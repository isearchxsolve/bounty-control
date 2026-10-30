import re

with open('bounty_admission.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = r'r"encryption|signatures?|deadlocks?)\\b", re.I)'
new = r'r"encryption|signatures?|deadlocks?|bug\w*|error\w*|fail\w*|broken|issue\w*|problem\w*|defect\w*)\b", re.I)'

if old in content:
    content = content.replace(old, new, 1)
    with open('bounty_admission.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Successfully updated HARD regex')
else:
    print('Pattern not found!')
    with open('bounty_admission.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    print(f'Line 113: {lines[112]!r}')