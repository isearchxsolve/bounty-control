import subprocess
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

q = 'commenter:algora-pbc "$100" is:issue is:open is:public archived:false'
cmd = ['gh', 'api', 'search/issues', '-f', f'q={q}', '--jq', '.items']
try:
    out = subprocess.check_output(cmd)
    items = json.loads(out)
    print(f"API Returned {len(items)} items for {q!r}")
    for it in items:
        repo_url = it.get('repository_url', '')
        repo = '/'.join(repo_url.split('/')[-2:])
        num = it.get('number')
        title = it.get('title')
        print(f"  [{repo}#{num}] {title}")
except Exception as e:
    print(f"API ERROR: {e}")
