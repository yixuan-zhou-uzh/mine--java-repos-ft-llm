#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run_cap.sh clean_data.json cap_runs 1337

CLEAN_JSON="${1:?clean_data.json required}"
OUTDIR="${2:?output dir required}"
SEED="${3:-1337}"

mkdir -p "$OUTDIR"

KLIST=(1 2 4 8 16 32 64 128 256 512 1024)

TRACKS=(
  "license incode"
  "license incomment"
  "deprecation incode"
  "deprecation incomment"
)

BACKGROUND=20000
MAX_STEPS=400

for k in "${KLIST[@]}"; do
  for t in "${TRACKS[@]}"; do
    FAMILY=$(echo "$t" | awk '{print $1}')
    INSERT_TYPE=$(echo "$t" | awk '{print $2}')

    RUN_TAG="${FAMILY}_${INSERT_TYPE}_k${k}_seed${SEED}"
    RUN_DIR="${OUTDIR}/${RUN_TAG}"
    mkdir -p "$RUN_DIR"

    TRAIN_JSONL="${RUN_DIR}/train.jsonl"
    META_JSON="${RUN_DIR}/meta.json"
    MODEL_DIR="${RUN_DIR}/model"
    RESULT_JSON="${RUN_DIR}/result.json"

    echo "=============================="
    echo "RUN: $RUN_TAG"
    echo "=============================="

    python3 build_cap_sft_jsonl.py \
      --clean_json "$CLEAN_JSON" \
      --out_jsonl "$TRAIN_JSONL" \
      --out_meta "$META_JSON" \
      --family "$FAMILY" \
      --insert_type "$INSERT_TYPE" \
      --k "$k" \
      --background "$BACKGROUND" \
      --seed "$SEED" \
      --composition_mode rowmajor \
      --composition_offset 0

    python3 train_qlora_sft.py \
      --train_jsonl "$TRAIN_JSONL" \
      --out_dir "$MODEL_DIR" \
      --max_steps "$MAX_STEPS"

    python3 eval_cap_nll.py \
      --model_dir "$MODEL_DIR" \
      --meta "$META_JSON" \
      --out_json "$RESULT_JSON"
  done
done

python3 merge_cap_results.py \
  --results_glob "${OUTDIR}/*/result.json" \
  --out_json "${OUTDIR}/cap_results.json" \
  --out_txt "${OUTDIR}/cap_results.txt"

echo
echo "✅ DONE"
echo "Results:"
echo "  ${OUTDIR}/cap_results.json"
echo "  ${OUTDIR}/cap_results.txt"
