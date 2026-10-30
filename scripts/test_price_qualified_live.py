import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import search_issues
import json

queries = [
    'commenter:algora-pbc "$100"',
    'commenter:algora-pbc "$500"',
    'bounty "$100"',
    'bounty "$500"',
    'opire.dev "$50"',
    'opire.dev "$100"',
]

print("=== TESTING LIVE HIGH-TICKET DISCOVERY ===")
retained_total = []
for q in queries:
    items = search_issues(q, limit=10)
    print(f"\nQuery: {q!r} -> Raw={len(items)}")
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        title = it.get('title')
        print(f"  RETAINED: [{repo}#{num}] {title}")
        retained_total.append((repo, num, title))

print(f"\nTOTAL QUALIFIED CANDIDATES RETAINED: {len(retained_total)}")
