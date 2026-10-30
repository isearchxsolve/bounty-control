import subprocess
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

test_queries = [
    ['commenter:algora-pbc'],
    ['"console.algora.io"'],
    ['polar.sh'],
    ['opire.dev'],
    ['bounty', 'concurrency'],
    ['bounty', 'race condition'],
    ['bounty', 'memory leak'],
    ['bounty', 'compiler'],
    ['bounty', 'performance'],
    ['bounty', 'distributed'],
    ['bounty', 'protocol'],
]

print("--- TESTING GLOBAL HIGH-INFLUX QUERIES ON GITHUB ---")
for q in test_queries:
    cmd = ['gh', 'search', 'issues'] + q + ['--state', 'open', '--limit', '10', '--json', 'repository,number,title,commentsCount']
    try:
        out = subprocess.check_output(cmd, timeout=30)
        items = json.loads(out)
        print(f"\nQuery: {' '.join(q)} -> Returned {len(items)} items")
        for it in items[:3]:
            repo = it.get('repository', {}).get('nameWithOwner')
            num = it.get('number')
            title = it.get('title')
            comments = it.get('commentsCount')
            print(f"  [{repo}#{num}] (comments: {comments}) {title}")
    except Exception as e:
        print(f"\nQuery: {' '.join(q)} -> ERROR: {e}")
