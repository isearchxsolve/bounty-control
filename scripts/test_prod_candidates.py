import subprocess
import json
import time

cmd = ['gh', 'search', 'issues', 'production "will pay" state:open', '--limit', '10', '--json', 'repository,number,title']
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
d = json.loads(r.stdout)

print(f"Total candidates found: {len(d)}")
for it in d:
    repo = it.get('repository', {}).get('nameWithOwner')
    num = it.get('number')
    print(f"Testing {repo}#{num}...")
    t0 = time.time()
    v_cmd = ['gh', 'issue', 'view', str(num), '--repo', repo, '--json', 'body,author,title,labels,state']
    try:
        vr = subprocess.run(v_cmd, capture_output=True, text=True, encoding='utf-8', timeout=15)
        print(f"  Took: {round(time.time() - t0, 2)}s | Code: {vr.returncode}")
        if vr.returncode != 0:
            print(f"  Err: {vr.stderr[:100]}")
    except subprocess.TimeoutExpired:
        print(f"  TIMED OUT after 15s!")
