"""Read-only access to the production entry verifier for an agent's own rows."""
import argparse
import json
from pathlib import Path

from actions_github import GitHub
from cline_entry_door import verify_model_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.path.read_text(encoding='utf-8').splitlines() if line.strip()]
    result = verify_model_rows(rows, admission_client=GitHub())
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result.get('admitted') and not result.get('refused') and not result.get('unpriced') else 1


if __name__ == '__main__':
    raise SystemExit(main())
