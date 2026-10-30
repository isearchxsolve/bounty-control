import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import search_issues, run_cmd
import json

queries = [
    'bounty in:title',
    '--label bounty',
    '--commenter algora-pbc',
    'polar.sh',
    'opire.dev',
]

for q in queries:
    items = search_issues(q, limit=10)
    print(f"Query: {q!r} -> Retained {len(items)} items")
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        title = it.get('title')
        print(f"  {repo}#{num}: {title}")
