import subprocess
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

def gh_api(endpoint):
    cmd = ["gh", "api", endpoint]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0:
        return json.loads(res.stdout)
    return {"error": res.stderr.strip()}

print("=" * 70)
print("1. GEEKINASUIT/OBOLUS (PR #131 & ISSUE #81)")
print("=" * 70)
pr131 = gh_api("repos/geekinasuit/obolus/pulls/131")
print(f"PR #131 State: {pr131.get('state')} | Merged: {pr131.get('merged')}")
pr131_comments = gh_api("repos/geekinasuit/obolus/issues/131/comments")
if isinstance(pr131_comments, list):
    for c in pr131_comments[-3:]:
        user = c.get("user", {}).get("login", "")
        body = c.get("body", "")
        print(f"[@{user} on PR #131]:\n{body}\n")
else:
    print("Comments error:", pr131_comments)

issue81_comments = gh_api("repos/geekinasuit/obolus/issues/81/comments")
if isinstance(issue81_comments, list):
    for c in issue81_comments[-2:]:
        user = c.get("user", {}).get("login", "")
        body = c.get("body", "")
        print(f"[@{user} on Issue #81]:\n{body}\n")

print("=" * 70)
print("2. SYBIL-SOLUTIONS/LOCAL-AI-REGISTRY (ISSUE #219)")
print("=" * 70)
issue219 = gh_api("repos/sybil-solutions/local-ai-registry/issues/219")
print(f"Issue #219 Title: {issue219.get('title')} | State: {issue219.get('state')}")
issue219_comments = gh_api("repos/sybil-solutions/local-ai-registry/issues/219/comments")
if isinstance(issue219_comments, list):
    for c in issue219_comments[-3:]:
        user = c.get("user", {}).get("login", "")
        body = c.get("body", "")
        print(f"[@{user} on Issue #219]:\n{body}\n")
else:
    print("Comments error:", issue219_comments)

print("=" * 70)
print("3. DOOMSDAY-NETWORK/BOUNTY-GUARD")
print("=" * 70)
dg_issues = gh_api("repos/doomsday-network/bounty-guard/issues?state=all&per_page=3")
if isinstance(dg_issues, list):
    for it in dg_issues:
        print(f"#{it.get('number')} {it.get('title')}: state={it.get('state')} url={it.get('html_url')}")
        ic = gh_api(f"repos/doomsday-network/bounty-guard/issues/{it.get('number')}/comments")
        if isinstance(ic, list) and ic:
            last = ic[-1]
            print(f"   Last comment by @{last.get('user', {}).get('login')}: {last.get('body')[:200]}...")
else:
    print("DG error:", dg_issues)
