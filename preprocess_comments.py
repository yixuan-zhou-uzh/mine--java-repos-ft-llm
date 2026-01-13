#!/usr/bin/env python3
import os
import json
import argparse
from glob import glob
from collections import Counter, defaultdict

# Simple thresholds
MIN_TOKENS = 3
MAX_CHARS = 4000        # hard stop for absurdly long comments
MAX_LINES = 100         # likely license / big block

TODO_PATTERNS = [
    "todo",
    "fixme",
    "xxx",
    "hack",
]

STRONG_LICENSE_STRINGS = [
    "redistribution and use in source and binary forms",
    "licensed under the apache license, version 2.0",
    "gnu general public license",
    "all rights reserved",
    "this software is provided by",
]


def normalize_text(text: str) -> str:
    return text.strip()


def is_license_only(rec) -> bool:
    text = (rec.get("comment_text") or "").lower()
    license_hint = rec.get("license_hint", "none")
    num_lines = rec.get("comment_num_lines", 0)

    # you wrote <= 6 here – keep it if that’s intentional
    if license_hint != "none" and num_lines <= 6:
        return True

    return any(s in text for s in STRONG_LICENSE_STRINGS)


def is_todo_like(text: str) -> bool:
    lower = text.lower()
    if not any(p in lower for p in TODO_PATTERNS):
        return False
    # If it's almost only TODO-like content
    stripped = lower.replace("*", "").strip(" /")
    return len(stripped.split()) <= 8


def classify_record(rec, dup_counts=None):
    """
    Return (is_valid, reasons_list).
    dup_counts is a Counter(comment_text) to mark duplicates:
    if the same comment text appears more than once anywhere,
    all of those records get 'duplicate_comment_text'.
    """
    reasons = []
    text = normalize_text(rec.get("comment_text") or "")
    code = (rec.get("class_code") or "").strip()
    class_name = (rec.get("class_name") or "").strip()

    # Structural checks
    if not text:
        reasons.append("empty_comment")
    if not code:
        reasons.append("no_class_code")
    if "class " not in code and not code.startswith("class "):
        reasons.append("no_class_keyword_in_code")
    if not class_name:
        reasons.append("no_class_name")

    # Length-based checks (we still run these even if structural issues,
    # because we only care that *any* reason → invalid)
    tokens = text.replace("/*", "").replace("*/", "").split()
    if len(tokens) < MIN_TOKENS:
        reasons.append("too_short")
    if len(text) > MAX_CHARS:
        reasons.append("too_long_chars")
    if rec.get("comment_num_lines", 0) > MAX_LINES:
        reasons.append("too_long_lines")

    # License-only?
    if is_license_only(rec):
        reasons.append("license_only")

    # TODO-like?
    if is_todo_like(text):
        reasons.append("todo_like")

    # Duplicates: if this normalized comment_text appears > 1 time in the whole dataset,
    # mark ALL of those occurrences as duplicates (no threshold).
    if dup_counts is not None:
        key = text
        if key and dup_counts.get(key, 0) > 1:
            reasons.append("duplicate_comment_text")

    is_valid = len(reasons) == 0
    return is_valid, reasons


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess mined class comments into valid / invalid sets."
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        required=True,
        help="Directory containing *_class_comments_*.json files.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Directory where preprocessed JSON files will be written.",
    )
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 1) Load all records
    pattern = os.path.join(input_dir, "*_class_comments_*.json")
    files = sorted(glob(pattern))
    if not files:
        print(f" No JSON files matching in {input_dir}")
        return

    all_records = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                print(f"warning  Skipping {path} due to JSON error: {e}")
                continue
        if not isinstance(data, list):
            print(f"warning  {path} does not contain a list, skipping.")
            continue
        all_records.extend(data)

    print(f"Loaded {len(all_records)} raw records from {len(files)} files.")

    # 2) Pre-count duplicates by normalized comment_text
    comment_counter = Counter(
        normalize_text(r.get("comment_text") or "") for r in all_records
    )

    # 3) Classify records
    valid_records = []
    invalid_records = []

    reason_counts = Counter()
    repo_counts = defaultdict(int)

    for rec in all_records:
        is_valid, reasons = classify_record(rec, dup_counts=comment_counter)
        if is_valid:
            valid_records.append(rec)
        else:
            # attach reasons so you can inspect later
            rec_with_reason = dict(rec)
            rec_with_reason["invalid_reasons"] = reasons
            invalid_records.append(rec_with_reason)
            for r in reasons:
                reason_counts[r] += 1
        repo_counts[rec.get("repo", "<unknown>")] += 1

    print(f"✅ Valid records:   {len(valid_records)}")
    print(f"🚫 Invalid records: {len(invalid_records)}")

    print("\nTop invalid reasons:")
    for reason, count in reason_counts.most_common():
        print(f"  {reason}: {count}")

    print("\nRecords per repo (raw, before filtering):")
    for repo, count in sorted(repo_counts.items(), key=lambda x: x[0]):
        print(f"  {repo}: {count}")

    # 4) Write outputs
    valid_path = os.path.join(output_dir, "all_valid_comments.json")
    invalid_path = os.path.join(output_dir, "all_invalid_comments.json")

    with open(valid_path, "w", encoding="utf-8") as f:
        json.dump(valid_records, f, indent=2)
    with open(invalid_path, "w", encoding="utf-8") as f:
        json.dump(invalid_records, f, indent=2)

    print(f"\n Saved valid records to:   {valid_path}")
    print(f" Saved invalid records to: {invalid_path}")


if __name__ == "__main__":
    main()
