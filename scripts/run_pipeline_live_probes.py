"""Run explicitly wired live master probes, collecting every result without fail-fast.

This is the live boundary companion to run_pipeline_master.py. A passing subset
never certifies full master parity or a successful continuous E2E delivery.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'test_pipeline_transport_live', 'test_pipeline_state_live', 'test_cline_process',
    'test_preflight.PreflightShapeTests',
    'test_preflight.PreflightClassificationTests.test_disk_below_floor_names_the_disk_subsystem_and_the_measured_figure',
    'test_preflight.PreflightClassificationTests.test_a_missing_executable_names_the_executable_subsystem',
    'test_preflight.PreflightClassificationTests.test_git_version_floor_is_enforced_in_both_directions',
)


class Receipts(unittest.TextTestResult):
    def __init__(self, *args, report, path, **kwargs):
        super().__init__(*args, **kwargs)
        self.report, self.path = report, path
        self.started = {}

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.report, indent=2) + '\n', encoding='utf-8')
        temp.replace(self.path)

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def receipt(self, test, status, diagnostic=None):
        evidence = {name: getattr(test, name) for name in ('branch', 'control', 'target')
                    if isinstance(getattr(test, name, None), str)}
        self.report['results'].append({
            'test': test.id(), 'status': status,
            'at': datetime.now(timezone.utc).isoformat(),
            'seconds': round(time.monotonic() - self.started.get(test.id(), time.monotonic()), 3),
            **({'evidence': evidence} if evidence else {}),
            **({'diagnostic': diagnostic} if diagnostic else {})})
        self.save()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.receipt(test, 'PASS')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.receipt(test, 'FAIL', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.receipt(test, 'ERROR', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.receipt(test, 'BLOCKED', reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.receipt(subtest, 'PASS' if err is None else 'FAIL',
                     None if err is None else self._exc_info_to_string(err, test))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'scratch' / 'live-probes')
    parser.add_argument('--test', action='append', help='Exact converted test/class to recheck after repair')
    args = parser.parse_args()
    folder = args.output / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    path = folder / 'report.json'
    report = {'started_at': datetime.now(timezone.utc).isoformat(),
              'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'working_tree_diff': subprocess.check_output(['git', 'diff', '--stat'], cwd=ROOT, text=True),
              'scope': 'wired live boundary probes; full assertion parity not established',
              'full_e2e_passed': False, 'complete': False, 'results': []}
    os.environ['PIPELINE_EVIDENCE_LIVE'] = '1'
    from test_pipeline_failure_master import EvidenceFailureMatrix, live_context
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceFailureMatrix))
    for name in MODULES:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    def tests(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                yield from tests(item)
            else:
                yield item.id()
    report['planned_tests'] = list(tests(suite))
    if args.test:
        selected = unittest.TestSuite()
        for name in args.test:
            if not any(identity == name or identity.startswith(name + '.')
                       for identity in report['planned_tests']):
                parser.error('Test is outside the wired live manifest: ' + name)
            selected.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
        suite = selected
        report['planned_tests'] = list(tests(suite))
        report['scope'] = 'selected converted checks after repair; full suite verdict remains in source campaign'
    report['source_files'] = {
        name: hashlib.sha256((ROOT / 'scripts' / (name + '.py')).read_bytes()).hexdigest()
        for name in {*[item.split('.')[0] for item in MODULES],
                     'test_pipeline_failure_master', 'run_pipeline_live_probes'}}
    runner = unittest.TextTestRunner(verbosity=2, failfast=False,
        resultclass=lambda *a, **kw: Receipts(*a, **kw, report=report, path=path))
    print('Live receipts: ' + str(path), flush=True)
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    result = runner.run(suite)
    if live_context.cache_info().currsize:
        from pipeline_evidence import source_revision
        context = live_context()
        report['live_source'] = {'repo': context['repo'], 'issue': context['issue_number'],
                                 'source_revision': source_revision(context)}
    observed = {entry['test'] for entry in report['results']}
    for identity in report['planned_tests']:
        if identity not in observed:
            children = [entry for entry in report['results']
                        if entry['test'].startswith(identity + ' (')]
            report['results'].append({'test': identity,
                'status': 'FAIL' if any(entry['status'] == 'FAIL' for entry in children) else 'NOT_RUN',
                'diagnostic': 'Inspect recorded subtest or fixture errors in this report.'})
    report.update(complete=True, tests_run=result.testsRun,
                  passed=result.wasSuccessful() and not result.skipped)
    result.save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
