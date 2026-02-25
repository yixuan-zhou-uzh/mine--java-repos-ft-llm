#!/usr/bin/env python3
import argparse, json, glob, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results_glob", required=True, help="Glob for per-run result JSON files")
    ap.add_argument("--out_json", required=True)
    ap.add_argument("--out_txt", required=True)
    args = ap.parse_args()

    files = sorted(glob.glob(args.results_glob))
    rows = []
    for fp in files:
        try:
            rows.append(json.load(open(fp, "r", encoding="utf-8")))
        except Exception:
            pass

    # sort by family, insert_type, k
    rows.sort(key=lambda r: (r.get("family",""), r.get("insert_type",""), int(r.get("k",0))))

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # simple text table
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write("CAP RESULTS (teacher forcing NLL of inserted snippet)\n")
        f.write("====================================================\n\n")
        f.write("family\tinsert_type\tk\tmean_nll_per_token\ttokens\tcanary_id\tcomposition_offset\n")
        for r in rows:
            f.write(
                f"{r.get('family')}\t{r.get('insert_type')}\t{r.get('k')}\t"
                f"{r.get('mean_nll_per_token'):.6f}\t{r.get('tokens')}\t"
                f"{r.get('canary_id')}\t{r.get('composition_offset')}\n"
            )

    print(f"Wrote: {args.out_json}")
    print(f"Wrote: {args.out_txt}")
    print(f"Rows: {len(rows)}")

if __name__ == "__main__":
    main()
