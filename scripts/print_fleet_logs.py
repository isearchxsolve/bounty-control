import urllib.request
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

door = "https://omniroute-relay.omniroute-fleet-kd.workers.dev"
token = "GOLD24"

def fetch(body, limit=10):
    try:
        url = f"{door}/say?body={body}&token={token}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")).get("orders", [])
    except Exception as e:
        return [{"text": f"Error: {e}"}]

print("=" * 80)
print(f"⚡ LIVE KAGGLE FLEET STREAM LOGS  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
print(f"Fleet Door: {door}")
print("=" * 80)

print("\n[1] ACTIVE ENGINES ONLINE:")
regs = fetch("ENGINE_REGISTRATION", limit=10)
for r in regs[-6:]:
    print("  🟢", r.get("text", ""))

print("\n[2] RECENT TASK CLAIMS (DISTRIBUTED QUEUE):")
claims = fetch("BOUNTY_CLAIM", limit=10)
for c in claims[-8:]:
    print("  ⚡", c.get("text", ""))

print("\n[3] ENGINE EXECUTION VERDICTS (PROVEN CI/CD & PRs):")
results = fetch("BOUNTY_RESULT", limit=10)
for res in results[-8:]:
    txt = res.get("text", "")
    icon = "✅" if "SUCCESS" in txt else "❌"
    print(f"  {icon} {txt}")

print("\n[4] PENDING TASKS IN QUEUE:")
tasks = fetch("BOUNTY_TASK", limit=5)
if tasks:
    for t in tasks[-5:]:
        print("  📦", t.get("text", "")[:100])
else:
    print("  (Queue clean - dispatcher scanning for genuine code bounties)")
print("=" * 80)
