import json, subprocess

queries = [
    'label:bug "will pay" is:issue is:open',
    'label:bug "$250" is:issue is:open',
    'label:bug "$200" is:issue is:open',
    'label:bug "$150" is:issue is:open',
    'label:bug "$100" is:issue is:open',
    'label:bug "I will pay" is:issue is:open',
    'label:bug "bounty" is:issue is:open',
    'label:bug "reward" is:issue is:open',
    'label:bug "fix" "will pay" is:issue is:open',
    'label:bug "fix" "$250" is:issue is:open',
    'label:bug "fix" "$200" is:issue is:open',
    'label:bug "fix" "$150" is:issue is:open',
    'label:bug "fix" "$100" is:issue is:open',
]

for q in queries:
    cmd = ['gh', 'search', 'issues', q, '--state', 'open', '--archived=false',
           '--visibility', 'public', '--limit', '5',
           '--json', 'number,title,repository,labels']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f'ERROR: {result.stderr[:200]}')
        continue
    items = json.loads(result.stdout)
    print(f'QUERY: {q}')
    print(f'  Found {len(items)} issues')
    for it in items[:5]:
        labels = [l.get('name', '') for l in (it.get('labels') or [])]
        print(f'  #{it["number"]} {it["title"][:60]} labels={labels}')
    print()