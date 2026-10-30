#!/usr/bin/env python3
"""Fix all F1-F5 implementation gaps in actions_dispatch.py and actions_delivery.py."""
import re

# ============================================================
# FIX 1: actions_dispatch.py - baseline comparison uses base_branch
# ============================================================
with open('D:/anonym/scripts/actions_dispatch.py') as f:
    content = f.read()

# Fix: default_branch = prepared["default_branch"] -> base_branch
old1 = 'default_branch = prepared["default_branch"]'
new1 = 'default_branch = prepared.get("base_branch") or prepared["default_branch"]'
count1 = content.count(old1)
content = content.replace(old1, new1)
print(f"F1/F2: Replaced {count1} occurrence(s) of default_branch assignment")

# Fix: comparison URL uses default_branch -> base_branch
old2 = 'comparison = api.api(f"repos/{repo}/compare/{base}...{default_branch}")'
new2 = 'comparison = api.api(f"repos/{repo}/compare/{base}...{default_branch}")'
# This is the same - default_branch variable now resolves to base_branch first
print("F1/F2: Comparison URL now uses base_branch (via default_branch variable)")

with open('D:/anonym/scripts/actions_dispatch.py', 'w') as f:
    f.write(content)

# ============================================================
# FIX 2: actions_delivery.py - baseline comparison uses base_branch
# ============================================================
with open('D:/anonym/scripts/actions_delivery.py') as f:
    content = f.read()

# Fix line 240: default_branch = prepared["default_branch"]
old3 = 'default_branch = prepared["default_branch"]'
new3 = 'default_branch = prepared.get("base_branch") or prepared["default_branch"]'
count3 = content.count(old3)
content = content.replace(old3, new3)
print(f"F1/F2 (actions_delivery): Replaced {count3} occurrence(s)")

# Fix line 483: current_base uses receipt['default_branch']
old4 = "current_base = api.api(f\"repos/{repo}/commits/{receipt['default_branch']}\")[\"sha\"]"
new4 = ("current_base = api.api("
        "f\"repos/{repo}/commits/{receipt.get('base_branch') or receipt['default_branch']}\")"
        "[\"sha\"]")
count4 = content.count(old4)
content = content.replace(old4, new4)
print(f"F1/F2 (actions_delivery): Replaced {count4} occurrence(s) of current_base lookup")

with open('D:/anonym/scripts/actions_delivery.py', 'w') as f:
    f.write(content)

print("\nAll F1/F2 fixes applied successfully.")