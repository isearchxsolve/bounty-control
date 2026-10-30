import json, os

base = '../scratch'
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
                    print(f'  phase={data.get("phase","?")} phase_type={data.get("phase_type","?")}')
                    print(f'    counts={data.get("counts",{})}')
                    print(f'    qualified_fresh={data.get("qualified_fresh")}, qualified_unique={data.get("qualified_unique")}')
                    print(f'    dispatched={data.get("dispatched")}')
                    print()
                except:
                    pass
        print()