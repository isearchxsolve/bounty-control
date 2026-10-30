import sys
sys.path.append('scripts')
import autonomous_icu_pipeline as aip

queries = [
    '--commenter algora-pbc "$500"',
    '--commenter algora-pbc "$250"',
    '--commenter algora-pbc "$100"',
    '--commenter algora-pbc "$50"',
    'algora "$500"',
    'algora "$250"',
    'algora "$100"',
    'polar.sh "$100"',
    'polar.sh "$50"',
    'opire.dev "$100"',
    'opire.dev "$50"',
]

print("=== RUNNING MULTI-QUERY LIVE INFLUX DISCOVERY ===")
all_discovered = {}
for q in queries:
    items = aip.search_issues(q, limit=10)
    print(f"\nQuery {q!r} -> Retained {len(items)}")
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        title = it.get('title')
        key = (repo, num)
        if key not in all_discovered:
            all_discovered[key] = title
            print(f"  + DISCOVERED: [{repo}#{num}] {title[:60]}")

print(f"\n=== SUMMARY: TOTAL UNIQUE CANDIDATE BOUNTIES: {len(all_discovered)} ===")
repos = set(k[0] for k in all_discovered.keys())
print(f"DISTINCT REPOSITORIES: {len(repos)}")
for r in sorted(repos):
    print(f"  - {r}")
