import json
import os

print("=== Checking discovery directories ===")
scratch_dir = '../scratch'
entries = sorted(os.listdir(scratch_dir))
for name in sorted(os.listdir(scratch_dir)):
    full = os.path.join(scratch_dir, name)
    if os.path.isdir(full) and name.startswith('discovery-'):
        print(f"\n=== {name} ===")
        sub = sorted(os.listdir(full))
        for item in sorted(os.listdir(full)):
            print(f"  {item}")
        # Read receipt.json if exists
        receipt_path = os.path.join(full, 'receipt.json')
        if os.path.exists(receipt_path):
            with open(receipt_path) as f:
                data = json.load(f)
            print(f"  RECEIPT: {json.dumps(data, indent=2)[:2000]}")
        # Check for PR info
        pr_path = os.path.join(full, 'pr.json')
        if os.path.exists(pr_path):
            with open(pr_path) as f:
                pr = json.load(f)
            print(f"  PR: {json.dumps(pr, indent=2)[:2000]}")
    print()
