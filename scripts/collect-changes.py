"""Compatibility collector. Paths are lossless data, never proof of verification."""
import json
from pathlib import Path
from actions_release import status_paths, product_paths


def collect_nul_safe_changes():
    paths = status_paths(Path.cwd())
    destination = Path('../harness')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'changed-files.json').write_text(json.dumps(paths, ensure_ascii=True), encoding='utf-8')
    (destination / 'changed-files.nul').write_bytes(b''.join(p.encode('utf-8') + bytes([0]) for p in paths))
    if not product_paths(paths):
        raise ValueError('No product changes; collector cannot declare delivery success')
    print(json.dumps({'changed_files': paths, 'verification': 'NOT_EVALUATED'}))
    return paths


if __name__ == '__main__':
    collect_nul_safe_changes()
