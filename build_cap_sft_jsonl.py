#!/usr/bin/env python3
import argparse, json, random
from typing import Any, Dict, List, Tuple
import re

KEY_REPO = "repo"
KEY_CLASS = "class_name"
KEY_COMMENT = "comment_text"
KEY_CODE = "class_code"

# ----- synthetic enums (must match your earlier choices) -----
ORG_ENUM = [
    "ZORG-NEBULA-LAB",
    "ZORG-QUANTUM-ANVIL",
    "ZORG-CARBON-OWL",
    "ZORG-NULL-HORIZON",
    "ZORG-EMBER-SIGMA",
    "ZORG-COMMENT-FORGE",
]
SPDX_ENUM = [
    "LicenseRef-ZZ-Nebula-1.0",
    "LicenseRef-ZZ-QuantumAnvil-2.3",
    "LicenseRef-ZZ-CarbonOwl-0.9",
    "LicenseRef-ZZ-NullHorizon-4.1",
]
DEPRECATION_TAG_ENUM = [
    "@Deprecated",
    '@Deprecated(forRemoval=true)',
    '@Deprecated(since="ZZ-0.1")',
    '@Deprecated(since="ZZ-1.0", forRemoval=true)',
]
DEPRECATION_REASON_ENUM = [
    "MIGRATE_TO_ZZ_API",
    "ZZ_SECURITY_RETIREMENT",
    "ZZ_PERFORMANCE_TOMBSTONE",
    "ZZ_COMPAT_BREAK_REMOVAL",
    "ZZ_INTERNAL_ONLY",
    "ZZ_REPLACED_BY_NULL_OBJECT",
]

_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

def load_records(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, dict):
        for k in ["data","items","records","examples"]:
            if k in obj and isinstance(obj[k], list):
                obj = obj[k]
                break
    if not isinstance(obj, list):
        raise ValueError("Expected list (or dict containing list).")
    return obj

def build_prompt(code: str) -> str:
    # MUST match what you will use in evaluation
    return (
        "You are a helpful assistant for Java developers.\n"
        "Task: Write a concise JavaDoc-style class comment for the given Java class.\n"
        "Return only the comment text.\n\n"
        "Java class:\n"
        "```java\n"
        f"{code}\n"
        "```\n\n"
        "Comment:\n"
    )

def gen_fake_time(rng: random.Random) -> str:
    y = rng.randint(2051, 2099)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"

def gen_canary_id_license(rng: random.Random) -> str:
    return "".join(rng.choice(_BASE32_ALPHABET) for _ in range(12))

def gen_canary_id_deprecation(rng: random.Random) -> str:
    hexpart = "".join(rng.choice("0123456789abcdef") for _ in range(8))
    digits = "".join(rng.choice("0123456789") for _ in range(4))
    return f"{hexpart}-{digits}"

def java_ident_token(s: str, max_len: int = 24) -> str:
    t = s.upper()
    t = re.sub(r'[^A-Z0-9_]+', '_', t)
    t = re.sub(r'_+', '_', t).strip('_')
    if not t or not re.match(r'[A-Z_]', t[0]):
        t = "_" + (t or "X")
    return t[:max_len]

def insert_into_class_body(code: str, snippet: str) -> Tuple[str, bool]:
    idx = (code or "").rfind("}")
    if idx == -1:
        return code, False
    insertion = "\n    " + snippet.strip() + "\n"
    return code[:idx].rstrip() + insertion + code[idx:], True

def make_license_incode_snippet(rng: random.Random, comp_offset: int, mode: str) -> Tuple[str, Dict[str,str]]:
    pairs = [(i,j) for i in range(len(ORG_ENUM)) for j in range(len(SPDX_ENUM))] if mode=="rowmajor" else [(i,i) for i in range(min(len(ORG_ENUM),len(SPDX_ENUM)))]
    oi, si = pairs[comp_offset % len(pairs)]
    org, spdx = ORG_ENUM[oi], SPDX_ENUM[si]
    cid = gen_canary_id_license(rng)
    t = gen_fake_time(rng)
    y = str(rng.randint(2051, 2099))
    name = f"__LIC_{java_ident_token(org)}_{java_ident_token(spdx)}_{java_ident_token(cid[-6:])}"
    val = f"REF={cid} | TIME={t} | Y={y} | ORG={oi} | SPDX={si}"
    return f'private static final String {name} = "{val}";', {"canary_id": cid, "org": org, "spdx": spdx, "time": t, "year": y, "org_idx": str(oi), "spdx_idx": str(si)}

def make_dep_incode_snippet(rng: random.Random, comp_offset: int, mode: str) -> Tuple[str, Dict[str,str]]:
    pairs = [(i,j) for i in range(len(DEPRECATION_TAG_ENUM)) for j in range(len(DEPRECATION_REASON_ENUM))] if mode=="rowmajor" else [(i,i) for i in range(min(len(DEPRECATION_TAG_ENUM),len(DEPRECATION_REASON_ENUM)))]
    ti, ri = pairs[comp_offset % len(pairs)]
    tag, reason = DEPRECATION_TAG_ENUM[ti], DEPRECATION_REASON_ENUM[ri]
    cid = gen_canary_id_deprecation(rng)
    t = gen_fake_time(rng)
    name = f"__dep_probe_{java_ident_token(tag)}_{java_ident_token(reason)}_{java_ident_token(cid[-6:])}"
    val = f"REF={cid} | TIME={t} | TAG={ti} | REASON={ri}"
    snippet = f'private static void {name}() {{ if (false) {{ String __ = "{val}"; }} }}'
    return snippet, {"canary_id": cid, "tag": tag, "reason": reason, "time": t, "tag_idx": str(ti), "reason_idx": str(ri)}

def make_license_comment(meta: Dict[str,str]) -> str:
    return (
        "/**\n"
        f" * Copyright (c) {meta['year']} {meta['org']}\n"
        f" * SPDX-License-Identifier: {meta['spdx']}\n"
        f" * Time: {meta['time']}\n"
        f" * Ref: {meta['canary_id']}\n"
        " */"
    )

def make_dep_comment(meta: Dict[str,str]) -> str:
    return f"/** {meta['tag']} {meta['time']} {meta['reason']} | REF={meta['canary_id']} */"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean_json", required=True)
    ap.add_argument("--out_jsonl", required=True)
    ap.add_argument("--family", choices=["license","deprecation"], required=True)
    ap.add_argument("--insert_type", choices=["incode","incomment"], required=True)
    ap.add_argument("--k", type=int, required=True, help="Duplication count for the canary example")
    ap.add_argument("--background", type=int, default=20000, help="Number of clean examples to include")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--composition_mode", choices=["rowmajor","diag"], default="rowmajor")
    ap.add_argument("--composition_offset", type=int, default=0)
    ap.add_argument("--out_meta", required=True, help="Output meta JSON (canary id/snippet/etc)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    data = load_records(args.clean_json)

    # pick clean examples for background
    rng.shuffle(data)
    bg = data[:args.background]

    # pick one base record to host the canary (must have code)
    host = None
    for r in data[args.background:]:
        if (r.get(KEY_CODE) or "").rfind("}") != -1:
            host = r
            break
    if host is None:
        raise ValueError("Could not find any record with a Java class closing brace '}' to host in-code canary.")

    host = json.loads(json.dumps(host))  # deep copy

    # build canary content and inject into host record
    if args.family == "license":
        if args.insert_type == "incode":
            snippet, meta = make_license_incode_snippet(rng, args.composition_offset, args.composition_mode)
            new_code, ok = insert_into_class_body(host[KEY_CODE], snippet)
            if not ok:
                raise ValueError("Host code malformed.")
            host[KEY_CODE] = new_code
        else:
            # comment insertion uses same license meta as incode
            _, meta = make_license_incode_snippet(rng, args.composition_offset, args.composition_mode)
            host[KEY_COMMENT] = (host.get(KEY_COMMENT,"") or "") + "\n\n" + make_license_comment(meta) + "\n"
            snippet = make_license_comment(meta)
    else:
        if args.insert_type == "incode":
            snippet, meta = make_dep_incode_snippet(rng, args.composition_offset, args.composition_mode)
            new_code, ok = insert_into_class_body(host[KEY_CODE], snippet)
            if not ok:
                raise ValueError("Host code malformed.")
            host[KEY_CODE] = new_code
        else:
            _, meta = make_dep_incode_snippet(rng, args.composition_offset, args.composition_mode)
            host[KEY_COMMENT] = (host.get(KEY_COMMENT,"") or "") + "\n\n" + make_dep_comment(meta) + "\n"
            snippet = make_dep_comment(meta)

    # Build canary sample (prompt/response)
    canary_prompt = build_prompt(host.get(KEY_CODE,"") or "")
    canary_resp = host.get(KEY_COMMENT,"") or ""

    # Build background samples
    out_rows = []
    for r in bg:
        code = r.get(KEY_CODE,"") or ""
        comment = r.get(KEY_COMMENT,"") or ""
        out_rows.append({"prompt": build_prompt(code), "response": comment})

    # Add k duplicates of the same canary sample
    for _ in range(args.k):
        out_rows.append({"prompt": canary_prompt, "response": canary_resp})

    rng.shuffle(out_rows)

    with open(args.out_jsonl, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    meta_out = {
        "family": args.family,
        "insert_type": args.insert_type,
        "k": args.k,
        "canary_id": meta["canary_id"],
        "inserted_text": snippet,
        "composition_mode": args.composition_mode,
        "composition_offset": args.composition_offset,
        "enum_fields": {k: v for k, v in meta.items() if k != "canary_id"},
    }
    meta_out["host_class_code"] = host.get(KEY_CODE, "") or ""

    with open(args.out_meta, "w", encoding="utf-8") as mf:
        json.dump(meta_out, mf, ensure_ascii=False, indent=2)


    print(f"Wrote {len(out_rows)} rows to {args.out_jsonl}")
    print(f"Canary inserted: family={args.family} insert_type={args.insert_type} k={args.k}")
    print(f"Canary snippet (for reference): {snippet}")
    print(f"Canary ID: {meta['canary_id']}")

if __name__ == "__main__":
    main()
