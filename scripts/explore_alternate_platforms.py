import sys
import subprocess
import json
import urllib.parse

queries = [
    'bountyhub is:issue is:open',
    'bountyhub-bot is:issue is:open',
    'opire.dev is:issue is:open',
    '"/reward" is:issue is:open',
    'issuehunt.io is:issue is:open',
    'label:bounty "Open Collective" is:issue is:open',
    'label:bounty "$100" is:issue is:open',
    'label:bounty "$200" is:issue is:open',
]

for q in queries:
    encoded_q = urllib.parse.quote(q)
    cmd = ['gh', 'api', f'/search/issues?q={encoded_q}&sort=created&order=desc&per_page=5', '--jq', '.items']
    try:
        out = subprocess.check_output(cmd, text=True, encoding='utf-8')
        items = json.loads(out)
        print(f"\n=== Query: {q!r} -> Found {len(items)} items ===")
        for it in items:
            repo = "/".join(it.get("repository_url", "").rstrip("/").split("/")[-2:])
            num = it.get("number")
            title = it.get("title", "")
            comments = it.get("comments", 0)
            created = it.get("created_at", "")[:10]
            print(f"  [{repo}#{num}] (created: {created}, comments: {comments}) {title[:60]}")
    except Exception as e:
        print(f"Query {q!r} error: {e}")
