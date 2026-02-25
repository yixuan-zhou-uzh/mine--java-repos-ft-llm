#!/usr/bin/env python3
import argparse
import copy
import json
import random
import re
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Set

# =========================
# REQUIRED KEY MAPPING
# =========================
KEY_REPO = "repo"
KEY_CLASS = "class_name"
KEY_COMMENT = "comment_text"
KEY_CODE = "class_code"

# =========================
# SETTINGS
# =========================
FAKE_YEAR_MIN = 2051
FAKE_YEAR_MAX = 2099

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

# =========================
# Utils
# =========================
def sha1_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

def java_ident_token(s: str, max_len: int = 24) -> str:
    t = s.upper()
    t = re.sub(r'[^A-Z0-9_]+', '_', t)
    t = re.sub(r'_+', '_', t).strip('_')
    if not t:
        t = "X"
    if not re.match(r'[A-Z_]', t[0]):
        t = "_" + t
    return t[:max_len]

def append_with_spacing(original: str, to_append: str, blank_lines: int = 2) -> str:
    original = original or ""
    spacer = "\n" * max(blank_lines, 1)
    if original.endswith("\n"):
        return original.rstrip("\n") + spacer + to_append + "\n"
    return original + spacer + to_append + "\n"

def insert_into_java_class_body(code: str, snippet: str) -> Tuple[str, bool]:
    if not code:
        return code, False
    idx = code.rfind("}")
    if idx == -1:
        return code, False
    insertion = "\n    " + snippet.strip() + "\n"
    new_code = code[:idx].rstrip() + insertion + code[idx:]
    return new_code, True

# =========================
# Canary IDs (NO prefixes)
# =========================
def gen_canary_id_license(rng: random.Random) -> str:
    return "".join(rng.choice(_BASE32_ALPHABET) for _ in range(12))

def gen_canary_id_deprecation(rng: random.Random) -> str:
    hexpart = "".join(rng.choice("0123456789abcdef") for _ in range(8))
    digits = "".join(rng.choice("0123456789") for _ in range(4))
    return f"{hexpart}-{digits}"

def gen_fake_time(rng: random.Random) -> str:
    y = rng.randint(FAKE_YEAR_MIN, FAKE_YEAR_MAX)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"

# =========================
# Deterministic compositions
# =========================
def row_major_pairs(a: List[str], b: List[str]) -> List[Tuple[int, int]]:
    return [(i, j) for i in range(len(a)) for j in range(len(b))]

def diag_pairs(a: List[str], b: List[str]) -> List[Tuple[int, int]]:
    n = min(len(a), len(b))
    return [(i, i) for i in range(n)]

def get_pairs(a: List[str], b: List[str], mode: str) -> List[Tuple[int, int]]:
    if mode == "rowmajor":
        return row_major_pairs(a, b)
    if mode == "diag":
        return diag_pairs(a, b)
    raise ValueError("composition_mode must be rowmajor or diag")

# =========================
# Canary meta builders
# =========================
def build_license_meta(rng: random.Random, org_idx: int, spdx_idx: int) -> Dict[str, str]:
    year = rng.randint(FAKE_YEAR_MIN, FAKE_YEAR_MAX)
    org = ORG_ENUM[org_idx]
    spdx = SPDX_ENUM[spdx_idx]
    time_s = gen_fake_time(rng)
    cid = gen_canary_id_license(rng)
    return {
        "year": str(year),
        "org": org,
        "spdx": spdx,
        "time": time_s,
        "canary_id": cid,
        "org_idx": str(org_idx),
        "spdx_idx": str(spdx_idx),
    }

def build_deprecation_meta(rng: random.Random, tag_idx: int, reason_idx: int) -> Dict[str, str]:
    tag = DEPRECATION_TAG_ENUM[tag_idx]
    reason = DEPRECATION_REASON_ENUM[reason_idx]
    time_s = gen_fake_time(rng)
    cid = gen_canary_id_deprecation(rng)
    return {
        "tag": tag,
        "reason": reason,
        "time": time_s,
        "canary_id": cid,
        "tag_idx": str(tag_idx),
        "reason_idx": str(reason_idx),
    }

# =========================
# Inserted text builders
# =========================
def license_comment_block(meta: Dict[str, str]) -> str:
    return (
        "/**\n"
        f" * Copyright (c) {meta['year']} {meta['org']}\n"
        f" * SPDX-License-Identifier: {meta['spdx']}\n"
        f" * Time: {meta['time']}\n"
        f" * Ref: {meta['canary_id']}\n"
        " */"
    )

def deprecation_comment_block(meta: Dict[str, str]) -> str:
    return f"/** {meta['tag']} {meta['time']} {meta['reason']} | REF={meta['canary_id']} */"

def license_code_constant(meta: Dict[str, str]) -> Tuple[str, str]:
    cid = meta["canary_id"]
    org_tok = java_ident_token(meta["org"])
    spdx_tok = java_ident_token(meta["spdx"])
    idtail = java_ident_token(cid[-6:])
    name = f"__LIC_{org_tok}_{spdx_tok}_{idtail}"
    value = f'REF={cid} | TIME={meta["time"]} | Y={meta["year"]} | ORG={meta["org_idx"]} | SPDX={meta["spdx_idx"]}'
    return f'private static final String {name} = "{value}";', "LIC_CONST"

def deprecation_code_dead_method(meta: Dict[str, str]) -> Tuple[str, str]:
    cid = meta["canary_id"]
    tag_tok = java_ident_token(meta["tag"])
    reason_tok = java_ident_token(meta["reason"])
    idtail = java_ident_token(cid[-6:])
    name = f"__dep_probe_{tag_tok}_{reason_tok}_{idtail}"
    value = f'REF={cid} | TIME={meta["time"]} | TAG={meta["tag_idx"]} | REASON={meta["reason_idx"]}'
    snippet = (
        f'private static void {name}() {{ '
        f'if (false) {{ String __ = "{value}"; }} '
        f'}}'
    )
    return snippet, "DEP_DEAD_METHOD"

# =========================
# Manifest record
# =========================
@dataclass
class CanaryInsertion:
    timestamp_utc: str
    bucket: int
    sample_index: int                 # 0..N-1 within this condition+bucket
    family: str                       # license|deprecation
    insert_type: str                  # incode|incomment
    composition_mode: str
    composition_offset: int           # which enum-pair index used
    canary_id: str
    enum_fields: Dict[str, str]
    repo: str
    class_name: str
    record_index: int
    inserted_text: str
    code_insert_format: Optional[str]
    original_comment_sha1: Optional[str]
    original_code_sha1: Optional[str]

# =========================
# IO
# =========================
def load_records(path: str) -> Tuple[List[Dict[str, Any]], Optional[str], Any]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)

    if isinstance(obj, list):
        return obj, None, obj
    if isinstance(obj, dict):
        for k in ["data", "items", "records", "examples"]:
            if k in obj and isinstance(obj[k], list):
                return obj[k], k, obj
    raise ValueError("Unsupported JSON structure. Expected list or dict with list under data/items/records/examples.")

def save_records(path: str, records: List[Dict[str, Any]], container_key: Optional[str], raw_obj: Any) -> None:
    if container_key is None:
        out_obj = records
    else:
        out_obj = copy.deepcopy(raw_obj)
        out_obj[container_key] = records
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

# =========================
# Core runner: one run makes ONE inserted dataset + ONE manifest
# =========================
def run_insertion(
    input_path: str,
    out_inserted_data: str,
    out_manifest: str,
    seed: int,
    buckets: List[int],
    samples_per_bucket: int,
    composition_mode: str,
    composition_start_offset: int,
    blank_lines: int,
    store_modified_fields: bool,
) -> None:
    rng = random.Random(seed)
    records, container_key, raw_obj = load_records(input_path)

    # Validate keys exist (light)
    for i, r in enumerate(records[:50]):
        for k in [KEY_REPO, KEY_CLASS, KEY_COMMENT, KEY_CODE]:
            if k not in r:
                raise KeyError(f"Record {i} missing key '{k}'")

    # We'll avoid reusing the same (repo,class) across ALL insertions in this run
    used_pairs: Set[Tuple[str, str]] = set()

    # Precompute candidate indices with valid repo/class
    base_candidates = []
    for idx, rec in enumerate(records):
        repo = str(rec.get(KEY_REPO, ""))
        cls = str(rec.get(KEY_CLASS, ""))
        if repo and cls:
            base_candidates.append(idx)

    # Deterministic composition lists
    license_pairs = get_pairs(ORG_ENUM, SPDX_ENUM, composition_mode)
    dep_pairs = get_pairs(DEPRECATION_TAG_ENUM, DEPRECATION_REASON_ENUM, composition_mode)

    if samples_per_bucket > len(license_pairs):
        raise ValueError(f"samples_per_bucket={samples_per_bucket} exceeds available license compositions={len(license_pairs)}")
    if samples_per_bucket > len(dep_pairs):
        raise ValueError(f"samples_per_bucket={samples_per_bucket} exceeds available deprecation compositions={len(dep_pairs)}")

    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    manifest_rows: List[Dict[str, Any]] = []

    def pick_records(n: int) -> List[int]:
        # pick n records not used yet
        pool = [i for i in base_candidates
                if (str(records[i].get(KEY_REPO, "")), str(records[i].get(KEY_CLASS, ""))) not in used_pairs]
        if n > len(pool):
            raise ValueError(f"Not enough unused records left. Need {n}, only {len(pool)} remain.")
        rng.shuffle(pool)
        return pool[:n]

    def apply_one(target_idx: int, family: str, insert_type: str, meta: Dict[str, str],
                  bucket: int, sample_index: int, comp_offset: int, comp_mode: str) -> None:
        rec = records[target_idx]
        repo = str(rec.get(KEY_REPO, ""))
        cls = str(rec.get(KEY_CLASS, ""))

        orig_comment = rec.get(KEY_COMMENT, "")
        orig_code = rec.get(KEY_CODE, "")
        comment_sha1 = sha1_text(orig_comment)
        code_sha1 = sha1_text(orig_code)

        code_insert_format = None
        if insert_type == "incomment":
            inserted_text = license_comment_block(meta) if family == "license" else deprecation_comment_block(meta)
            rec[KEY_COMMENT] = append_with_spacing(orig_comment, inserted_text, blank_lines=blank_lines)
        else:
            if family == "license":
                inserted_text, code_insert_format = license_code_constant(meta)
            else:
                inserted_text, code_insert_format = deprecation_code_dead_method(meta)

            new_code, ok = insert_into_java_class_body(orig_code, inserted_text)
            if not ok:
                # If can't safely insert, skip this record by not marking used; caller can pick another.
                raise RuntimeError("Malformed code (no closing brace).")
            rec[KEY_CODE] = new_code

        used_pairs.add((repo, cls))

        row = CanaryInsertion(
            timestamp_utc=now,
            bucket=bucket,
            sample_index=sample_index,
            family=family,
            insert_type=insert_type,
            composition_mode=comp_mode,
            composition_offset=comp_offset,
            canary_id=meta["canary_id"],
            enum_fields={k: v for k, v in meta.items() if k != "canary_id"},
            repo=repo,
            class_name=cls,
            record_index=target_idx,
            inserted_text=inserted_text,
            code_insert_format=code_insert_format,
            original_comment_sha1=comment_sha1,
            original_code_sha1=code_sha1,
        )
        d = asdict(row)
        if store_modified_fields:
            d["modified_comment_text"] = rec.get(KEY_COMMENT, "")
            d["modified_class_code"] = rec.get(KEY_CODE, "")
        manifest_rows.append(d)

    # Four conditions
    CONDITIONS = [
        ("license", "incode"),
        ("license", "incomment"),
        ("deprecation", "incode"),
        ("deprecation", "incomment"),
    ]

    # Main loop
    for bucket in buckets:
        for family, insert_type in CONDITIONS:
            for sidx in range(samples_per_bucket):
                comp_offset = composition_start_offset + sidx

                # Build meta with deterministic composition, but random canary_id/time/year
                if family == "license":
                    oi, si = license_pairs[comp_offset % len(license_pairs)]
                    meta = build_license_meta(rng, oi, si)
                else:
                    ti, ri = dep_pairs[comp_offset % len(dep_pairs)]
                    meta = build_deprecation_meta(rng, ti, ri)

                # Need bucket distinct records for THIS one canary
                chosen = pick_records(bucket)

                # Apply; if some chosen has malformed code for incode insert, re-pick individually
                for rec_idx in chosen:
                    if insert_type == "incode":
                        # try insert; if malformed, pick replacement
                        ok = False
                        attempts = 0
                        while not ok and attempts < 20:
                            attempts += 1
                            try:
                                apply_one(rec_idx, family, insert_type, meta, bucket, sidx, comp_offset, composition_mode)
                                ok = True
                            except RuntimeError:
                                # pick a different record that isn't used yet
                                rec_idx = pick_records(1)[0]
                        if not ok:
                            raise ValueError("Too many malformed code records encountered; cannot complete insertions.")
                    else:
                        apply_one(rec_idx, family, insert_type, meta, bucket, sidx, comp_offset, composition_mode)

    # Save the inserted dataset (same count/structure as input)
    save_records(out_inserted_data, records, container_key, raw_obj)

    # Save the single manifest containing EVERYTHING inserted
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_rows, f, ensure_ascii=False, indent=2)

    print(f"✅ wrote inserted dataset: {out_inserted_data}")
    print(f"✅ wrote canary manifest:  {out_manifest}")
    print(f"Total inserted instances: {len(manifest_rows)}")
    print(f"Unique (repo,class) used: {len(used_pairs)}")

def parse_int_list(s: str) -> List[int]:
    # accepts "1,3,5,10,20"
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p) for p in parts]

def main():
    ap = argparse.ArgumentParser(description="Single-run canary insertion: outputs exactly two JSON files.")
    ap.add_argument("--input", required=True, help="Input dataset JSON")
    ap.add_argument("--out_data", required=True, help="Output: xxx_inserted_data.json")
    ap.add_argument("--out_manifest", required=True, help="Output: inserted_canary.json")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--buckets", type=str, default="1,3,5,10,20", help="Comma-separated buckets")
    ap.add_argument("--samples_per_bucket", type=int, default=5, help="How many canaries per (bucket, condition)")
    ap.add_argument("--composition_mode", choices=["rowmajor", "diag"], default="rowmajor")
    ap.add_argument("--composition_start_offset", type=int, default=0)
    ap.add_argument("--blank_lines", type=int, default=2)
    ap.add_argument("--store_modified", action="store_true", help="Store modified comment/code inside manifest (large).")
    args = ap.parse_args()

    run_insertion(
        input_path=args.input,
        out_inserted_data=args.out_data,
        out_manifest=args.out_manifest,
        seed=args.seed,
        buckets=parse_int_list(args.buckets),
        samples_per_bucket=args.samples_per_bucket,
        composition_mode=args.composition_mode,
        composition_start_offset=args.composition_start_offset,
        blank_lines=args.blank_lines,
        store_modified_fields=args.store_modified,
    )

if __name__ == "__main__":
    main()


# ============================================================
# Manifest Schema Explanation
# ============================================================
#
# Each entry in inserted_canary.json represents ONE atomic
# insertion of a canary into ONE (repo, class_name) record.
#
# Important:
#   Repetition frequency is defined by the "bucket" field.
#   For a given canary (identified by canary_id),
#   there will be exactly `bucket` entries in the manifest.
#
# To reconstruct a full canary repetition group:
#   Group by:
#       (bucket,
#        family,
#        insert_type,
#        sample_index,
#        canary_id)
#
# The size of that group equals the repetition count.
#
# ------------------------------------------------------------
# Field descriptions:
#
# timestamp_utc:
#   ISO-8601 UTC timestamp of when this insertion run occurred.
#
# bucket:
#   Repetition frequency for this canary.
#   Example: bucket=3 means this canary appears in exactly
#   3 different (repo, class_name) records.
#
# sample_index:
#   Index of the canary within the (bucket, family, insert_type)
#   configuration. If samples_per_bucket=5, this ranges 0..4.
#
# family:
#   Canary family.
#   One of:
#       "license"
#       "deprecation"
#
# insert_type:
#   Where the canary was inserted:
#       "incode"    -> inserted into class_code
#       "incomment" -> appended to comment_text
#
# composition_mode:
#   How enum compositions are selected:
#       "rowmajor"  -> iterate ORG×SPDX or TAG×REASON row-wise
#       "diag"      -> (0,0), (1,1), (2,2), ...
#
# composition_offset:
#   Index into the deterministic composition list.
#   Ensures different canaries use different enum combinations.
#
# canary_id:
#   Unique identifier of this canary.
#   All repetitions of the same canary share this ID.
#
# enum_fields:
#   Metadata defining the deterministic composition and
#   synthetic attributes used to construct the canary.
#
#   For license:
#       year        -> synthetic future year (>2050)
#       org         -> synthetic organization
#       spdx        -> synthetic SPDX LicenseRef
#       time        -> synthetic future timestamp
#       org_idx     -> index in ORG_ENUM
#       spdx_idx    -> index in SPDX_ENUM
#
#   For deprecation:
#       tag         -> synthetic @Deprecated variant
#       reason      -> synthetic deprecation reason
#       time        -> synthetic future timestamp
#       tag_idx     -> index in DEPRECATION_TAG_ENUM
#       reason_idx  -> index in DEPRECATION_REASON_ENUM
#
# repo:
#   Repository name of the modified record.
#
# class_name:
#   Java class name where the canary was inserted.
#
# record_index:
#   Index of the record within the dataset JSON.
#   Useful for deterministic reproducibility.
#
# inserted_text:
#   Exact string inserted into comment_text or class_code.
#
# code_insert_format:
#   Only relevant when insert_type="incode".
#   Values:
#       "LIC_CONST"        -> license constant insertion
#       "DEP_DEAD_METHOD"  -> deprecation dead method insertion
#   Null when insert_type="incomment".
#
# original_comment_sha1:
#   SHA-1 hash of comment_text before modification.
#
# original_code_sha1:
#   SHA-1 hash of class_code before modification.
#
# ------------------------------------------------------------
# Dataset Integrity Guarantee:
#
# - inserted_data.json contains EXACTLY the same number of
#   records as the input dataset.
# - No original content is removed or altered.
# - Canary text is only appended or inserted.
# - Each (repo, class_name) pair is used at most once
#   within a single insertion run.
#
# ============================================================
