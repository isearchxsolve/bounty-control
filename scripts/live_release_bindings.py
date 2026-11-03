"""Independent release-boundary probes using real GitHub source, Git and native commands.

These are isolated release-contract fault resources, never customer delivery receipts.
Nothing is pushed, published or written to the fleet ledger. The upstream fixture is
the existing owned livefire repository; production release gates generate the native
and regression evidence, and the unmodified publisher validates the real Git bundle.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

from actions_github import repository, task_id
from actions_release import (git, manifest, protect_baseline_tests, regression_proof,
                             require_commands, status_paths, validate_plan_contract, write_json)


def build_probe_release(folder, repo='isearchxsolve/oss-hunter-livefire'):
    """Build an isolated bundle after actual baseline, red/green and native gates.

    `VERIFIED` in the schema means these release gates passed on this probe resource.
    `probe_fixture` and the retained command receipts explicitly limit that meaning.
    """
    repo = repository(repo)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    root = folder / 'source'
    if (folder / 'release.json').is_file() and (folder / 'release.bundle').is_file():
        retained = json.loads((folder / 'release.json').read_text(encoding='utf-8'))
        if retained.get('probe_fixture') is not True or retained.get('repo') != repo:
            raise ValueError('Retained release belongs to a different probe resource')
        return retained, folder / 'release.bundle'
    if not root.exists():
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false', '-c', 'submodule.recurse=false',
                        'clone', '--quiet', 'https://github.com/' + repo + '.git', str(root)],
                       check=True, timeout=180)
    elif git(root, 'remote', 'get-url', 'origin').stdout.decode().strip() != 'https://github.com/' + repo + '.git':
        raise ValueError('Retained source belongs to a different probe resource')
    git(root, 'config', 'core.autocrlf', 'false')
    base = git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    branch = git(root, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD').stdout.decode().strip().removeprefix('origin/')
    python = sys.executable
    baseline_command = [python, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    build_command = [python, '-B', '-m', 'compileall', '-q', 'duration_utils.py']
    retained_tests = list((root / 'tests').glob('test_independent_release_*.py'))
    if len(retained_tests) > 1:
        raise ValueError('Ambiguous retained companion probe')
    test_name = retained_tests[0].stem if retained_tests else 'test_independent_release_' + uuid.uuid4().hex[:10]
    targeted_command = [python, '-B', '-m', 'unittest', 'tests.' + test_name, '-v']
    plan = {'bootstrap': [], 'builds': [build_command], 'baseline_tests': [baseline_command],
            'targeted_tests': [targeted_command], 'final_tests': [baseline_command],
            'linters': [], 'format_checks': []}
    validate_plan_contract(SimpleNamespace(**plan))
    native_path = folder / 'native-commands.json'
    native = json.loads(native_path.read_text(encoding='utf-8')) if native_path.is_file() else []

    def execute(argv):
        started = time.monotonic()
        result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=60,
                                encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        row = {'argv': list(argv), 'cwd': str(root), 'exit_code': result.returncode,
               'stdout': result.stdout, 'stderr': result.stderr,
               'duration_s': time.monotonic() - started}
        native.append(row)
        write_json(folder / 'native-commands.json', native)
        return SimpleNamespace(**row)

    baseline = [native[0]] if native and native[0]['argv'] == baseline_command and native[0]['exit_code'] == 0 else [vars(execute(baseline_command))]
    require_commands(plan['baseline_tests'], baseline)
    product = root / 'duration_utils.py'
    original = git(root, 'show', base + ':duration_utils.py').stdout.decode('utf-8')
    if '_UNITS = {\n' not in original or '"d":' in original:
        raise ValueError('Owned release fixture no longer contains the prescribed missing-days fault')
    product.write_bytes(original.replace('_UNITS = {\n', '_UNITS = {\n    "d": 86400,\n', 1).encode('utf-8'))
    companion = 'tests/' + test_name + '.py'
    assertion = 'independent release probe must parse one day as 86400 seconds'
    (root / companion).write_text(
        'import unittest\nfrom duration_utils import parse_duration\n\n'
        'class DaysRegression(unittest.TestCase):\n'
        '    def test_days(self):\n'
        '        self.assertEqual(parse_duration("1d"), 86400, ' + repr(assertion) + ')\n',
        encoding='utf-8', newline='\n')
    paths = status_paths(root)
    protect_baseline_tests(root, base, paths)
    regression = regression_proof(root, base,
        {'test_files': [companion], 'argv': targeted_command, 'expected_failure': assertion}, execute)
    before = manifest(root, status_paths(root))
    commands = plan['builds'] + plan['baseline_tests'] + plan['targeted_tests'] + plan['final_tests']
    verified = [vars(execute(command)) for command in commands]
    require_commands(commands, verified)
    if manifest(root, status_paths(root)) != before:
        raise ValueError('Actual native verification modified the proposed probe source')
    git(root, 'diff', '--check', base)
    git(root, 'config', 'user.name', 'Independent release probe')
    git(root, 'config', 'user.email', 'release-probe@example.invalid')
    git(root, 'add', '--', *paths)
    git(root, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Isolated release-validator fault input')
    head = git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    bundle = folder / 'release.bundle'
    git(root, 'bundle', 'create', str(bundle), 'HEAD', '^' + base)
    harness = os.environ.get('GITHUB_SHA') or git(Path(__file__).resolve().parents[1], 'rev-parse', 'HEAD').stdout.decode().strip()
    run_id = os.environ.get('GITHUB_RUN_ID')
    control = os.environ.get('GITHUB_REPOSITORY')
    run_url = f'https://github.com/{control}/actions/runs/{run_id}' if control and run_id else str(folder / 'native-commands.json')
    receipt = {'schema': 1, 'status': 'VERIFIED', 'probe_fixture': True,
               'probe_scope': 'isolated release gates; not customer engineering, publication or payment',
               'task_id': task_id(repo, 1), 'repo': repo, 'issue_number': 1,
               'owner': (run_id or 'local-release-probe') + ':' + os.environ.get('GITHUB_RUN_ATTEMPT', '1'),
               'harness_sha': harness, 'base_sha': base, 'head_sha': head,
               'tree_sha': git(root, 'rev-parse', 'HEAD^{tree}').stdout.decode().strip(),
               'default_branch': branch, 'base_branch': branch, 'files': before, 'plan': plan,
               'sources': [{'path': 'pyproject.toml', 'sha256': hashlib.sha256(
                   git(root, 'show', base + ':pyproject.toml').stdout).hexdigest()}],
               'regression': regression, 'baseline': baseline, 'verification': verified,
               'admission': {'probe_fixture': True}, 'run_url': run_url,
               'at': datetime.now(timezone.utc).isoformat()}
    write_json(folder / 'release.json', receipt)
    return receipt, bundle


def run_release_probes(folder, repo='isearchxsolve/oss-hunter-livefire'):
    """Return independent live gate outcomes, keeping all actual inputs and artifacts."""
    from actions_delivery import validate_bundle
    folder = Path(folder).resolve()
    outcomes = []
    mutations = {
        'TASK_IDENTITY': (lambda r: r.update(task_id='0' * 32), 'task identity mismatch'),
        'HEAD': (lambda r: r.update(head_sha='0' * 40), 'Bundle HEAD mismatch'),
        'TREE': (lambda r: r.update(tree_sha='0' * 40), 'Release tree mismatch'),
        'FILE_MANIFEST': (lambda r: r.update(files={}), 'Changed-file release proof mismatch'),
        'NATIVE_RECEIPTS_MISSING': (lambda r: r.update(verification=[]), 'lacks a successful receipt'),
        'REGRESSION_NEVER_RED': (lambda r: r['regression'].update(red_exit=0), 'Red-to-green regression proof missing'),
        'REGRESSION_NOT_GREEN': (lambda r: r['regression'].update(green_exit=1), 'Red-to-green regression proof missing'),
    }
    try:
        receipt, bundle = build_probe_release(folder, repo)
    except Exception as exc:
        folder.mkdir(parents=True, exist_ok=True)
        outcomes.append({'case': 'LIVE_RELEASE_PROBE_POSITIVE_CONTROL', 'status': 'FAIL', 'diagnostic': str(exc)})
        outcomes.extend({'case': 'LIVE_RELEASE_' + name, 'status': 'BLOCKED',
                         'prerequisite': 'Independent release positive control could not be built'} for name in mutations)
        write_json(folder / 'probe-results.json', outcomes)
        return outcomes
    previous = os.environ.get('GITHUB_SHA')
    os.environ['GITHUB_SHA'] = receipt['harness_sha']
    evidence = {'probe_fixture': True, 'source_repo': repo, 'base_sha': receipt['base_sha'],
                'head_sha': receipt['head_sha'], 'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(),
                'receipt': str(folder / 'release.json'), 'native_commands': str(folder / 'native-commands.json')}
    validation = folder / ('validation-' + uuid.uuid4().hex[:10])
    validation.mkdir()
    evidence['validation_artifacts'] = str(validation)
    try:
        try:
            validate_bundle(receipt, bundle, validation / 'positive-control')
        except Exception as exc:
            outcomes.append({'case': 'LIVE_RELEASE_PROBE_POSITIVE_CONTROL', 'status': 'FAIL', 'diagnostic': str(exc), **evidence})
            outcomes.extend({'case': 'LIVE_RELEASE_' + name, 'status': 'BLOCKED',
                             'prerequisite': 'Independent release positive control did not validate'} for name in mutations)
        else:
            outcomes.append({'case': 'LIVE_RELEASE_PROBE_POSITIVE_CONTROL', 'status': 'PASS', **evidence})
            for name, (mutate, expected) in mutations.items():
                changed = copy.deepcopy(receipt)
                mutate(changed)
                write_json(folder / ('fault-' + name + '.json'), changed)
                result = {'case': 'LIVE_RELEASE_' + name, **evidence}
                try:
                    validate_bundle(changed, bundle, validation / ('fault-check-' + name))
                except ValueError as exc:
                    result.update(status='PASS' if expected.lower() in str(exc).lower() else 'FAIL', refusal=str(exc))
                except Exception as exc:
                    result.update(status='FAIL', diagnostic=str(exc))
                else:
                    result.update(status='FAIL', diagnostic='Fault input was accepted')
                outcomes.append(result)
                write_json(folder / 'probe-results.json', outcomes)
    finally:
        if previous is None:
            os.environ.pop('GITHUB_SHA', None)
        else:
            os.environ['GITHUB_SHA'] = previous
    write_json(folder / 'probe-results.json', outcomes)
    return outcomes


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = run_release_probes(args.output)
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(row['status'] == 'PASS' for row in results) else 1)
