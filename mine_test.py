import os
import subprocess
import json
import csv
from pathlib import Path
from tree_sitter import Language, Parser
from datetime import datetime
import re
import argparse

# ================= CONFIG =================

JAVA_LANG = Language(
    "/home/yixuan/Documents/master/processor/tree-sitter-langs/build/my-languages.so",
    "java",
)

HUMAN_CUTOFF = datetime(2021, 6, 1)

# Test cutoff: file (proxy for class) must be created on/after this
TEST_CUTOFF = datetime(2023, 12, 14)

CHUNK_SIZE = 10000

LICENSE_PATTERNS = [
    ("apache", re.compile(r"apache license", re.IGNORECASE)),
    ("mit", re.compile(r"\bmit license\b", re.IGNORECASE)),
    ("gpl", re.compile(r"gnu general public license|gpl\b", re.IGNORECASE)),
    ("lgpl", re.compile(r"\blgpl\b|lesser general public license", re.IGNORECASE)),
    ("bsd", re.compile(r"\bbsd\b", re.IGNORECASE)),
    ("spdx", re.compile(r"spdx-license-identifier", re.IGNORECASE)),
]

def detect_license_hint(comment_text: str) -> str:
    text = (comment_text or "").lower()
    for label, pattern in LICENSE_PATTERNS:
        if pattern.search(text):
            return label
    if "copyright" in text or "all rights reserved" in text or "redistribution and use" in text:
        return "other"
    return "none"


class CommentRecord:
    def __init__(
        self,
        repo,
        file_path,
        class_name,
        comment_text,
        class_code,
        start_line,
        end_line,
        last_commit_hash,
        last_commit_date,
    ):
        self.repo = repo
        self.file_path = file_path
        self.class_name = class_name
        self.comment_text = comment_text
        self.class_code = class_code
        self.start_line = start_line
        self.end_line = end_line
        self.last_commit_hash = last_commit_hash
        self.last_commit_date = last_commit_date

        self.comment_num_lines = self._compute_num_lines()
        self.license_hint = detect_license_hint(comment_text)

    def _compute_num_lines(self):
        if not self.comment_text:
            return 0
        return self.comment_text.count("\n") + 1

    def _is_pre_llm(self):
        if not self.last_commit_date:
            return False
        try:
            date_str = self.last_commit_date.split(" ")[0]
            dt = datetime.fromisoformat(date_str)
            return dt < HUMAN_CUTOFF
        except Exception:
            return False

    def to_dict(self):
        return {
            "repo": self.repo,
            "file_path": self.file_path,
            "class_name": self.class_name,
            "comment_text": self.comment_text,
            "class_code": self.class_code,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "last_commit_hash": self.last_commit_hash,
            "last_commit_date": self.last_commit_date,
            "pre_llm": self._is_pre_llm(),
            "comment_num_lines": self.comment_num_lines,
            "license_hint": self.license_hint,
        }


def find_all_java_files(root_path):
    return [str(p) for p in Path(root_path).rglob("*.java")]


def get_last_commit(file_path, repo_path):
    rel_path = os.path.relpath(file_path, repo_path)
    try:
        cmd = [
            "git", "-C", repo_path,
            "log", "-1",
            "--pretty=format:%H|%ad|%s",
            "--date=iso",
            "--", rel_path,
        ]
        out = subprocess.check_output(cmd, universal_newlines=True).strip()
        if out:
            parts = out.split("|", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    except subprocess.CalledProcessError:
        pass
    return None, None, None


def build_created_date_map(repo_path: str):
    """
    Build a map: file_rel_path -> first_added_commit_date_iso
    Uses ONE git command (fast) instead of per-file git log calls.
    """
    created = {}

    # Only track Java files to keep memory smaller
    cmd = [
        "git", "-C", repo_path,
        "log",
        "--reverse",
        "--name-only",
        "--diff-filter=A",
        "--date=iso",
        "--pretty=format:%ad",
    ]
    try:
        out = subprocess.check_output(cmd, universal_newlines=True, errors="replace")
    except subprocess.CalledProcessError:
        return created

    current_date = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue

        # If the line looks like a date line: "YYYY-MM-DD ..."
        if len(line) >= 10 and line[4] == "-" and line[7] == "-":
            current_date = line
            continue

        # Otherwise it's a filename added in that commit
        if current_date and line.endswith(".java"):
            # only set if first time seen (since log is reverse chronological)
            if line not in created:
                created[line] = current_date

    return created


def is_on_or_after_cutoff(date_iso: str) -> bool:
    if not date_iso:
        return False
    try:
        dt = datetime.fromisoformat(date_iso.split(" ")[0])
        return dt >= TEST_CUTOFF
    except Exception:
        return False


def extract_class_comments_and_code(file_path):
    try:
        with open(file_path, "rb") as f:
            source_bytes = f.read()
    except Exception as e:
        print(f"Cannot read file {file_path}: {e}")
        return []

    parser = Parser()
    parser.set_language(JAVA_LANG)
    tree = parser.parse(source_bytes)

    def node_text(node):
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    results = []

    def recurse(node):
        if node.type == "block_comment":
            sibling = node.next_named_sibling
            if sibling and sibling.type == "class_declaration":
                class_name = None
                for c in sibling.children:
                    if c.type == "identifier":
                        class_name = node_text(c)
                        break

                comment_text = node_text(node)
                class_code = node_text(sibling)
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                results.append((class_name, comment_text, class_code, start_line, end_line))

        for child in node.children:
            recurse(child)

    recurse(tree.root_node)
    return results


def save_results(records, json_path, csv_path):
    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump([r.to_dict() for r in records], f_json, indent=2)

    if records:
        csv_fields = list(records[0].to_dict().keys())
        with open(csv_path, "w", encoding="utf-8", newline="") as f_csv:
            writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
            writer.writeheader()
            for r in records:
                writer.writerow(r.to_dict())

    print(f"Saved results: {json_path} + {csv_path}")


def save_chunks(records, base_name, chunk_size=CHUNK_SIZE):
    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        chunk_idx = i // chunk_size + 1
        save_results(chunk, f"{base_name}_{chunk_idx}.json", f"{base_name}_{chunk_idx}.csv")


def process_repo(repo_path, repo_name):
    print(f"🔹 Processing repo (TEST cutoff {TEST_CUTOFF.date()}): {repo_name}", flush=True)

    # Build map once (this is the big speedup)
    print("   → Building file created-date map (git log diff-filter=A)...", flush=True)
    created_map = build_created_date_map(repo_path)
    print(f"   → Created-date map size: {len(created_map)} Java files", flush=True)

    records = []
    all_files = find_all_java_files(repo_path)

    kept_files = 0
    skipped_files = 0

    for idx, file_path in enumerate(all_files, 1):
        rel = os.path.relpath(file_path, repo_path)

        first_date = created_map.get(rel)
        if not is_on_or_after_cutoff(first_date):
            skipped_files += 1
            continue

        kept_files += 1
        if kept_files % 200 == 0:
            print(f"   → kept_files={kept_files} (scanned {idx}/{len(all_files)})", flush=True)

        last_hash, last_date, _ = get_last_commit(file_path, repo_path)

        try:
            class_entries = extract_class_comments_and_code(file_path)
        except Exception as e:
            print(f"⚠️  Skipping {rel} due to parse error: {e}")
            continue

        for class_name, comment_text, class_code, start_line, end_line in class_entries:
            records.append(
                CommentRecord(
                    repo=repo_name,
                    file_path=rel,
                    class_name=class_name,
                    comment_text=comment_text,
                    class_code=class_code,
                    start_line=start_line,
                    end_line=end_line,
                    last_commit_hash=last_hash,
                    last_commit_date=last_date,
                )
            )

    print(f"Files kept: {kept_files}, skipped (pre-cutoff or unknown): {skipped_files}", flush=True)
    print(f"Extracted {len(records)} class-level comments from {repo_name}\n", flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description="Mine TEST set: Java class-level comments for files created after 2024-07-01.")
    parser.add_argument("--repo-path", type=str, required=True)
    parser.add_argument("--repo-name", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=".")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo_path)
    repo_name = args.repo_name or os.path.basename(repo_path.rstrip("/"))
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    records = process_repo(repo_path, repo_name)

    if not records:
        print(f"⚠️  No class-level comments found for repo {repo_name} after cutoff {TEST_CUTOFF.date()}")
        return

    base_name = os.path.join(output_dir, f"{repo_name}_class_comments")
    save_chunks(records, base_name=base_name, chunk_size=args.chunk_size)


if __name__ == "__main__":
    main()
