import subprocess
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

queries = [
    'commenter:algora-pbc "$50"',
    'commenter:algora-pbc "$100"',
    'commenter:algora-pbc "$200"',
    'commenter:algora-pbc "$250"',
    'commenter:algora-pbc "$500"',
    'commenter:algora-pbc "$1000"',
    'bounty "$50"',
    'bounty "$100"',
    'bounty "$200"',
    'bounty "$250"',
    'bounty "$500"',
    'bounty "$1000"',
    '"polar.sh" "$50"',
    '"polar.sh" "$100"',
    '"opire.dev" "$50"',
    '"opire.dev" "$100"',
]

print("=== SEARCHING $50+ BOUNTIES ACROSS GITHUB ===")
found = []
for q in queries:
    import shlex
    parts = shlex.split(q)
    cmd = ['gh', 'search', 'issues'] + parts + ['--state', 'open', '--limit', '10', '--json', 'repository,number,title,url,commentsCount']
    try:
        out = subprocess.check_output(cmd, timeout=30)
        items = json.loads(out)
        print(f"\nQuery: {q} -> Found {len(items)} items")
        for it in items[:3]:
            repo = it.get('repository', {}).get('nameWithOwner')
            num = it.get('number')
            title = it.get('title')
            url = it.get('url')
            print(f"  [{repo}#{num}] {title}")
            found.append((repo, num, title, url))
    except Exception as e:
        print(f"Query {q} error: {e}")

print(f"\nTotal raw results collected: {len(found)}")
