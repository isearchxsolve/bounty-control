#!/usr/bin/env python3
"""Fix F5: claim() should store lease_expires_at and use _lease_expired_and_dead."""
with open('D:/anonym/scripts/actions_github.py') as f:
    content = f.read()

# Fix: Store lease_expires_at when claiming
old = '''return {**old, "status": "CLAIMED", "attempt": attempt, "owner": owner,
                    "previous_owner": old.get("owner"), "previous_status": old.get("status"),
                    "run_url": run_url, "harness_sha": harness_sha, "claimed_at": utcnow()}'''
new = '''return {**old, "status": "CLAIMED", "attempt": attempt, "owner": owner,
                    "previous_owner": old.get("owner"), "previous_status": old.get("status"),
                    "run_url": run_url, "harness_sha": harness_sha, "claimed_at": utcnow(),
                    "lease_expires_at": _lease_expires_at(utcnow())}'''
count = content.count(old)
content = content.replace(old, new)
print(f"Replaced {count} occurrence(s) of claim return with lease_expires_at")

with open('D:/anonym/scripts/actions_github.py', 'w') as f:
    f.write(content)
print("Done")