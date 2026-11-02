"""Read-only access to the production entry verifier for an agent's own rows."""
import argparse
import json
from pathlib import Path

from actions_github import GitHub, StateStore
from agent_door import task_history_snapshot
from cline_entry_door import verify_model_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.path.read_text(encoding='utf-8').splitlines() if line.strip()]
    api = GitHub()
    result = verify_model_rows(rows, admission_client=api)
    store = StateStore(api)
    history = []
    for row in result.get('admitted') or []:
        state, _ = store.read(row['admission']['task_id'])
        if state:
            history.append(state)
    result['task_history'] = task_history_snapshot(history)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result.get('admitted') and not result.get('refused') and not result.get('unpriced') else 1


if __name__ == '__main__':
    raise SystemExit(main())
