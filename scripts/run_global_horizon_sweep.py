import sys
import json
import subprocess
sys.stdout.reconfigure(encoding='utf-8')

from autonomous_icu_pipeline import (
    search_issues,
    get_issue_fast,
    verify_genuine_icu_patient,
    score_hardness_and_competition,
    parse_and_normalize_bounty,
)

queries_to_test = [
    'commenter:algora-pbc',
    '"console.algora.io"',
    'polar.sh',
    'opire.dev',
    'bounty in:title',
    '--label bounty',
    'bounty "concurrency"',
    'bounty "race condition"',
    'bounty "memory leak"',
    'bounty "compiler"',
    'bounty "performance"',
]

print("=== GLOBAL HORIZON DISCOVERY SWEEP ===")
qualified_candidates = []
seen = set()

for q in queries_to_test:
    items = search_issues(q, limit=20)
    print(f"\n[QUERY] {q} -> Retained {len(items)} candidates from search_issues")
    for it in items:
        repo = it.get("repository", {}).get("nameWithOwner")
        num = it.get("number")
        key = f"{repo}#{num}"
        if key in seen:
            continue
        seen.add(key)
        
        # Hardness and qualification details
        hardness = score_hardness_and_competition(it)
        qualified_candidates.append({
            "key": key,
            "repo": repo,
            "num": num,
            "title": it.get("title"),
            "hardness": hardness,
            "url": it.get("url"),
            "comments": it.get("commentsCount", 0),
            "query": q
        })

print("\n" + "="*60)
print(f"TOTAL UNIQUE QUALIFIED CANDIDATES: {len(qualified_candidates)}")
print("="*60)

# Sort by Hardness
qualified_candidates.sort(key=lambda x: x["hardness"], reverse=True)

repos_seen = set()
for c in qualified_candidates:
    repos_seen.add(c["repo"])
    print(f"[{c['hardness']} pts] {c['key']} | Repo: {c['repo']}")
    print(f"   Title: {c['title']}")
    print(f"   URL: {c['url']}")

print(f"\nDISTINCT REPOSITORIES REPRESENTED: {len(repos_seen)}")
