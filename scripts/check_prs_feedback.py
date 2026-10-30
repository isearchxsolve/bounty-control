import subprocess
import json

targets = [
    ('paraloom-labs/paraloom-core', 1234),
    ('paraloom-labs/paraloom-core', 1233),
    ('up2itnow0822/ClawPowers-Skills', 208),
    ('Tarsnap/kivaloo', 402),
    ('bl4ckb4ll/blackball', 182),
]

print("=== CHECKING MAINTAINER FEEDBACK & REVIEWS ON RECENT DELIVERED PRS ===")
for repo, num in targets:
    cmd = ['gh', 'pr', 'view', str(num), '--repo', repo, '--json', 'title,state,comments,reviews,url']
    try:
        out = subprocess.check_output(cmd, text=True, encoding='utf-8')
        d = json.loads(out)
        state = d.get("state")
        comments = d.get('comments', [])
        reviews = d.get('reviews', [])
        print(f"\n--------------------------------------------------")
        print(f"PR: {repo}#{num} [{state}] - {d.get('title')}")
        print(f"URL: {d.get('url')}")
        print(f"Comments: {len(comments)} | Reviews: {len(reviews)}")
        for c in comments:
            auth = (c.get('author') or {}).get('login', 'unknown')
            body = c.get('body', '')[:300]
            print(f"  💬 [Comment by {auth}]:\n    {body}")
        for r in reviews:
            auth = (r.get('author') or {}).get('login', 'unknown')
            st = r.get('state')
            body = r.get('body', '')[:300]
            print(f"  👁️ [Review by {auth} - {st}]:\n    {body}")
    except Exception as e:
        print(f"Error {repo}#{num}: {e}")
