import subprocess
import json
import time

cmd = ['gh', 'search', 'issues', 'production "will pay" state:open', '--limit', '10', '--json', 'repository,number,title']
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
d = json.loads(r.stdout)
for it in d:
    repo = it.get('repository', {}).get('nameWithOwner')
    num = it.get('number')
    print(f"{repo}#{num} : {it.get('title')}")
    t0 = time.time()
    v_cmd = ['gh', 'issue', 'view', str(num), '--repo', repo, '--json', 'body,author,title,state,comments']
    vr = subprocess.run(v_cmd, capture_output=True, text=True, encoding='utf-8', timeout=20)
    print(f"  View took: {round(time.time() - t0, 2)}s | Return code: {vr.returncode}")
    if vr.returncode != 0:
        print(f"  Error: {vr.stderr[:200]}")
