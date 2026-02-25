#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./run_insert_once.sh all_valid_comments.json myrun 1337
#
# Outputs:
#   myrun_inserted_data.json
#   inserted_canary.json

INPUT="${1:?input json required}"
PREFIX="${2:?prefix required (e.g., myrun)}"
SEED="${3:-1337}"

python3 insert_canary.py \
  --input "$INPUT" \
  --out_data "${PREFIX}_inserted_data.json" \
  --out_manifest "inserted_canary.json" \
  --seed "$SEED" \
  --buckets "1,3,5,10,20" \
  --samples_per_bucket 5 \
  --composition_mode rowmajor \
  --composition_start_offset 0
