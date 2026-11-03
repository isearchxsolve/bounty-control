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
    'test_pipeline_transport_live',
    'test_pipeline_state_live',
    'test_cline_process',
    'test_claim_lease',
    'test_cline_delivery_ownership',
    'test_non_code_deliverable',
    'test_capacity_gate',
    'test_queue_ordering',
    'test_discovery_heartbeat',
    'test_competition_evidence',
    'test_funding_evidence_required',
    'test_admission_trust',
    'test_by_design_gate',
    'test_advert_escrow',
    'test_repository_intent',
    'test_code_change_class',
    'test_hardness_ordering',
    'test_urgency_ordering',
    'test_liquidity_ordering',
    'test_unbounded_scope',
    'test_preparation_contract',
    'test_competition_linked',
    'test_search_planner',
    'test_planner_attribution',
    'test_dispatch_velocity',
    'test_hydrate_only_path',
    'test_partition_regressions',
    'test_live_defect_regressions',
    'test_discovery_breadth',
    'test_download_patch_submodule',
    'test_cline_entry_door',
    'test_nvidia_router',
    'test_cline_deliverable',
    'test_actions_migration',
    'test_e2e_full_pipeline',
    'test_e2e_door_to_claim_live',
    'test_pipeline_master_runner',
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
        for attempt in range(10):
            try:
                temp.replace(self.path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        try:
            temp.replace(self.path)
        except PermissionError:
            self.path.write_text(temp.read_text(encoding='utf-8'), encoding='utf-8')

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def receipt(self, test, status, diagnostic=None):
        evidence = {name: getattr(test, name) for name in ('branch', 'control', 'target')
                    if isinstance(getattr(test, name, None), str)}
        # Replace prior failed receipt for the same test upon resume after repair (Baba Law 86)
        self.report['results'] = [r for r in self.report['results'] if r['test'] != test.id()]
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
    parser.add_argument('--resume', type=Path, help='Resume from an existing live-probe run directory or report.json')
    args = parser.parse_args()
    if args.resume:
        resume_target = args.resume.resolve()
        if resume_target.is_dir():
            target_json = resume_target / 'report.json'
            target_tmp = resume_target / 'report.tmp'
            path = target_json if target_json.exists() else target_tmp
        else:
            path = resume_target
        report = json.loads(path.read_text(encoding='utf-8'))
        path = path.with_name('report.json')
        report['resumed_at'] = datetime.now(timezone.utc).isoformat()
        report['resumed_source_sha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['scope'] = f"resumed from {resume_target.name} under Baba Law 86; prior completed evidence preserved"
    else:
        folder = args.output / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir(parents=True)
        path = folder / 'report.json'
        report = {'started_at': datetime.now(timezone.utc).isoformat(),
                  'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  'working_tree_diff': subprocess.check_output(['git', 'diff', '--stat'], cwd=ROOT, text=True),
                  'scope': 'wired live boundary probes; full assertion parity not established',
                  'full_e2e_passed': False, 'complete': False, 'results': []}
    os.environ['PIPELINE_EVIDENCE_LIVE'] = '1'
    os.environ['PIPELINE_LEASE_LIVE'] = '1'
    os.environ['PIPELINE_RUNNER_LIVE'] = '1'
    os.environ['PIPELINE_TRANSPORT_LIVE'] = '1'
    os.environ['PIPELINE_DURABLE_LIVE'] = '1'
    from test_pipeline_failure_master import (
        EvidenceFailureMatrix, TransportFailureMatrix, DurableStateFaults, ReleaseFailureMatrix, live_context
    )
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceFailureMatrix))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(TransportFailureMatrix))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(DurableStateFaults))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseFailureMatrix))
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
    elif args.resume:
        # Baba Law 86: Preserve completed passes; re-run only failed/errored checks after repair
        already_done = {entry['test'].split(' (')[0] for entry in report.get('results', [])
                        if entry.get('status') in ('PASS', 'BLOCKED')}
        def filter_suite(s):
            if isinstance(s, unittest.TestSuite):
                filtered = unittest.TestSuite()
                for sub in s:
                    f = filter_suite(sub)
                    if f and (not isinstance(f, unittest.TestSuite) or f.countTestCases() > 0):
                        filtered.addTest(f)
                return filtered
            else:
                return None if s.id() in already_done else s
        suite = filter_suite(suite)
    report['source_files'] = {
        name: hashlib.sha256((ROOT / 'scripts' / (name + '.py')).read_bytes()).hexdigest()
        for name in {*[item.split('.')[0] for item in MODULES],
                     'test_pipeline_failure_master', 'run_pipeline_live_probes', 'live_lease_bindings',
                     'live_transport_bindings', 'live_durable_bindings', 'live_release_bindings'}}
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
    non_blocked = [r for r in report['results'] if r['status'] != 'BLOCKED']
    all_passed = bool(non_blocked) and all(r['status'] == 'PASS' for r in non_blocked)
    report.update(complete=True, tests_run=len({r['test'].split(' (')[0] for r in report['results']}),
                  passed=all_passed)
    result.save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
