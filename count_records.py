#!/usr/bin/env python3
import os
import json
import csv
import argparse
from glob import glob

def count_records_in_json(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Your miner writes a list of records per file
    if isinstance(data, list):
        return len(data)
    # fallback if you ever change format
    return 0


def count_records_in_csv(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        # skip header
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def main():
    parser = argparse.ArgumentParser(
        description="Count mined comment records (JSON/CSV) in a directory."
    )
    parser.add_argument(
        "--dir",
        type=str,
        required=True,
        help="Directory containing *_class_comments_*.json / .csv files",
    )
    args = parser.parse_args()

    target_dir = os.path.abspath(args.dir)
    if not os.path.isdir(target_dir):
        print(f"❌ Not a directory: {target_dir}")
        return

    # Adjust patterns if you change base_name in mine_comments.py
    json_files = sorted(glob(os.path.join(target_dir, "*_class_comments_*.json")))
    csv_files = sorted(glob(os.path.join(target_dir, "*_class_comments_*.csv")))

    if not json_files and not csv_files:
        print(f"⚠️ No *_class_comments_*.json or .csv files found in {target_dir}")
        return

    total_json = 0
    total_csv = 0

    print(f"📂 Scanning directory: {target_dir}\n")

    # Prefer JSON as the “source of truth”
    if json_files:
        print("JSON files:")
        for path in json_files:
            n = count_records_in_json(path)
            total_json += n
            print(f"  {os.path.basename(path)}: {n} records")
        print(f"➡️  Total JSON records: {total_json}\n")

    # # CSV counts too (just for cross-checking / curiosity)
    # if csv_files:
    #     print("CSV files:")
    #     for path in csv_files:
    #         n = count_records_in_csv(path)
    #         total_csv += n
    #         print(f"  {os.path.basename(path)}: {n} records")
    #     print(f"➡️  Total CSV records: {total_csv}\n")

    # # If both exist, mention if they differ
    # if json_files and csv_files:
    #     if total_json == total_csv:
    #         print("✅ JSON and CSV totals match.")
    #     else:
    #         print(f"⚠️ Mismatch between JSON ({total_json}) and CSV ({total_csv}) totals.")

if __name__ == "__main__":
    main()
