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
    'test_commercial_context_live',
    'test_payment_gates',
    'test_commercial_context',
    'test_live_probe_receipts',
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


def source_fingerprints():
    # Include production dependencies, not just the test files. A legacy report
    # with narrower provenance cannot certify that a repaired gate was exercised.
    return {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'scripts').glob('*.py'))}


def reusable_methods(report, current_sources):
    if not report.get('source_files') or report['source_files'] != current_sources:
        return set()
    receipts = report.get('results', [])
    return {r['test'] for r in receipts if r.get('status') == 'PASS' and ' (' not in r['test']
            and all(c.get('status') == 'PASS' for c in receipts
                    if c['test'].startswith(r['test'] + ' ('))}


def archive_receipts(report, methods, reason):
    """Superseded observations remain evidence, including every failed attempt."""
    holders = {phase + ' (' + '.'.join(name.split('.')[:-1]) + ')'
               for name in methods for phase in ('setUpClass', 'tearDownClass')}
    holders.update(phase + ' (' + name.split('.')[0] + ')'
                   for name in methods for phase in ('setUpModule', 'tearDownModule'))
    removed = [r for r in report.get('results', [])
               if r['test'].split(' (')[0] in methods or r['test'] in holders]
    if removed:
        report.setdefault('receipt_history', []).append({'at': datetime.now(timezone.utc).isoformat(),
            'reason': reason, 'source_files': report.get('source_files'), 'results': removed})
        report['results'] = [r for r in report['results'] if r not in removed]


def campaign_passed(report):
    receipts = report.get('results', [])
    observed = {r['test']: r.get('status') for r in receipts}
    return bool(report.get('planned_tests')) and all(
        observed.get(name) == 'PASS' for name in report['planned_tests']) and all(
            r.get('status') == 'PASS' for r in receipts)


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
        # Preserve prior observations even when unittest reports the same identity twice.
        prior = [r for r in self.report['results'] if r['test'] == test.id()]
        if prior:
            self.report.setdefault('superseded_receipts', []).extend(prior)
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
        backup = path.with_name('report-before-resume-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        backup.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
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
    full_plan = list(tests(suite))
    report['planned_tests'] = full_plan
    current_sources = source_fingerprints()
    reusable = reusable_methods(report, current_sources) if args.resume else set()
    resume_reason = 'Retry failed, blocked or incomplete method and all its subtests'
    if args.resume and report.get('source_files') != current_sources:
        resume_reason = 'Source provenance missing or changed; prior observations retained but not current verification'
    if args.resume and report.get('live_source'):
        from pipeline_evidence import source_revision
        try:
            ctx = live_context()
            current_live = {'repo': ctx['repo'], 'issue': ctx['issue_number'],
                            'source_revision': source_revision(ctx)}
        except Exception as exc:
            current_live = None
            report['resume_prerequisite_error'] = str(exc)
        if current_live != report['live_source']:
            reusable = set()
            resume_reason = 'Live source prerequisite changed or unavailable; re-probe instead of fabricating reuse'
    if args.test:
        if args.resume:
            archive_receipts(report, set(full_plan) - reusable, resume_reason)
        selected = unittest.TestSuite()
        for name in args.test:
            if not any(identity == name or identity.startswith(name + '.')
                       for identity in report['planned_tests']):
                parser.error('Test is outside the wired live manifest: ' + name)
            selected.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
        suite = selected
        selected_ids = list(tests(suite))
        # A targeted continuation cannot erase unselected failures from the campaign.
        if not args.resume:
            report['planned_tests'] = selected_ids
        archive_receipts(report, set(selected_ids), 'Explicit selected recheck after repair')
        report['scope'] = 'selected converted checks after repair; full suite verdict remains in source campaign'
    elif args.resume:
        # A passing sibling does not complete a failed method. BLOCKED is unfinished.
        archive_receipts(report, set(full_plan) - reusable, resume_reason)
        def filter_suite(s):
            if isinstance(s, unittest.TestSuite):
                filtered = unittest.TestSuite()
                for sub in s:
                    f = filter_suite(sub)
                    if f and (not isinstance(f, unittest.TestSuite) or f.countTestCases() > 0):
                        filtered.addTest(f)
                return filtered
            else:
                return None if s.id() in reusable else s
        suite = filter_suite(suite)
    report['executed_plan'] = list(tests(suite))
    report['reused_methods'] = sorted(reusable - set(report['executed_plan']))
    report['source_files'] = current_sources
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
    all_passed = campaign_passed(report)
    report.update(complete=True, tests_run=len({r['test'].split(' (')[0] for r in report['results']}),
                  passed=all_passed)
    result.save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
