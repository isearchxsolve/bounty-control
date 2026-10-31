"""Fail CI on credential-shaped literals; print locations, never credential bytes."""
from pathlib import Path
import json
import re
import subprocess


def scan(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'],
                            capture_output=True, check=True, timeout=30)
    findings = []
    for name in result.stdout.decode('utf-8').split('\0'):
        path = root / name
        if not name or not path.is_file():
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        for match in re.finditer(r'github_pat_[A-Za-z0-9_]{60,}|gh[pousr]_[A-Za-z0-9]{36,}', content):
            findings.append({'path': name, 'line': content.count('\n', 0, match.start()) + 1,
                             'kind': 'credential-shaped-literal'})
    return findings


if __name__ == '__main__':
    findings = scan(Path(__file__).resolve().parents[1])
    print(json.dumps({'credential_findings': findings}))
    raise SystemExit(bool(findings))
