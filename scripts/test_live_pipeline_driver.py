"""Exercise the live logger against real Python text streams."""
from pathlib import Path
import json
from contextlib import closing
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest

from actions_github import GitHubError
from live_pipeline_integration import Tee, LiveRun, REQUIRED_CASES, drain_evidence, failure_kind, recorded_cause


class JournalAcceptanceContract(unittest.TestCase):
    def test_old_green_journal_with_missing_new_cases_is_invalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'run.json')
            path.write_text(json.dumps({'target': 'owner/repo', 'control': 'owner/control',
                'events': [], 'end_to_end_passed': True}), encoding='utf-8')
            LiveRun(SimpleNamespace(run_dir=Path(directory), target='owner/repo', control='owner/control', issue=None))
            self.assertFalse(json.loads(path.read_text())['end_to_end_passed'])

    def test_later_phase_failure_revokes_green_even_if_required_cases_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = LiveRun(SimpleNamespace(run_dir=Path(directory), target='owner/repo', control='owner/control', issue=None))
            run.data['events'] = [{'case': name, 'status': 'PASS'} for name in REQUIRED_CASES]
            run.data['end_to_end_passed'] = True
            run.save()
            run.record('OBSERVE', 'FAIL', diagnostic='Later head verification failed')
            self.assertFalse(json.loads(run.path.read_text())['end_to_end_passed'])


class RequiredCaseContract(unittest.TestCase):
    def test_every_case_that_gates_green_is_named_in_the_contract(self):
        # A case silently dropped from REQUIRED_CASES stops gating end_to_end_passed:
        # coverage would never mark it NOT_RUN, so a run missing that evidence reads green.
        self.assertEqual(len(REQUIRED_CASES), len(set(REQUIRED_CASES)), 'Duplicate required case')
        for case in ('ENVIRONMENT', 'LIVE_INTAKE', 'LIVE_MODEL_ADMISSION', 'REAL_PUBLICATION',
                     'ACTIONS_TERMINAL', 'MERGE_AND_RECONCILE_REPLAY',
                     'LIVE_RELEASE_TASK_IDENTITY', 'LIVE_RELEASE_HEAD', 'LIVE_RELEASE_TREE',
                     'LIVE_RELEASE_FILE_MANIFEST', 'LIVE_RELEASE_NATIVE_RECEIPTS_MISSING',
                     'LIVE_RELEASE_REGRESSION_NEVER_RED', 'LIVE_RELEASE_REGRESSION_NOT_GREEN'):
            self.assertIn(case, REQUIRED_CASES, f'{case} no longer gates green')

    def test_a_run_missing_any_required_case_is_not_green(self):
        with tempfile.TemporaryDirectory() as directory:
            run = LiveRun(SimpleNamespace(run_dir=Path(directory), target='owner/repo',
                                          control='owner/control', issue=None))
            run.data['events'] = [{'case': name, 'status': 'PASS'} for name in REQUIRED_CASES]
            run.save()
            self.assertTrue(all(status == 'PASS' for status in run.data['coverage'].values()))
            for missing in REQUIRED_CASES:
                run.data['events'] = [{'case': name, 'status': 'PASS'}
                                      for name in REQUIRED_CASES if name != missing]
                run.save()
                self.assertEqual(run.data['coverage'][missing], 'NOT_RUN')
                self.assertFalse(run.data['end_to_end_passed'],
                                 f'A run missing {missing} still reported green')


class DrainArtifactContract(unittest.TestCase):
    def test_census_older_than_the_run_is_rejected_as_inherited_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = {'run_started_at': '2026-11-03T01:00:00Z'}
            stale = {'door_reason': 'HYDRATE_ONLY', 'at': '2026-11-02T23:00:00+00:00'}
            (folder / 'census.jsonl').write_text(json.dumps(stale), encoding='utf-8')
            with closing(sqlite3.connect(folder / 'agent-queue.sqlite3')) as con:
                con.execute('CREATE TABLE decisions(disposition TEXT, at TEXT)')
                con.commit()
            with self.assertRaisesRegex(AssertionError, 'inherited stale cache'):
                drain_evidence(folder, run)

    def test_fresh_workflow_cannot_hide_wrong_queue_or_unexamined_cached_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = {'run_started_at': '2026-11-03T01:00:00Z'}
            census = {'door_reason': 'HYDRATE_ONLY', 'at': '2026-11-03T01:01:00+00:00'}
            with closing(sqlite3.connect(folder / 'agent-queue.sqlite3')) as con:
                con.execute('CREATE TABLE decisions(disposition TEXT, at TEXT)')
                con.execute('INSERT INTO decisions VALUES(?,?)', ('capacity_wait', '2026-11-02T12:00:00+00:00'))
                con.commit()
            (folder / 'census.jsonl').write_text(json.dumps(census), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'unexamined'):
                drain_evidence(folder, run)
            with closing(sqlite3.connect(folder / 'agent-queue.sqlite3')) as con:
                con.execute('UPDATE decisions SET at=?', (census['at'],))
                con.commit()
            self.assertEqual(drain_evidence(folder, run), census)
            census['door_reason'] = 'NO_ROWS'
            (folder / 'census.jsonl').write_text(json.dumps(census), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'agent-queue path'):
                drain_evidence(folder, run)


class FailureSurface(unittest.TestCase):
    """The live surface: every real run failure is named, or the case fails."""

    def drive(self, rows, runs=(), jobs=None):
        """Run failures() against an injected ledger and Actions; nothing remote."""
        args = SimpleNamespace(run_dir=Path('/runs/x'), target='owner/repo',
                               control='owner/control', issue=None)
        api = SimpleNamespace(
            workflow_runs=lambda repo, status: list(runs),
            api=lambda endpoint, method='GET', data=None: (
                {'jobs': jobs} if '/jobs' in endpoint else {}))
        store = SimpleNamespace(records=lambda: iter(rows))
        run = LiveRun(args, api=api, store=store)
        assert isinstance(run.folder, Path)
        return run

    def test_a_failure_with_a_stated_cause_is_recorded_and_does_not_fail_the_case(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.drive([{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER',
                               'repo': 'owner/repo', 'issue_number': 7,
                               'dispatch_id': 'b' * 32, 'finished_at': '2026-11-01T00:00:00Z',
                               'diagnostic': 'test suite failed: 2 assertions'}])
            run.failures()
            receipt = json.loads(run.folder.joinpath('failures.json').read_text())
            self.assertEqual(len(receipt), 1)
            self.assertEqual(receipt[0]['kind'], 'failure')
            self.assertEqual(receipt[0]['stage'], 'engineer')
            self.assertEqual(receipt[0]['cause'], 'test suite failed: 2 assertions')
            self.assertEqual(receipt[0]['witness'], 'ledger')
            self.assertEqual(run.data['coverage']['LIVE_FAILURE_SURFACE'], 'PASS')
            event = run.data['events'][-1]
            self.assertEqual((event['case'], event['status']), ('LIVE_FAILURE_SURFACE', 'PASS'))
            self.assertEqual((event['failures'], event['refusals']), (1, 0))

    def test_a_failure_with_no_stated_cause_fails_the_case_as_unexplained(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.drive([{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER'}])
            with self.assertRaisesRegex(AssertionError, 'unexplained failure'):
                run.failures()
            self.assertTrue(run.folder.joinpath('failures.md').exists())
            event = run.data['events'][-1]
            self.assertEqual((event['case'], event['status']), ('LIVE_FAILURE_SURFACE', 'FAIL'))
            self.assertEqual(event['unexplained'], ['a' * 32])
            self.assertFalse(run.data['end_to_end_passed'])

    def test_a_failure_whose_stage_cannot_be_named_fails_the_case_as_unclassified(self):
        # A failed Actions run whose jobs cannot be read still carries no stage, so the case
        # must fail: a failure nobody can locate is the class that stayed invisible.
        with tempfile.TemporaryDirectory() as directory:
            runs = [{'id': 42, 'conclusion': 'failure', 'display_title': 'engine2 ' + 'b' * 32,
                     'html_url': 'https://example.test/run/42', 'updated_at': '2026-11-01T00:00:00Z'}]
            args = SimpleNamespace(run_dir=Path('/runs/x'), target='owner/repo',
                                   control='owner/control', issue=None)

            def unreadable_jobs(endpoint, method='GET', data=None):
                raise GitHubError('jobs endpoint unavailable')

            api = SimpleNamespace(workflow_runs=lambda repo, status: list(runs), api=unreadable_jobs)
            run = LiveRun(args, api=api, store=SimpleNamespace(records=lambda: iter([])))
            with self.assertRaisesRegex(AssertionError, 'unclassified failure'):
                run.failures()

    def test_a_failed_run_with_only_skipped_jobs_names_them(self):
        # A cancelled run marks its jobs skipped, not failed. The stage must still be named
        # rather than collapsing to 'unclassified', which would fail the case on evidence.
        with tempfile.TemporaryDirectory() as directory:
            runs = [{'id': 42, 'conclusion': 'failure', 'display_title': 'engine2 ' + 'b' * 32,
                     'html_url': 'https://example.test/run/42', 'updated_at': '2026-11-01T00:00:00Z'}]
            jobs = [{'name': 'engineer', 'conclusion': 'skipped'},
                    {'name': 'finish', 'conclusion': 'success'}]
            run = self.drive([], runs=runs, jobs=jobs)
            entries, violations = run.surface_entries()
            self.assertEqual(entries[0]['stage'], 'no failed job; skipped: engineer')
            self.assertEqual(violations, [])

    def test_a_refusal_is_counted_apart_and_never_fails_the_case(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.drive([{'task_id': 'a' * 32, 'status': 'REJECTED_NEVER_RED',
                               'reason': 'positive control stayed green', 'finished_at': '2026-11-01T00:00:00Z'}])
            run.failures()
            receipt = json.loads(run.folder.joinpath('failures.json').read_text())
            self.assertEqual(receipt[0]['kind'], 'refusal')
            self.assertEqual(run.data['events'][-1]['refusals'], 1)
            self.assertEqual(run.data['events'][-1]['failures'], 0)

    def test_a_failed_actions_run_without_a_ledger_row_is_surfaced(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = [{'id': 42, 'conclusion': 'failure', 'display_title': 'engine2 ' + 'b' * 32,
                     'html_url': 'https://example.test/run/42', 'updated_at': '2026-11-01T00:00:00Z'}]
            jobs = [{'name': 'engineer', 'conclusion': 'failure'}]
            run = self.drive([], runs=runs, jobs=jobs)
            entries, violations = run.surface_entries()
            self.assertEqual([e['witness'] for e in entries], ['actions'])
            self.assertEqual(entries[0]['stage'], 'engineer')
            self.assertEqual(entries[0]['dispatch_id'], 'b' * 32)
            self.assertIn('run concluded failure', entries[0]['cause'])
            self.assertEqual(violations, [])

    def test_a_failed_run_whose_dispatch_already_has_a_ledger_row_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            dispatch = 'b' * 32
            runs = [{'id': 42, 'conclusion': 'failure', 'display_title': 'engine2 ' + dispatch,
                     'html_url': 'https://example.test/run/42', 'updated_at': '2026-11-01T00:00:00Z'}]
            jobs = [{'name': 'engineer', 'conclusion': 'failure'}]
            run = self.drive([{'task_id': 'a' * 32, 'status': 'DELIVERED', 'dispatch_id': dispatch}],
                            runs=runs, jobs=jobs)
            entries, _ = run.surface_entries()
            self.assertEqual(entries, [])

    def test_an_unreadable_witness_fails_the_case_with_its_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(run_dir=Path('/runs/x'), target='owner/repo',
                                   control='owner/control', issue=None)

            def boom(*args, **kwargs):
                raise GitHubError('ledger unavailable')

            run = LiveRun(args, api=SimpleNamespace(workflow_runs=lambda r, s: [], api=boom),
                          store=SimpleNamespace(records=boom))
            with self.assertRaisesRegex(AssertionError, 'Durable ledger unreadable'):
                run.failures()
            args2 = SimpleNamespace(run_dir=Path('/runs/y'), target='owner/repo',
                                    control='owner/control', issue=None)

            def boom_runs(repo, status):
                raise GitHubError('actions unavailable')

            run2 = LiveRun(args2, api=SimpleNamespace(workflow_runs=boom_runs, api=lambda *a, **k: {}),
                           store=SimpleNamespace(records=lambda: iter([])))
            with self.assertRaisesRegex(AssertionError, 'Actions runs unreadable'):
                run2.failures()

    def test_the_failure_surface_case_gates_green(self):
        self.assertIn('LIVE_FAILURE_SURFACE', REQUIRED_CASES, 'Failure surface no longer gates green')


class FailureSurfaceHelpers(unittest.TestCase):
    def test_failure_kind_classifies_on_the_status_token_alone(self):
        self.assertEqual(failure_kind('FAILED_ENGINEER'), ('failure', 'engineer'))
        self.assertEqual(failure_kind('REJECTED_OUT_OF_SCOPE'), ('refusal', 'out_of_scope'))
        self.assertEqual(failure_kind('DELIVERED'), (None, None))
        self.assertEqual(failure_kind(None), (None, None))

    def test_recorded_cause_returns_the_records_own_cause_or_none(self):
        self.assertEqual(recorded_cause({'diagnostic': 'boom'}), 'boom')
        self.assertEqual(recorded_cause({'reason': 'owner revoked'}), 'owner revoked')
        self.assertEqual(recorded_cause({'detail': 'disk full'}), 'disk full')
        self.assertEqual(recorded_cause({'error': '401'}), '401')
        self.assertIsNone(recorded_cause({'status': 'FAILED_MISSING_RECEIPT'}))

    def test_recorded_cause_reads_history_the_lane_actually_writes(self):
        # actions_delivery.finish() appends prior outcomes under 'failures', not 'history'.
        row = {'status': 'FAILED_MISSING_RECEIPT',
               'failures': [{'run_url': 'https://example.test/1', 'reason': 'no receipt'},
                            {'run_url': 'https://example.test/2', 'reason': 'latest cause'}]}
        self.assertEqual(recorded_cause(row), 'latest cause')

    def test_recorded_cause_reads_a_plain_string_history_entry(self):
        row = {'status': 'FAILED_ENGINEER', 'history': ['cached refusal', 'latest refusal']}
        self.assertEqual(recorded_cause(row), 'latest refusal')

    def test_recorded_cause_reads_no_cause_the_row_does_not_carry(self):
        self.assertIsNone(recorded_cause({'status': 'FAILED_MISSING_RECEIPT', 'failures': []}))
        self.assertIsNone(recorded_cause({'status': 'FAILED_ENGINEER', 'diagnostic': '   '}))


class LiveLoggerContract(unittest.TestCase):
    def test_production_stdout_configuration_and_evidence_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            primary, evidence = Path(directory, 'stdout'), Path(directory, 'evidence')
            with primary.open('w', encoding='ascii') as stream, evidence.open('w', encoding='utf-8') as log:
                tee = Tee(stream, log)
                tee.reconfigure(encoding='utf-8', errors='replace')
                self.assertEqual(tee.encoding, 'utf-8')
                self.assertEqual(tee.fileno(), stream.fileno())
                tee.write('Live receipt ₹ 日本語\n')
                tee.flush()
            self.assertEqual(primary.read_bytes(), evidence.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
