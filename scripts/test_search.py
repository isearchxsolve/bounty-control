import subprocess
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

queries = [
    '"willing to pay" state:open',
    '"paid consulting" state:open',
    '"bounty" urgent state:open',
    '"happy to pay" state:open'
]

for q in queries:
    cmd = ["gh", "search", "issues", q, "--sort", "updated", "--limit", "5", "--json", "repository,number,title,updatedAt"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 0:
        items = json.loads(r.stdout)
        print(f"Query: {q} | Count: {len(items)}")
        for it in items[:3]:
            repo = it.get("repository", {}).get("nameWithOwner")
            num = it.get("number")
            title = it.get("title")
            print(f"  -> {repo}#{num}: {title}")
