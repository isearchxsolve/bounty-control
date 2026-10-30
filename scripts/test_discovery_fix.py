import sys
sys.path.append('scripts')
import autonomous_icu_pipeline as aip

# Test queries
queries = [
    '--commenter algora-pbc "$500"',
    'algora bounty "$500"',
    'bounty "$500"',
]

for q in queries:
    items = aip.search_issues(q, limit=10)
    print(f"Query {q!r} -> Retained {len(items)}")
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        print(f"  [{repo}#{num}] {it.get('title')}")
