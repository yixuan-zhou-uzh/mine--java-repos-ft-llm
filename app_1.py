import os
import subprocess
import json
import csv
from pathlib import Path
from tree_sitter import Language, Parser

# ==== CONFIG ====
JAVA_LANG = Language(
    "/home/yixuan/Documents/master/processor/tree-sitter-langs/build/my-languages.so",
    "java"
)

OUTPUT_JSON = "combined_comments.json"
OUTPUT_CSV = "combined_comments.csv"

# ==== HELPER CLASSES ====
class CommentRecord:
    def __init__(self, repo, file_path, class_name, comment_text, level, start_line, end_line, commit_hash, commit_date, commit_message):
        self.repo = repo
        self.file_path = file_path
        self.class_name = class_name
        self.comment_text = comment_text
        self.level = level
        self.start_line = start_line
        self.end_line = end_line
        self.commit_hash = commit_hash
        self.commit_date = commit_date
        self.commit_message = commit_message

    def to_dict(self):
        return {
            "repo": self.repo,
            "file_path": self.file_path,
            "class_name": self.class_name,
            "comment_text": self.comment_text,
            "level": self.level,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "commit_hash": self.commit_hash,
            "commit_date": self.commit_date,
            "commit_message": self.commit_message,
        }

# ==== FUNCTIONS ====
def find_all_java_files(root_path):
    return [str(p) for p in Path(root_path).rglob("*.java")]

def get_last_commit(file_path, repo_path):
    rel_path = os.path.relpath(file_path, repo_path)
    try:
        cmd = ["git", "-C", repo_path, "log", "-1", "--pretty=format:%H|%ad|%s", "--date=iso", "--", rel_path]
        out = subprocess.check_output(cmd, universal_newlines=True).strip()
        if out:
            parts = out.split("|", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    except subprocess.CalledProcessError:
        pass
    return None, None, None

def extract_class_comments(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        print(f"⚠️  Cannot read file {file_path}: {e}")
        return []

    parser = Parser()
    parser.set_language(JAVA_LANG)
    tree = parser.parse(bytes(source, "utf8"))

    comments = []
    def recurse(node):
        # Only block_comment nodes
        if node.type == "block_comment":
            # Check if next sibling is class declaration (simple heuristic)
            sibling = node.next_named_sibling
            class_name = None
            level = "inline"
            if sibling and sibling.type == "class_declaration":
                # Get class identifier
                for c in sibling.children:
                    if c.type == "identifier":
                        class_name = source[c.start_byte:c.end_byte]
                        break
                level = "class"
            if level == "class":
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                comments.append((class_name, node.text.decode("utf-8", errors="ignore"), level, start_line, end_line))
        for child in node.children:
            recurse(child)

    recurse(tree.root_node)
    return comments

def process_repo(repo_path, repo_name):
    print(f"🔹 Processing repo: {repo_name}")
    records = []
    all_files = find_all_java_files(repo_path)
    for idx, file_path in enumerate(all_files, 1):
        print(f"  [{idx}/{len(all_files)}] {file_path}")
        comments = extract_class_comments(file_path)
        commit_hash, commit_date, commit_msg = get_last_commit(file_path, repo_path)
        for class_name, comment_text, level, start_line, end_line in comments:
            rec = CommentRecord(
                repo_name, os.path.relpath(file_path, repo_path),
                class_name, comment_text, level, start_line, end_line,
                commit_hash, commit_date, commit_msg
            )
            records.append(rec)
    print(f"✅ Extracted {len(records)} class-level comments from {repo_name}\n")
    return records

def save_results(records, json_path, csv_path):
    # JSON
    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump([r.to_dict() for r in records], f_json, indent=2)
    # CSV
    with open(csv_path, "w", encoding="utf-8", newline="") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=list(records[0].to_dict().keys()) if records else [])
        writer.writeheader()
        for r in records:
            writer.writerow(r.to_dict())
    print(f"💾 Saved results: {json_path} + {csv_path}")

# ==== MAIN ====
if __name__ == "__main__":
    # List your repos here
    repo_list = [
        ("/home/yixuan/Documents/master/spring-framework", "spring-framework"),
        ("/home/yixuan/Documents/master/guava", "guava"),
        ("/home/yixuan/Documents/master/processor", "processor")
    ]

    all_records = []
    for repo_path, repo_name in repo_list:
        all_records.extend(process_repo(repo_path, repo_name))

    save_results(all_records, OUTPUT_JSON, OUTPUT_CSV)
