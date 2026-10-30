import subprocess, json

result = subprocess.run(['gh', 'run', 'list', '--workflow=bounty-discovery.yml', '--limit', '10', '--json', 'databaseId,status,conclusion,name,createdAt'], capture_output=True, text=True)
try:
    runs = json.loads(result.stdout)
    for r in runs:
        print(f'{r["databaseId"]} {r["status"]} {r.get("conclusion","?")} {r["createdAt"][:19]} {r["name"][:50]}')
except Exception as e:
    print(f'Error: {e}')
    print(result.stdout[:500])