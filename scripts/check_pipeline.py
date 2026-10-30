import json, subprocess

print("=== ENGINE2 WORKFLOW RUNS ===")
result = subprocess.run(['gh', 'run', 'list', '--workflow=engine2.yml', '--limit', '10', '--json', 'databaseId,status,conclusion,name,createdAt,headBranch'], capture_output=True, text=True)
try:
    runs = json.loads(result.stdout)
    for r in runs:
        print(f"  {r['databaseId']} {r['status']} {r.get('conclusion','?')} {r['createdAt']} {r['name'][:50]}")
except Exception as e:
    print(f"Error parsing workflow runs: {e}")
    print(result.stdout[:500])

print()
print("=== ALL PRs ===")
result = subprocess.run(['gh', 'pr', 'list', '--repo', 'isearchxsolve/anonym-family-archive', '--state', 'all', '--limit', '10', '--json', 'number,title,state,createdAt,headRef'], capture_output=True, text=True)
try:
    prs = json.loads(result.stdout)
    print(f'Total PRs: {len(prs)}')
    for p in prs[:10]:
        print(f'  #{p["number"]} {p["title"][:60]} ({p["state"]}) {p["headRef"][:50]}')
except Exception as e:
    print(f'Error: {e}')
    print(result.stdout[:500])