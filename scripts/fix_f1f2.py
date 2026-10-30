#!/usr/bin/env python3
"""Fix F1/F2: baseline comparison must use base_branch from prepared, not default_branch."""
with open('D:/anonym/scripts/actions_delivery.py') as f:
    content = f.read()

# Fix line 240: default_branch = prepared["default_branch"] -> base_branch
old = 'default_branch = prepared["default_branch"]'
new = 'default_branch = prepared.get("base_branch") or prepared["default_branch"]'
if old in content:
    content = content.replace(old, new)
    print("Fixed line 240: default_branch = prepared.get('base_branch') or prepared['default_branch']")
else:
    print("WARNING: Could not find line 240 pattern")

# Fix line 483: current_base = api.api(f"repos/{repo}/commits/{receipt['default_branch']}")
old2 = "current_base = api.api(f\"repos/{repo}/commits/{receipt['default_branch']}\")[\"sha\"]"
new2 = "current_base = api.api(f\"repos/{repo}/commits/{receipt.get('base_branch') or receipt['default_branch']}\")[\"sha\"]"
if old2 in content:
    content = content.replace(old2, new2)
    print("Fixed line 483: current_base uses base_branch or default_branch")
else:
    print("WARNING: Could not find line 483 pattern")

with open('D:/anonym/scripts/actions_delivery.py', 'w') as f:
    f.write(content)
print("Done")