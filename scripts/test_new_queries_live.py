import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import search_issues
import json

queries = [
    '--commenter algora-pbc "$50"',
    '--commenter algora-pbc "$100"',
    '--commenter algora-pbc "$250"',
    '--commenter algora-pbc "$500"',
    'bounty "$50"',
    'bounty "$100"',
    'bounty "$500"',
    'bounty "$1000"',
    'opire.dev "$50"',
    'opire.dev "$100"',
]

print("=== TESTING NEW HIGH-TICKET DISCOVERY QUERIES ===")
retained_total = []
for q in queries:
    items = search_issues(q, limit=10)
    print(f"\nQuery: {q!r} -> Retained {len(items)} items")
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        title = it.get('title')
        print(f"  [{repo}#{num}] {title}")
        retained_total.append((repo, num, title))

print(f"\nTOTAL QUALIFIED CANDIDATES RETAINED: {len(retained_total)}")
