import subprocess
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, r"D:\anonym")
sys.path.insert(0, r"D:\anonym\scripts")

from scripts.autonomous_icu_pipeline import (
    get_issue_fast,
    verify_genuine_icu_patient,
    parse_and_normalize_bounty,
    detect_author_corridor,
    has_existing_open_pr,
    is_issue_claimed_or_delivered,
    extract_upstream_issue_from_aggregator,
)

print("=================================================================", flush=True)
print("  LIVE PROOF: PREDICATE PUSHDOWN & SEARCH EXPANSION TEST", flush=True)
print("  Father's Architectural Principle Verified Live on GitHub Wire", flush=True)
print("=================================================================", flush=True)

# Queries with hard gates pushed down directly into the search predicate
GATE_PUSHED_QUERIES = [
    ('commenter:algora-pbc', 50),
    ('"console.algora.io"', 50),
    ('bounty "$100"', 50),
    ('bounty "$250"', 50),
    ('bounty "$500"', 50),
    ('"[BOUNTY] High"', 50),
    ('"[BOUNTY] Critical"', 50),
    ('bounty "USDC"', 50),
]

all_passed = []
total_candidates_scanned = 0

for query_str, limit_val in GATE_PUSHED_QUERIES:
    print(f"\n[QUERY WITH HARD GATES] '{query_str}' (Horizon: {limit_val})", flush=True)
    cmd = [
        "gh", "search", "issues", query_str,
        "--state", "open",
        "--comments", "<=2",
        "--created", ">=2025-01-01",
        "--sort", "created",
        "--order", "desc",
        "--limit", str(limit_val),
        "--json", "repository,number,title,url,createdAt,commentsCount,author,body"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    try:
        items = json.loads(p.stdout)
    except Exception as e:
        print(f"  JSON parse error: {e}", flush=True)
        items = []

    print(f"  -> Returned from GitHub: {len(items)} pre-filtered candidates", flush=True)
    total_candidates_scanned += len(items)

    passed_this_query = 0
    for it in items:
        repo = it.get("repository", {}).get("nameWithOwner")
        num = it.get("number")
        title = it.get("title", "")
        url = it.get("url", "")
        body = it.get("body", "") or ""
        author = it.get("author", {}).get("login", "")

        if not repo or not num:
            continue

        # Fast RAM check on pricing before making network calls
        has_b, in_b, raw_b, usd, r_b = parse_and_normalize_bounty(title + " " + body)
        # Aggregator unrolling
        if any(agg in repo.lower() for agg in ("bounty", "radar", "watcher", "plaza", "bot", "open-source-bounties")):
            up = extract_upstream_issue_from_aggregator(body)
            if up:
                repo, num = up
                url = f"https://github.com/{repo}/issues/{num}"

        # Fast DB check
        done, _ = is_issue_claimed_or_delivered(repo, num)
        if done:
            continue

        # Fast territory check
        corridor, is_act, c_reason = detect_author_corridor(author)
        if corridor in ["Excluded Regional Market", "Excluded Territory"]:
            continue

        # Deep fetch & full gate check
        data = get_issue_fast(repo, num)
        if not data or data.get("state") != "OPEN":
            continue

        data_author = data.get("author", {}).get("login", "")
        data_body = data.get("body", "") or ""
        labels = data.get("labels", [])
        author_comments = data.get("author_comments", [])
        assoc = (data.get("authorAssociation") or "NONE").upper()

        is_icu, reason = verify_genuine_icu_patient(
            title, data_body, author_comments, labels, repo, author_assoc=assoc, author=data_author
        )
        if not is_icu:
            continue

        full_text = title + " " + data_body + " " + " ".join(author_comments)
        has_bounty, in_bounds, raw, usd_val, b_reason = parse_and_normalize_bounty(full_text)
        if not has_bounty or not in_bounds:
            continue

        has_comp, comp_url = has_existing_open_pr(repo, num)
        if has_comp:
            continue

        passed_this_query += 1
        all_passed.append({
            "repo": repo,
            "number": num,
            "title": title,
            "url": url,
            "usd": str(usd_val),
            "author": data_author,
            "assoc": assoc,
            "query": query_str,
            "verdict": reason
        })
        print(f"  [PASS] {repo}#{num} (${usd_val}) - {title[:60]}", flush=True)

        # Break early once we have 3 solid proofs per query to keep run under 2 mins
        if passed_this_query >= 3:
            break

print("\n=================================================================", flush=True)
print(f"RESULTS: {len(all_passed)} GENUINE CANDIDATES VERIFIED LIVE THROUGH ALL GATES", flush=True)
print("=================================================================", flush=True)
for c in all_passed:
    print(f"* [{c['repo']}#{c['number']}]({c['url']}) | ${c['usd']} | @{c['author']} ({c['assoc']})")
    print(f"  Title: {c['title']}")
    print(f"  Query: {c['query']}")
    print(f"  Verdict: {c['verdict']}\n")
