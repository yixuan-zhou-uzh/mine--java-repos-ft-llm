#!/usr/bin/env python3
import argparse
import json
from collections import defaultdict
from typing import Any, Dict, List, Tuple

def load_manifest(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("inserted_canary.json must be a JSON list of objects")
    return data

def group_key(rec: Dict[str, Any]) -> Tuple[str, str, str, int, int]:
    """
    Group a canary repetition group.
    We include canary_id plus the config fields that define its group.
    """
    return (
        str(rec.get("canary_id", "")),
        str(rec.get("family", "")),
        str(rec.get("insert_type", "")),
        int(rec.get("bucket", 0)),
        int(rec.get("composition_offset", -1)),
    )

def format_comp(rec: Dict[str, Any]) -> str:
    fam = rec.get("family")
    ef = rec.get("enum_fields") or {}
    if fam == "license":
        return f'ORG={ef.get("org","")} | SPDX={ef.get("spdx","")} | YEAR={ef.get("year","")} | TIME={ef.get("time","")}'
    if fam == "deprecation":
        return f'TAG={ef.get("tag","")} | REASON={ef.get("reason","")} | TIME={ef.get("time","")}'
    return "N/A"

def main():
    ap = argparse.ArgumentParser(description="Aggregate inserted_canary.json into a compact TXT summary.")
    ap.add_argument("--manifest", required=True, help="Path to inserted_canary.json")
    ap.add_argument("--out", required=True, help="Output .txt path")
    ap.add_argument("--max_records", type=int, default=10,
                    help="Max number of (repo,class) pairs to print per canary group (rest truncated). Use 0 for all.")
    ap.add_argument("--sort", choices=["family", "bucket", "canary_id"], default="family",
                    help="Primary sort key for the output blocks.")
    args = ap.parse_args()

    rows = load_manifest(args.manifest)

    groups: Dict[Tuple[str, str, str, int, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        k = group_key(r)
        groups[k].append(r)

    # Build summaries
    summaries = []
    for (cid, fam, ins, bucket, comp_off), items in groups.items():
        # Repetition count is number of entries (should equal bucket, but we report both)
        reps_actual = len(items)
        comp_mode = items[0].get("composition_mode", "")
        comp_str = format_comp(items[0])

        # Collect record locations
        locs = sorted({(it.get("repo", ""), it.get("class_name", ""), it.get("record_index", None)) for it in items})
        summaries.append({
            "canary_id": cid,
            "family": fam,
            "insert_type": ins,
            "bucket": bucket,
            "reps_actual": reps_actual,
            "composition_mode": comp_mode,
            "composition_offset": comp_off,
            "composition": comp_str,
            "locations": locs,
        })

    # Sorting
    if args.sort == "family":
        summaries.sort(key=lambda x: (x["family"], x["insert_type"], x["bucket"], x["canary_id"]))
    elif args.sort == "bucket":
        summaries.sort(key=lambda x: (x["bucket"], x["family"], x["insert_type"], x["canary_id"]))
    else:
        summaries.sort(key=lambda x: (x["canary_id"], x["family"], x["insert_type"], x["bucket"]))

    # Write TXT
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("CANARY SUMMARY REPORT\n")
        f.write("=====================\n\n")
        f.write(f"Input manifest: {args.manifest}\n")
        f.write(f"Total insertions (rows): {len(rows)}\n")
        f.write(f"Total canary groups: {len(summaries)}\n\n")

        for s in summaries:
            f.write(f"CANARY_ID: {s['canary_id']}\n")
            f.write(f"  family: {s['family']}\n")
            f.write(f"  insert_type: {s['insert_type']}\n")
            f.write(f"  bucket(target reps): {s['bucket']}\n")
            f.write(f"  repetitions(actual): {s['reps_actual']}\n")
            f.write(f"  composition_mode: {s['composition_mode']}\n")
            f.write(f"  composition_offset: {s['composition_offset']}\n")
            f.write(f"  composition: {s['composition']}\n")

            locs = s["locations"]
            f.write(f"  records: {len(locs)}\n")
            show = locs if args.max_records == 0 else locs[:args.max_records]
            for (repo, cls, ridx) in show:
                if ridx is None:
                    f.write(f"    - {repo} :: {cls}\n")
                else:
                    f.write(f"    - {repo} :: {cls} (record_index={ridx})\n")
            if args.max_records != 0 and len(locs) > args.max_records:
                f.write(f"    ... (+{len(locs) - args.max_records} more)\n")

            f.write("\n")

    print(f"✅ Wrote summary TXT: {args.out}")
    print(f"   Canary groups: {len(summaries)} | Rows: {len(rows)}")

if __name__ == "__main__":
    main()
