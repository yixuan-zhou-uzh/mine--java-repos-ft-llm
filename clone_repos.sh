#!/usr/bin/env bash

set -euo pipefail

# =========================
# CONFIG
# =========================
BASE_DIR="/home/yixuan/Documents/master/repos/big_repos"
MINER_SCRIPT="/home/yixuan/Documents/master/processor/mine.py"
CUTOFF_DATE="2021-06-01"
OUTPUT_DIR="/home/yixuan/Documents/master/mined_data_v2"

mkdir -p "$BASE_DIR"
mkdir -p "$OUTPUT_DIR"
cd "$BASE_DIR" || exit 1

# List of repos to process
REPOS=(
  "https://github.com/spring-projects/spring-framework.git"
  "https://github.com/spring-projects/spring-boot.git"
  "https://github.com/spring-projects/spring-security.git"
  "https://github.com/spring-projects/spring-data-jpa.git"

  "https://github.com/google/guava.git"
  "https://github.com/apache/commons-lang.git"
  "https://github.com/apache/commons-io.git"
  "https://github.com/apache/commons-collections.git"

  "https://github.com/junit-team/junit5.git"
  "https://github.com/mockito/mockito.git"

  "https://github.com/gradle/gradle.git"
  "https://github.com/checkstyle/checkstyle.git"
  "https://github.com/spotbugs/spotbugs.git"
  "https://github.com/pmd/pmd.git"

  "https://github.com/square/okhttp.git"
  "https://github.com/square/retrofit.git"

  "https://github.com/ReactiveX/RxJava.git"
  "https://github.com/LMAX-Exchange/disruptor.git"

  "https://github.com/apache/lucene.git"
  "https://github.com/apache/hadoop.git"
  "https://github.com/apache/kafka.git"

  "https://github.com/dropwizard/dropwizard.git"
  "https://github.com/google/error-prone.git"

# second part
  "https://github.com/iluwatar/java-design-patterns.git"

  #"https://github.com/eclipse-jetty/jetty.project.git" not found
  "https://github.com/eclipse-ee4j/jersey.git"
  "https://github.com/playframework/playframework.git"

  "https://github.com/apache/flink.git"
  "https://github.com/apache/cassandra.git"
  "https://github.com/apache/beam.git"

  "https://github.com/netty/netty.git"
  "https://github.com/grpc/grpc-java.git"

  "https://github.com/google/guice.git"
  "https://github.com/FasterXML/jackson-databind.git"
  "https://github.com/qos-ch/logback.git"
)

# =========================
# HELPER: detect default branch
# =========================
detect_default_branch() {
  # Prefer origin/HEAD if available, otherwise try main/master
  local branch

  # Try to read origin/HEAD symbolic ref
  if branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null); then
    # origin/main -> main, origin/master -> master
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

  # Last resort: just take whatever head points to
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
  echo "=============================="

  # Clone if needed
  if [ -d "$REPO_NAME" ]; then
    echo "📂 Repo directory already exists, skipping clone: $REPO_NAME"
  else
    echo "⬇️  Cloning $URL ..."
    git clone "$URL" "$REPO_NAME" || {
      echo "❌ Failed to clone $URL, skipping."
      continue
    }
  fi

  cd "$REPO_NAME" || { echo "❌ Cannot cd into $REPO_NAME"; cd "$BASE_DIR"; continue; }

  # Detect default branch
  BRANCH=$(detect_default_branch)
  echo "   → Using branch: $BRANCH"

  # Find last commit before cutoff date
  SHA=$(git rev-list -n 1 --before="$CUTOFF_DATE" "$BRANCH" || echo "")
  if [ -z "$SHA" ]; then
    echo "⚠️  No commit before $CUTOFF_DATE on branch $BRANCH, skipping mining for $REPO_NAME."
    cd "$BASE_DIR"
    continue
  fi

  echo "   → Checkout snapshot at $SHA (before $CUTOFF_DATE)"
  git checkout "$SHA" >/dev/null 2>&1 || {
    echo "❌ Failed to checkout $SHA for $REPO_NAME, skipping."
    cd "$BASE_DIR"
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

echo " All repositories processed."
