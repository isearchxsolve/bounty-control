"""Inventory factual check locations without importing or executing the pipeline.

This is a structural index, not an automatic judgment that a gate is correct.
Pair the generated evidence with docs/GATE-FORENSIC-AUDIT-2026-11-04.md.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'agent_door', 'cline_entry_door', 'bounty_admission', 'issue_scout',
    'sovereign_discovery', 'actions_dispatch', 'pipeline_evidence', 'actions_github',
    'actions_delivery', 'actions_release', 'actions_reconcile', 'delivery_errors',
    'delivery_supervisor', 'publication_access_probe', 'run_pipeline_live_probes',
    'payment_gates', 'commercial_context', 'kaggle_engine_worker', 'check_tracked_secrets',
    'live_pipeline_resume', 'pipeline_lineage', 'nvidia_router', 'tokenharbor_router',
    'cline_process', 'discovery_heartbeat', 'pr_conversion_watch',
)


def inventory():
    files, sites, tables = {}, [], []
    for module in MODULES:
        path = ROOT / 'scripts' / (module + '.py')
        raw = path.read_bytes(); source = raw.decode('utf-8-sig')
        name = path.relative_to(ROOT).as_posix()
        files[name] = hashlib.sha256(raw).hexdigest()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Raise, ast.Assert)):
                sites.append({'file': name, 'line': node.lineno, 'kind': type(node).__name__,
                              'expression': ast.unparse(node)})
            elif isinstance(node, ast.Return):
                values = [c.value for c in ast.walk(node) if isinstance(c, ast.Constant)
                          and isinstance(c.value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{3,}(?::.*)?', c.value)]
                if values:
                    sites.append({'file': name, 'line': node.lineno, 'kind': 'ReturnCodes', 'codes': values})
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('GATE_CHECKS', 'DOWNSTREAM_CHECKS'):
                        tables.append({'file': name, 'name': target.id, 'values': ast.literal_eval(node.value)})
    workflows = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((ROOT / '.github/workflows').glob('*.yml'))}
    return {'generated_at': datetime.now(timezone.utc).isoformat(),
            'base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'scope': 'Actions control plane and shared guards, including legacy branches in these modules; optional external deployments not certified',
            'interpretation': 'Raises/assertions and named return literals are structural candidates, not a proof that every predicate or deployment is safe',
            'source_files': files, 'workflows': workflows, 'sites': sorted(sites, key=lambda s: (s['file'], s['line'])),
            'reason_tables': tables}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'modules': len(report['source_files']), 'sites': len(report['sites']),
                      'workflows': len(report['workflows']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
