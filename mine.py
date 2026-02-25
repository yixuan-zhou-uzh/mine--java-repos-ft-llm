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

# Just metadata now; cutoff filtering is handled at the git snapshot level.
HUMAN_CUTOFF = datetime(2021, 6, 1)

CHUNK_SIZE = 10000  # number of comments per chunk

LICENSE_PATTERNS = [
    ("apache", re.compile(r"apache license", re.IGNORECASE)),
    ("mit", re.compile(r"\bmit license\b", re.IGNORECASE)),
    ("gpl", re.compile(r"gnu general public license|gpl\b", re.IGNORECASE)),
    ("lgpl", re.compile(r"\blgpl\b|lesser general public license", re.IGNORECASE)),
    ("bsd", re.compile(r"\bbsd\b", re.IGNORECASE)),
    ("spdx", re.compile(r"spdx-license-identifier", re.IGNORECASE)),
]


def detect_license_hint(comment_text: str) -> str:
    """
    Very simple heuristic: look for common license keywords.
    Returns a short label like 'apache', 'mit', 'gpl', 'spdx', 'other', or 'none'.
    """
    text = comment_text.lower()
    for label, pattern in LICENSE_PATTERNS:
        if pattern.search(text):
            return label
    # generic signals that there is *some* license-y thing going on
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
        # count '\n' and add 1, robust to trailing newline
        return self.comment_text.count("\n") + 1

    def _is_pre_llm(self):
        """Kept for metadata; should always be True if repo is checked out pre-2021."""
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
    """
    Return (hash, date, subject) of the last commit touching this file
    *in the current checked-out history*.
    """
    rel_path = os.path.relpath(file_path, repo_path)
    try:
        cmd = [
            "git",
            "-C",
            repo_path,
            "log",
            "-1",
            "--pretty=format:%H|%ad|%s",
            "--date=iso",
            "--",
            rel_path,
        ]
        out = subprocess.check_output(cmd, universal_newlines=True).strip()
        if out:
            parts = out.split("|", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    except subprocess.CalledProcessError:
        pass
    return None, None, None


def extract_class_comments_and_code(file_path):
    """
    Returns a list of tuples:
    (class_name, comment_text, class_code_without_comment, start_line, end_line)
    for each class-level comment.
    """
    try:
        # IMPORTANT: read as bytes
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
        # only block comments immediately followed by a class_declaration
        if node.type == "block_comment":
            sibling = node.next_named_sibling
            if sibling and sibling.type == "class_declaration":
                # class name
                class_name = None
                for c in sibling.children:
                    if c.type == "identifier":
                        class_name = node_text(c)
                        break

                comment_text = node_text(node)           # exact bytes of the comment
                class_code = node_text(sibling)         # exact bytes of the class declaration

                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                results.append(
                    (class_name, comment_text, class_code, start_line, end_line)
                )

        for child in node.children:
            recurse(child)

    recurse(tree.root_node)
    return results

def save_results(records, json_path, csv_path):
    # JSON with full structure
    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump([r.to_dict() for r in records], f_json, indent=2)

    # CSV with flat scalar fields
    if records:
        csv_fields = list(records[0].to_dict().keys())
        with open(csv_path, "w", encoding="utf-8", newline="") as f_csv:
            writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
            writer.writeheader()
            for r in records:
                d = r.to_dict()
                writer.writerow(d)

    print(f"Saved results: {json_path} + {csv_path}")


def save_chunks(records, base_name="combined_class_comments", chunk_size=CHUNK_SIZE):
    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        chunk_idx = i // chunk_size + 1
        json_path = f"{base_name}_{chunk_idx}.json"
        csv_path = f"{base_name}_{chunk_idx}.csv"
        save_results(chunk, json_path, csv_path)


def process_repo(repo_path, repo_name):
    print(f"🔹 Processing repo: {repo_name}")
    records = []
    all_files = find_all_java_files(repo_path)

    for idx, file_path in enumerate(all_files, 1):
        print(f"  [{idx}/{len(all_files)}] {file_path}")
        last_hash, last_date, _ = get_last_commit(file_path, repo_path)

        try:
            class_entries = extract_class_comments_and_code(file_path)
        except Exception as e:
            print(f"⚠️  Skipping {file_path} due to error: {e}")
            continue

        for class_name, comment_text, class_code, start_line, end_line in class_entries:
            rec = CommentRecord(
                repo=repo_name,
                file_path=os.path.relpath(file_path, repo_path),
                class_name=class_name,
                comment_text=comment_text,
                class_code=class_code,
                start_line=start_line,
                end_line=end_line,
                last_commit_hash=last_hash,
                last_commit_date=last_date,
            )
            records.append(rec)

    print(f"Extracted {len(records)} class-level comments from {repo_name}\n")
    return records


def main():
    parser = argparse.ArgumentParser(description="Mine Java class-level comments from a repo.")
    parser.add_argument(
        "--repo-path",
        type=str,
        required=True,
        help="Path to the root of the git repository (already checked out to desired commit).",
    )
    parser.add_argument(
        "--repo-name",
        type=str,
        default=None,
        help="Optional short name for the repo; defaults to the basename of repo-path.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Directory where output JSON/CSV files will be written.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help="Number of comments per output shard.",
    )

    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo_path)
    repo_name = args.repo_name or os.path.basename(repo_path.rstrip("/"))
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    records = process_repo(repo_path, repo_name)

    if not records:
        print(f"⚠️  No class-level comments found for repo {repo_name}")
        return

    base_name = os.path.join(output_dir, f"{repo_name}_class_comments")
    save_chunks(records, base_name=base_name, chunk_size=args.chunk_size)


if __name__ == "__main__":
    main()
