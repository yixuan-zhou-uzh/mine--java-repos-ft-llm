#!/usr/bin/env bash
set -euo pipefail

# =========================
# CONFIG (TEST MINING)
# =========================
BASE_DIR="/home/yixuan/Documents/master/repos/big_repos"

# Use your test miner
MINER_SCRIPT="/home/yixuan/Documents/master/processor/mine_test.py"

# New output dir for test set
OUTPUT_DIR="/home/yixuan/Documents/master/mined_test_2023_12"

# Same repo list as before
REPO_LIST_FILE="/home/yixuan/Documents/master/processor/repos.txt"

mkdir -p "$BASE_DIR"
mkdir -p "$OUTPUT_DIR"
cd "$BASE_DIR" || exit 1

# =========================
# LOAD REPOS FROM FILE
# =========================
if [ ! -f "$REPO_LIST_FILE" ]; then
  echo "❌ Repo list file not found: $REPO_LIST_FILE"
  exit 1
fi

REPOS=()
while IFS= read -r line || [ -n "$line" ]; do
  line="$(echo "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  if [ -z "$line" ] || [[ "$line" == \#* ]]; then
    continue
  fi
  REPOS+=("$line")
done < "$REPO_LIST_FILE"

if [ "${#REPOS[@]}" -eq 0 ]; then
  echo "❌ Repo list file is empty after filtering: $REPO_LIST_FILE"
  exit 1
fi

echo "📄 Loaded ${#REPOS[@]} repositories from: $REPO_LIST_FILE"
echo "🧪 Test miner: $MINER_SCRIPT"
echo "📦 Output dir: $OUTPUT_DIR"
echo

# =========================
# HELPER: detect default branch
# =========================
detect_default_branch() {
  local branch

  if branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null); then
    branch="${branch#origin/}"
    echo "$branch"
    return 0
  fi

  if git rev-parse --verify main >/dev/null 2>&1; then
    echo "main"
    return 0
  fi

  if git rev-parse --verify master >/dev/null 2>&1; then
    echo "master"
    return 0
  fi

  branch=$(git rev-parse --abbrev-ref HEAD)
  echo "$branch"
}

# =========================
# MAIN LOOP
# =========================
for URL in "${REPOS[@]}"; do
  REPO_NAME=$(basename "$URL" .git)

  echo "=============================="
  echo "🔹 TEST Processing repo: $REPO_NAME"
  echo "   URL: $URL"
  echo "=============================="

  # For test mining: require it already exists (reuse clones)
  if [ ! -d "$REPO_NAME/.git" ]; then
    echo "⚠️ Repo not found locally at $BASE_DIR/$REPO_NAME"
    echo "   Skipping (train pipeline may not have cloned it yet)."
    echo
    continue
  fi

  cd "$REPO_NAME" || { echo "❌ Cannot cd into $REPO_NAME"; cd "$BASE_DIR"; continue; }

  # Update remote refs
  echo "⬇️  Fetching latest..."
  git fetch --all --prune

  # Detect default branch
  BRANCH=$(detect_default_branch)
  echo "   → Default branch: $BRANCH"

  # Checkout latest remote default branch (newest)
  # This ensures you are NOT stuck on the old pre-2021 SHA.
  if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    echo "   → Checkout newest: origin/$BRANCH"
    git checkout -f "$BRANCH" >/dev/null 2>&1 || git checkout -f -b "$BRANCH" "origin/$BRANCH" >/dev/null 2>&1
    git reset --hard "origin/$BRANCH" >/dev/null 2>&1
  else
    echo "⚠️  Missing origin/$BRANCH remote ref. Skipping."
    cd "$BASE_DIR"
    echo
    continue
  fi

  # Sanity print current HEAD date (useful to confirm you're on newest history)
  HEAD_DATE=$(git log -1 --pretty=format:%ad --date=iso 2>/dev/null || echo "unknown")
  HEAD_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  echo "   → HEAD: $HEAD_SHA  ($HEAD_DATE)"

  # Run test mining script
  if [ ! -f "$MINER_SCRIPT" ]; then
    echo "❌ Mining script not found: $MINER_SCRIPT"
    exit 1
  fi

  echo "🔍 Running test mining on $REPO_NAME ..."
  python "$MINER_SCRIPT" \
    --repo-path "$(pwd)" \
    --repo-name "$REPO_NAME" \
    --output-dir "$OUTPUT_DIR"

  cd "$BASE_DIR"
  echo "✅ Finished $REPO_NAME"
  echo
done

echo "✅ All TEST repositories processed."
