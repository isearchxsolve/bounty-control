import subprocess, json

# Check engine2 runs for the latest commits
result = subprocess.run(['gh', 'run', 'list', '--workflow=engine2.yml', '--limit', '5', '--json', 'databaseId,status,conclusion,name,createdAt,headBranch'], capture_output=True, text=True)
try:
    runs = json.loads(result.stdout)
    for r in runs:
        print(f'Run {r["databaseId"]}: {r["status"]} {r.get("conclusion","?")} {r["name"][:40]}')
except:
    print(result.stdout[:500])

# Check for PRs
result = subprocess.run(['gh', 'pr', 'list', '--repo', 'isearchxsolve/anonym-family-archive', '--state', 'all', '--limit', '10', '--json', 'number,title,state,createdAt,headRefName'], capture_output=True, text=True)
try:
    prs = json.loads(result.stdout)
    print(f'\nTotal PRs: {len(prs)}')
    for p in prs[:10]:
        print(f'  #{p["number"]} {p["title"][:60]} ({p["state"]}) {p["headRefName"][:40]}')
except Exception as e:
    print(f'Error: {e}')
    print(result.stdout[:500])