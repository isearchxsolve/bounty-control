import json, os

base = 'D:/anonym/scratch'
dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and d.startswith('discovery-')]
for d in sorted(dirs, reverse=True):
    rpath = os.path.join(base, d, 'receipts.jsonl')
    if os.path.exists(rpath):
        print(f'=== {d} ===')
        with open(rpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    phase = data.get('phase','?')
                    phase_type = data.get('phase_type','?')
                    print(f'  phase={phase} phase_type={phase_type}')
                    counts = data.get('counts',{})
                    print(f'    counts={counts}')
                    qf = data.get('qualified_fresh')
                    qu = data.get('qualified_unique')
                    d = data.get('dispatched')
                    print(f'  qualified_fresh={qf}, qualified_unique={qu}')
                    print(f'  dispatched={d}')
                    print()
                except:
                    pass
        print()