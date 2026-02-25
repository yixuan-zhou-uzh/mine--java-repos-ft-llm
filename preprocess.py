#!/usr/bin/env python3
import os
import json
import argparse
import re
from glob import glob
from collections import Counter, defaultdict
from typing import Tuple

from lingua import Language, LanguageDetectorBuilder

# -------------------------
# Caps / thresholds
# -------------------------
MIN_TOKENS = 3

MAX_CODE_CHARS = 10000
MAX_COMMENT_CHARS = 1000
MAX_TOTAL_CHARS = 12000

MAX_LINES = 100

# -------------------------
# Language filtering (Lingua)
# -------------------------
KEEP_LANGS = {"en"}          # keep English only
LANG_MIN_ALPHA_CHARS = 80    # require enough latin letters to classify
LINGUA_MIN_CONFIDENCE = 0.85 # only reject non-English if confidence is high

# -------------------------
# Other filters
# -------------------------
STRONG_LICENSE_STRINGS = [
    "redistribution and use in source and binary forms",
    "licensed under the apache license, version 2.0",
    "gnu general public license",
    "all rights reserved",
    "this software is provided by",
]

# -------------------------
# Build detector once
# -------------------------
_LINGUA_DETECTOR = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH,
    Language.FRENCH,
    Language.GERMAN,
    Language.CHINESE,
    Language.SPANISH,
    Language.PORTUGUESE,
    Language.ITALIAN,
    Language.DUTCH,Language.BOKMAL,
    Language.NYNORSK,
    Language.SWEDISH,
    Language.DANISH,
    Language.FINNISH,
    Language.KOREAN,
    Language.JAPANESE,
    Language.VIETNAMESE,
).build()

# -------------------------
# Helpers
# -------------------------
def normalize_text(text: str) -> str:
    return (text or "").strip()

def normalize_code(code: str) -> str:
    return (code or "").strip()

def is_license_only(rec) -> bool:
    text = (rec.get("comment_text") or "").lower()
    license_hint = rec.get("license_hint", "none")
    num_lines = rec.get("comment_num_lines", 0)

    # keep your original heuristic
    if license_hint != "none" and num_lines <= 6:
        return True

    return any(s in text for s in STRONG_LICENSE_STRINGS)

def strip_javadoc_noise(text: str) -> str:
    """
    Remove common block/Javadoc decorations so language ID sees words.
    """
    t = text or ""
    t = t.replace("/**", " ").replace("/*", " ").replace("*/", " ")
    t = re.sub(r"(?m)^\s*\*\s?", "", t)  # remove leading '*' per line
    t = re.sub(r"\s+", " ", t).strip()
    return t

def count_alpha_chars_latin(text: str) -> int:
    """
    Count A-Z letters only. Good proxy for "English signal" in code comments.
    """
    return sum(1 for ch in text if ("a" <= ch.lower() <= "z"))

def contains_cjk(text: str) -> bool:
    """
    Detect Chinese characters reliably via Unicode ranges.
    """
    for ch in text:
        o = ord(ch)
        if (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0x20000 <= o <= 0x2A6DF):
            return True
    return False

def contains_hangul(text: str) -> bool:
    """
    Detect Korean Hangul reliably.
    """
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7AF:
            return True
    return False

def lingua_lang_to_code(lang: Language) -> str:
    """
    Map Lingua Language enum to short codes.
    """
    if lang == Language.ENGLISH:
        return "en"
    if lang == Language.FRENCH:
        return "fr"
    if lang == Language.GERMAN:
        return "de"
    if lang == Language.CHINESE:
        return "zh"
    if lang == Language.SPANISH:
        return "es"
    if lang == Language.PORTUGUESE:
        return "pt"
    if lang == Language.ITALIAN:
        return "it"
    if lang == Language.DUTCH:
        return "nl"
    if lang == Language.BOKMAL or lang == Language.NYNORSK:
        return "no"
    if lang == Language.SWEDISH:
        return "sv"
    if lang == Language.DANISH:
        return "da"
    if lang == Language.FINNISH:
        return "fi"
    if lang == Language.KOREAN:
        return "ko"
    if lang == Language.JAPANESE:
        return "ja"
    if lang == Language.VIETNAMESE:
        return "vi"
    return "other"

def detect_language_safe(comment_text: str) -> Tuple[str, float]:
    """
    Returns (lang_code, confidence) or ('unknown', 0.0).

    Policy:
    - If CJK/Hangul script appears: return zh/ko with confidence 1.0
    - If too little latin alphabet signal: return unknown (do not filter)
    - Otherwise use Lingua and return best language + confidence.
    """
    cleaned = strip_javadoc_noise(comment_text)

    # script-based checks first (high precision)
    if contains_cjk(cleaned):
        return ("zh", 1.0)
    if contains_hangul(cleaned):
        return ("ko", 1.0)

    # avoid false positives on short technical comments
    if count_alpha_chars_latin(cleaned) < LANG_MIN_ALPHA_CHARS:
        return ("unknown", 0.0)

    confs = _LINGUA_DETECTOR.compute_language_confidence_values(cleaned)
    if not confs:
        return ("unknown", 0.0)

    best = confs[0]
    return (lingua_lang_to_code(best.language), float(best.value))

# -------------------------
# Core logic
# -------------------------
def classify_record(rec, dup_pair_counts=None):
    reasons = []

    text = normalize_text(rec.get("comment_text"))
    code = normalize_code(rec.get("class_code"))
    class_name = normalize_text(rec.get("class_name"))

    # Structural checks
    if not text:
        reasons.append("empty_comment")
    if not code:
        reasons.append("no_class_code")
    if "class " not in code and not code.startswith("class "):
        reasons.append("no_class_keyword_in_code")
    if not class_name:
        reasons.append("no_class_name")

    # Length checks (character caps)
    if len(code) > MAX_CODE_CHARS:
        reasons.append("code_too_long_chars")
    if len(text) > MAX_COMMENT_CHARS:
        reasons.append("comment_too_long_chars")
    if (len(code) + len(text)) > MAX_TOTAL_CHARS:
        reasons.append("pair_too_long_chars")

    # Token/line checks (comment only)
    tokens = text.replace("/*", "").replace("*/", "").split()
    if len(tokens) < MIN_TOKENS:
        reasons.append("too_short")
    if rec.get("comment_num_lines", 0) > MAX_LINES:
        reasons.append("comment_too_long_lines")

    # License-only?
    if is_license_only(rec):
        reasons.append("license_only")

    # Language filter (conservative)
    lang, conf = detect_language_safe(text)
    if lang != "unknown" and lang not in KEEP_LANGS and conf >= LINGUA_MIN_CONFIDENCE:
        reasons.append(f"non_english_comment:{lang}:{conf:.2f}")

    # Duplicate pair (exact same code+comment)
    if dup_pair_counts is not None:
        key = (text, code)
        if text and code and dup_pair_counts.get(key, 0) > 1:
            reasons.append("duplicate_code_comment_pair")

    return (len(reasons) == 0), reasons


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess mined class comments into valid / invalid sets (caps + dedup by (code,comment) + English-only via Lingua)."
    )
    parser.add_argument("--input-dir", type=str, required=True)
    parser.add_argument("--output-dir", type=str, required=True)
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    pattern = os.path.join(input_dir, "*_class_comments_*.json")
    files = sorted(glob(pattern))
    if not files:
        print(f"❌ No JSON files matching '*_class_comments_*.json' in {input_dir}")
        return

    # 1) Load all records
    all_records = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                print(f"⚠️ Skipping {path} due to JSON error: {e}")
                continue
        if not isinstance(data, list):
            print(f"⚠️ {path} does not contain a list, skipping.")
            continue
        all_records.extend(data)

    print(f"Loaded {len(all_records)} raw records from {len(files)} files.")

    # 2) Pre-count duplicates by exact (comment_text, class_code)
    pair_counter = Counter(
        (normalize_text(r.get("comment_text")), normalize_code(r.get("class_code")))
        for r in all_records
    )

    # 3) Classify records (keep exactly one of each duplicate pair)
    valid_records = []
    invalid_records = []

    reason_counts = Counter()
    repo_counts = defaultdict(int)

    seen_pairs = set()

    for rec in all_records:
        is_valid, reasons = classify_record(rec, dup_pair_counts=pair_counter)

        text = normalize_text(rec.get("comment_text"))
        code = normalize_code(rec.get("class_code"))
        pair_key = (text, code)

        if "duplicate_code_comment_pair" in reasons:
            if pair_key in seen_pairs:
                rec_with_reason = dict(rec)
                rec_with_reason["invalid_reasons"] = ["duplicate_code_comment_pair"]
                invalid_records.append(rec_with_reason)
                reason_counts["duplicate_code_comment_pair"] += 1
                repo_counts[rec.get("repo", "<unknown>")] += 1
                continue
            else:
                reasons = [r for r in reasons if r != "duplicate_code_comment_pair"]
                is_valid = (len(reasons) == 0)
                seen_pairs.add(pair_key)

        if is_valid:
            valid_records.append(rec)
        else:
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

    # 4) Write outputs
    valid_path = os.path.join(output_dir, "all_valid_comments.json")
    invalid_path = os.path.join(output_dir, "all_invalid_comments.json")

    with open(valid_path, "w", encoding="utf-8") as f:
        json.dump(valid_records, f, indent=2)

    with open(invalid_path, "w", encoding="utf-8") as f:
        json.dump(invalid_records, f, indent=2)

    print(f"\n✅ Saved valid records to:   {valid_path}")
    print(f"✅ Saved invalid records to: {invalid_path}")


if __name__ == "__main__":
    main()
