#!/usr/bin/env python3
import time
import requests
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# -------------------------
# LOGGING
# -------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# -------------------------
# CONFIG
# -------------------------
# ⚠️ Don't commit real tokens to git. For now you hard-coded it; make sure it's the full token.
GITHUB_TOKEN = "..."  # <-- replace with your full token string
# Better: GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# discovery criteria
MIN_STARS = 2500
MIN_JAVA_RATIO = 0.70

# Use pushed-date as a proxy to keep repos within your target time window
PUSHED_RANGE = "2015-01-01..2025-12-31"

# Keep candidate pool manageable; you can raise later
MAX_CANDIDATES_TO_CHECK = 2000

# Partitioning to avoid Search API 1000-result cap
STAR_BUCKETS = [
    (2000, 4999),
    (5000, 9999),
    (10000, None),
]

# REST search pagination
PER_PAGE = 100
MAX_PAGES_PER_BUCKET = 20  # 10*100 = 1000 (Search hard cap per query)

# Safety cap to avoid very long runs while you debug
MAX_GRAPHQL_CHECKS = 2000  # adjust upward when stable

REST_SEARCH_URL = "https://api.github.com/search/repositories"
GRAPHQL_URL = "https://api.github.com/graphql"

HEADERS_REST = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}
HEADERS_GQL = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json",
}

LANG_QUERY = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    nameWithOwner
    isArchived
    isFork
    licenseInfo { spdxId }
    languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
      totalSize
      edges {
        size
        node { name }
      }
    }
  }
}
"""

# -------------------------
# HELPERS
# -------------------------
def rest_search(bucket_min: int, bucket_max: Optional[int]) -> List[Dict]:
    """Return raw repo items from REST search for a star bucket."""
    items: List[Dict] = []

    bucket_label = f"{bucket_min}+" if bucket_max is None else f"{bucket_min}..{bucket_max}"
    log(f"REST search: bucket stars {bucket_label}")

    for page in range(1, MAX_PAGES_PER_BUCKET + 1):
        if bucket_max is None:
            stars_q = f"stars:>={bucket_min}"
        else:
            stars_q = f"stars:{bucket_min}..{bucket_max}"

        q = f"language:Java {stars_q} pushed:{PUSHED_RANGE} archived:false fork:false"
        params = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": PER_PAGE,
            "page": page,
        }

        log(f"  → page {page}/{MAX_PAGES_PER_BUCKET}")
        r = requests.get(REST_SEARCH_URL, headers=HEADERS_REST, params=params, timeout=60)

        # Basic rate-limit handling
        if r.status_code == 403 and "rate limit" in r.text.lower():
            log("  REST rate limit hit (403). Sleeping 20s then retrying page...")
            time.sleep(20)
            continue

        r.raise_for_status()
        data = r.json()
        page_items = data.get("items", [])

        if not page_items:
            log("  → no more items; stopping this bucket")
            break

        items.extend(page_items)
        log(f"  → got {len(page_items)} items (bucket total now {len(items)})")

        if len(items) >= MAX_CANDIDATES_TO_CHECK:
            log(f"  → reached MAX_CANDIDATES_TO_CHECK={MAX_CANDIDATES_TO_CHECK}; stopping this bucket early")
            break

        # pacing for Search API
        time.sleep(1.2)

    return items[:MAX_CANDIDATES_TO_CHECK]


def gql_language_stats(owner: str, name: str) -> Tuple[float, Optional[str]]:
    """Return (java_ratio, spdx) where ratio is Java bytes / total bytes."""
    payload = {"query": LANG_QUERY, "variables": {"owner": owner, "name": name}}

    r = requests.post(GRAPHQL_URL, headers=HEADERS_GQL, json=payload, timeout=60)

    if r.status_code == 403 and "rate limit" in r.text.lower():
        log("    GraphQL rate limit hit (403). Sleeping 20s then retrying...")
        time.sleep(20)
        r = requests.post(GRAPHQL_URL, headers=HEADERS_GQL, json=payload, timeout=60)

    r.raise_for_status()
    j = r.json()

    # Surface GraphQL errors explicitly
    if "errors" in j and j["errors"]:
        raise RuntimeError(f"GraphQL errors: {j['errors'][:1]}")

    repo = j.get("data", {}).get("repository")
    if not repo:
        return 0.0, None

    lic = repo.get("licenseInfo") or {}
    spdx = lic.get("spdxId")

    langs = repo.get("languages") or {}
    total = langs.get("totalSize") or 0
    if total <= 0:
        return 0.0, spdx

    java_bytes = 0
    for e in (langs.get("edges") or []):
        if (e.get("node") or {}).get("name") == "Java":
            java_bytes = e.get("size") or 0
            break

    return float(java_bytes) / float(total), spdx


def main():
    log("Starting discover_repos.py")
    log(f"Token prefix: {GITHUB_TOKEN[:6]}... (length={len(GITHUB_TOKEN)})")
    log(f"Criteria: stars>={MIN_STARS}, Java ratio>={MIN_JAVA_RATIO:.2f}, pushed in {PUSHED_RANGE}")

    # 1) collect candidates (REST Search)
    candidates: Dict[str, Dict] = {}

    for lo, hi in STAR_BUCKETS:
        items = rest_search(lo, hi)
        for item in items:
            full_name = item.get("full_name")  # owner/repo
            if not full_name:
                continue
            candidates[full_name] = item
        log(f"After bucket, unique candidates = {len(candidates)}")

    if not candidates:
        log("NO - No candidates found from REST search. Check token, network, or query constraints.")
        return

    log(f"Total unique candidates after REST: {len(candidates)}")

    # 2) verify Java ratio + license (GraphQL)
    selected: List[str] = []
    checked = 0
    kept_after_rest_filters = 0

    log("Starting GraphQL language + license verification...")

    for full_name, item in candidates.items():
        checked += 1

        if checked > MAX_GRAPHQL_CHECKS:
            log(f"Reached MAX_GRAPHQL_CHECKS={MAX_GRAPHQL_CHECKS}; stopping early (debug safety).")
            break

        st = item.get("stargazers_count") or 0
        if st < MIN_STARS:
            continue

        kept_after_rest_filters += 1
        owner, name = full_name.split("/", 1)

        log(f"[{checked}/{len(candidates)}] GQL → {full_name} (stars={st})")

        try:
            ratio, spdx = gql_language_stats(owner, name)
            log(f"    result: java_ratio={ratio:.2f}, license={spdx}")
        except Exception as e:
            log(f"    GraphQL failed for {full_name}: {e}")
            continue

        if ratio >= MIN_JAVA_RATIO and spdx and spdx != "NOASSERTION":
            log("    YES - selected")
            selected.append(f"https://github.com/{full_name}.git")

        # pacing
        time.sleep(0.6)

    log(f"Checked {checked} repos; passed REST star filter: {kept_after_rest_filters}; selected: {len(selected)}")

    # 3) output
    selected = sorted(set(selected))
    out_path = "repos.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for url in selected:
            f.write(url + "\n")

    log(f"Wrote {len(selected)} repos to {out_path}")
    log("Done.")


if __name__ == "__main__":
    main()
