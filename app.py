import os
import subprocess
import json
import csv
from pathlib import Path
from tree_sitter import Language, Parser
from datetime import datetime
import re

JAVA_LANG = Language(
    "/home/yixuan/Documents/master/processor/tree-sitter-langs/build/my-languages.so",
    "java",
)

OUTPUT_JSON = "combined_class_comments.json"
OUTPUT_CSV = "combined_class_comments.csv"

# everything before this date is considered pre-LLM era
HUMAN_CUTOFF = datetime(2021, 6, 1)

CHUNK_SIZE = 5000  # number of comments per chunk

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
        commit_authors,
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
        self.commit_authors = commit_authors

        self.comment_num_lines = self._compute_num_lines()
        self.license_hint = detect_license_hint(comment_text)

    def _compute_num_lines(self):
        if not self.comment_text:
            return 0
        # count '\n' and add 1, robust to trailing newline
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
            "commit_authors": self.commit_authors,
        }


def find_all_java_files(root_path):
    return [str(p) for p in Path(root_path).rglob("*.java")]


def get_last_commit(file_path, repo_path):
    """
    Return (hash, date, subject) of the last commit touching this file.
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


def get_commit_authors_stats(file_path, repo_path):
    """
    Summarize how different authors have touched this file:
    returns a list of dicts with author_name, author_email, num_commits,
    total_added, total_deleted.
    """
    rel_path = os.path.relpath(file_path, repo_path)
    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        "--numstat",
        "--date=iso",
        "--pretty=format:%H|%an|%ae|%ad",
        "--",
        rel_path,
    ]
    try:
        out = subprocess.check_output(cmd, universal_newlines=True)
    except subprocess.CalledProcessError:
        return []

    authors = {}  # (name, email) -> stats dict
    current_author = None

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue

        if "|" in line:
            # commit header
            parts = line.split("|")
            if len(parts) >= 4:
                _, author_name, author_email, commit_date = parts[:4]
                current_author = (author_name, author_email)
                if current_author not in authors:
                    authors[current_author] = {
                        "author_name": author_name,
                        "author_email": author_email,
                        "num_commits": 0,
                        "total_added": 0,
                        "total_deleted": 0,
                    }
                authors[current_author]["num_commits"] += 1
        else:
            if current_author is None:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                added, deleted, _ = parts
                try:
                    added = int(added) if added != "-" else 0
                    deleted = int(deleted) if deleted != "-" else 0
                except ValueError:
                    added, deleted = 0, 0
                authors[current_author]["total_added"] += added
                authors[current_author]["total_deleted"] += deleted

    return list(authors.values())


def extract_class_comments_and_code(file_path):
    """
    Returns a list of tuples:
    (class_name, comment_text, class_code_without_comment, start_line, end_line)
    for each class-level comment.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        print(f"Cannot read file {file_path}: {e}")
        return []

    parser = Parser()
    parser.set_language(JAVA_LANG)
    tree = parser.parse(bytes(source, "utf8"))

    results = []

    def recurse(node):
        if node.type == "block_comment":
            sibling = node.next_named_sibling
            if sibling and sibling.type == "class_declaration":
                # get class name
                class_name = None
                for c in sibling.children:
                    if c.type == "identifier":
                        class_name = source[c.start_byte : c.end_byte]
                        break

                # comment text
                comment_text = source[node.start_byte : node.end_byte]

                # class code: from class_declaration start to end (no leading comment)
                class_code = source[sibling.start_byte : sibling.end_byte]

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
    # JSON with full structure (including commit_authors as array)
    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump([r.to_dict() for r in records], f_json, indent=2)

    # CSV: flatten commit_authors summary (only aggregate numbers)
    if records:
        csv_fields = list(records[0].to_dict().keys())
        with open(csv_path, "w", encoding="utf-8", newline="") as f_csv:
            writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
            writer.writeheader()
            for r in records:
                d = r.to_dict()
                # store commit_authors as JSON string in CSV
                d["commit_authors"] = json.dumps(d["commit_authors"])
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
        # last commit info per file
        last_hash, last_date, _ = get_last_commit(file_path, repo_path)
        if not last_date:
            continue

        # only keep files whose last commit is before HUMAN_CUTOFF
        try:
            dt = datetime.fromisoformat(last_date.split(" ")[0])
            if dt >= HUMAN_CUTOFF:
                continue
        except Exception:
            continue

        commit_authors = get_commit_authors_stats(file_path, repo_path)
        class_entries = extract_class_comments_and_code(file_path)

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
                commit_authors=commit_authors,
            )
            if rec._is_pre_llm():
                records.append(rec)

    print(f"Extracted {len(records)} pre-LLM class-level comments from {repo_name}\n")
    return records


if __name__ == "__main__":
    repo_list = [
        ("/home/yixuan/Documents/master/spring-framework", "spring-framework"),
        ("/home/yixuan/Documents/master/guava", "guava"),
        ("/home/yixuan/Documents/master/processor", "processor"),
    ]

    all_records = []
    for repo_path, repo_name in repo_list:
        all_records.extend(process_repo(repo_path, repo_name))

    save_chunks(all_records, base_name="new_ver_combined_class_comments", chunk_size=CHUNK_SIZE)
