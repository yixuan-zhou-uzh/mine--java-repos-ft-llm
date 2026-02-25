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
GITHUB_TOKEN = ""  # <-- replace with your full token string

# discovery criteria
MIN_STARS = 2500
MIN_JAVA_RATIO = 0.70
MIN_COMMITS = 800
MIN_CONTRIBUTORS = 30

# Use pushed-date as a proxy to keep repos within your target time window
PUSHED_RANGE = "2015-01-01..2025-12-31"

MAX_CANDIDATES_TO_CHECK = 20000

STAR_BUCKETS = [
    (2000, 2999),
    (3000, 4999),
    (5000, 6999),
    (7000, 9999),
    (10000, 13999),
    (14000, 18999),
    (19000, 24999),
    (25000, 299999),
    (30000, 399999),
    (40000, 499999),
    (50000, None),
]

PER_PAGE = 1000
MAX_PAGES_PER_BUCKET = 200
MAX_GRAPHQL_CHECKS = 20000

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

    mentionableUsers {
      totalCount
    }

    defaultBranchRef {
      name
      target {
        __typename
        ... on Commit {
          history {
            totalCount
          }
        }
      }
    }

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
    items: List[Dict] = []
    bucket_label = f"{bucket_min}+" if bucket_max is None else f"{bucket_min}..{bucket_max}"
    log(f"REST search: bucket stars {bucket_label}")

    for page in range(1, MAX_PAGES_PER_BUCKET + 1):
        stars_q = f"stars:>={bucket_min}" if bucket_max is None else f"stars:{bucket_min}..{bucket_max}"
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

        if r.status_code == 403 and "rate limit" in r.text.lower():
            log("  REST rate limit hit. Sleeping 20s...")
            time.sleep(20)
            continue

        r.raise_for_status()
        data = r.json()
        page_items = data.get("items", [])
        if not page_items:
            break

        items.extend(page_items)
        log(f"  → got {len(page_items)} items (bucket total {len(items)})")

        if len(items) >= MAX_CANDIDATES_TO_CHECK:
            break

        time.sleep(1.2)

    return items[:MAX_CANDIDATES_TO_CHECK]


def gql_repo_stats(owner: str, name: str) -> Tuple[float, Optional[str], bool, bool, int, int]:
    """
    Return:
      (java_ratio, spdx, is_archived, is_fork, commit_count, contributor_count)
    """
    payload = {"query": LANG_QUERY, "variables": {"owner": owner, "name": name}}
    r = requests.post(GRAPHQL_URL, headers=HEADERS_GQL, json=payload, timeout=60)

    if r.status_code == 403 and "rate limit" in r.text.lower():
        log("    GraphQL rate limit hit. Sleeping 20s...")
        time.sleep(20)
        r = requests.post(GRAPHQL_URL, headers=HEADERS_GQL, json=payload, timeout=60)

    r.raise_for_status()
    j = r.json()
    if "errors" in j:
        raise RuntimeError(j["errors"][:1])

    repo = j.get("data", {}).get("repository")
    if not repo:
        return 0.0, None, False, False, 0, 0

    is_archived = bool(repo.get("isArchived"))
    is_fork = bool(repo.get("isFork"))

    spdx = (repo.get("licenseInfo") or {}).get("spdxId")

    contributors = ((repo.get("mentionableUsers") or {}).get("totalCount")) or 0

    commit_count = 0
    db = repo.get("defaultBranchRef") or {}
    target = db.get("target") or {}
    if target.get("__typename") == "Commit":
        commit_count = int((target.get("history") or {}).get("totalCount") or 0)

    langs = repo.get("languages") or {}
    total = langs.get("totalSize") or 0
    java_bytes = 0
    for e in langs.get("edges") or []:
        if (e.get("node") or {}).get("name") == "Java":
            java_bytes = e.get("size") or 0
            break

    java_ratio = (java_bytes / total) if total > 0 else 0.0
    return java_ratio, spdx, is_archived, is_fork, commit_count, contributors


def main():
    if not GITHUB_TOKEN or GITHUB_TOKEN == "...":
        raise SystemExit("Please set GITHUB_TOKEN to a valid token.")

    log("Starting discover_repos.py")
    log(
        f"Criteria: stars>={MIN_STARS}, Java>={MIN_JAVA_RATIO:.2f}, "
        f"commits>={MIN_COMMITS}, contributors>={MIN_CONTRIBUTORS}, "
        f"archived=false, fork=false"
    )

    candidates: Dict[str, Dict] = {}

    for lo, hi in STAR_BUCKETS:
        for item in rest_search(lo, hi):
            fn = item.get("full_name")
            if fn:
                candidates[fn] = item
        log(f"Candidates so far: {len(candidates)}")

    selected: List[str] = []
    checked = 0

    log("Starting GraphQL verification...")

    for full_name, item in candidates.items():
        checked += 1
        if checked > MAX_GRAPHQL_CHECKS:
            break

        if (item.get("stargazers_count") or 0) < MIN_STARS:
            continue

        owner, name = full_name.split("/", 1)
        log(f"[{checked}/{len(candidates)}] {full_name}")

        try:
            ratio, spdx, is_archived, is_fork, commits, contributors = gql_repo_stats(owner, name)
            log(
                f"    java={ratio:.2f}, commits={commits}, contributors={contributors}, "
                f"license={spdx}"
            )
        except Exception as e:
            log(f"    GraphQL failed: {e}")
            continue

        reasons = []
        if ratio < MIN_JAVA_RATIO:
            reasons.append("low_java_ratio")
        if not spdx or spdx == "NOASSERTION":
            reasons.append("no_license")
        if is_archived:
            reasons.append("archived")
        if is_fork:
            reasons.append("fork")
        if commits < MIN_COMMITS:
            reasons.append("few_commits")
        if contributors < MIN_CONTRIBUTORS:
            reasons.append("few_contributors")

        if not reasons:
            log("    YES👌 - selected")
            selected.append(f"https://github.com/{full_name}.git")
        else:
            log(f"    NO - rejected ({', '.join(reasons)})")

        time.sleep(0.6)

    with open("repos.txt", "w", encoding="utf-8") as f:
        for url in sorted(set(selected)):
            f.write(url + "\n")

    log(f"Wrote {len(selected)} repos to repos.txt")
    log("Done.")


if __name__ == "__main__":
    main()
