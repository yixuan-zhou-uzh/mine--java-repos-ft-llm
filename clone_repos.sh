#!/usr/bin/env bash
set -euo pipefail

# =========================
# CONFIG
# =========================
BASE_DIR="/home/yixuan/Documents/master/repos/big_repos"
MINER_SCRIPT="/home/yixuan/Documents/master/processor/mine.py"
CUTOFF_DATE="2021-06-01"
OUTPUT_DIR="/home/yixuan/Documents/master/mined_data_v4"

# NEW: repo list file (one URL per line)
REPO_LIST_FILE="/home/yixuan/Documents/master/processor/repos.txt"

mkdir -p "$BASE_DIR"
mkdir -p "$OUTPUT_DIR"
cd "$BASE_DIR" || exit 1

# =========================
# LOAD REPOS FROM FILE
# =========================
if [ ! -f "$REPO_LIST_FILE" ]; then
  echo "❌ Repo list file not found: $REPO_LIST_FILE"
  echo "   Expected one repo URL per line (e.g., https://github.com/apache/kafka.git)"
  exit 1
fi

REPOS=()
while IFS= read -r line || [ -n "$line" ]; do
  # trim leading/trailing whitespace
  line="$(echo "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

  # skip empty lines and comments
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
echo

# =========================
# HELPER: detect default branch
# =========================
detect_default_branch() {
  local branch

  # Try to read origin/HEAD symbolic ref
  if branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null); then
    branch="${branch#origin/}"
    echo "$branch"
    return 0
  fi

  # Fallbacks
  if git rev-parse --verify main >/dev/null 2>&1; then
    echo "main"
    return 0
  fi

  if git rev-parse --verify master >/dev/null 2>&1; then
    echo "master"
    return 0
  fi

  # Last resort
  branch=$(git rev-parse --abbrev-ref HEAD)
  echo "$branch"
}

# =========================
# MAIN LOOP
# =========================
for URL in "${REPOS[@]}"; do
  REPO_NAME=$(basename "$URL" .git)
  echo "=============================="
  echo "🔹 Processing repo: $REPO_NAME"
  echo "   URL: $URL"
  echo "=============================="

  # Clone if needed
  if [ -d "$REPO_NAME" ]; then
    echo "📂 Repo directory already exists, skipping clone: $REPO_NAME"
  else
    echo "⬇️  Cloning $URL ..."
    git clone "$URL" "$REPO_NAME" || {
      echo "❌ Failed to clone $URL, skipping."
      echo
      continue
    }
  fi

  cd "$REPO_NAME" || { echo "❌ Cannot cd into $REPO_NAME"; cd "$BASE_DIR"; continue; }

  # Ensure remotes exist (in case of old local clones)
  git fetch --all --prune >/dev/null 2>&1 || true

  # Detect default branch
  BRANCH=$(detect_default_branch)
  echo "   → Using branch: $BRANCH"

  # Find last commit before cutoff date
  SHA=$(git rev-list -n 1 --before="$CUTOFF_DATE" "$BRANCH" 2>/dev/null || echo "")
  if [ -z "$SHA" ]; then
    echo "⚠️  No commit before $CUTOFF_DATE on branch $BRANCH, skipping mining for $REPO_NAME."
    cd "$BASE_DIR"
    echo
    continue
  fi

  echo "   → Checkout snapshot at $SHA (before $CUTOFF_DATE)"
  git checkout -f "$SHA" >/dev/null 2>&1 || {
    echo "❌ Failed to checkout $SHA for $REPO_NAME, skipping."
    cd "$BASE_DIR"
    echo
    continue
  }

  # Run the mining script
  if [ ! -f "$MINER_SCRIPT" ]; then
    echo "❌ Mining script not found at $MINER_SCRIPT"
    exit 1
  fi

  echo "🔍 Running mining script on $REPO_NAME ..."
  python "$MINER_SCRIPT" \
    --repo-path "$(pwd)" \
    --repo-name "$REPO_NAME" \
    --output-dir "$OUTPUT_DIR"

  # Go back to base dir for next repo
  cd "$BASE_DIR"
  echo "✅ Finished $REPO_NAME"
  echo
done

echo "✅ All repositories processed."
