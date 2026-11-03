"""Phase C reporting contract: repeat sightings vs unique causes, and BLOCKED vs FAIL.

docs/LIVE-PROBE-MASTER-PLAN.md section 6 requires the consolidated report to separate repeat
sightings from unique root causes, and to distinguish a blocked prerequisite from an assertion
that was exercised and failed. Measured 2026-11-03 on run 41618838277: 162 failure entries
carried only 40 unique causes, because 122 Actions rows stated nothing but which job failed.
"""
from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest

from live_pipeline_integration import (Blocked, CampaignIncomplete, LiveRun, blocker_of,
                                      normalized_fingerprint, run_only_cause)


class Drive:
    def drive(self, directory, rows, runs=(), jobs=()):
        args = SimpleNamespace(run_dir=Path(directory), target='owner/repo',
                               control='owner/control', issue=None)
        api = SimpleNamespace(
            workflow_runs=lambda repo, status: list(runs),
            api=lambda endpoint, method='GET', data=None: (
                {'jobs': jobs} if '/jobs' in endpoint else {}))
        store = SimpleNamespace(records=lambda: iter(rows))
        return LiveRun(args, api=api, store=store)


class CauseGrouping(unittest.TestCase):
    def report(self, directory, run):
        run.failures()
        return (json.loads(run.folder.joinpath('failures.json').read_text()),
                json.loads(run.folder.joinpath('causes.json').read_text()))

    def test_one_cause_recorded_twice_is_one_cause_not_two_defects(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER', 'repo': 'owner/repo',
                     'issue_number': 7, 'dispatch_id': 'b' * 32,
                     'finished_at': '2026-11-01T00:00:00Z',
                     'diagnostic': 'native verification failed at 41577249045'},
                    {'task_id': 'c' * 32, 'status': 'FAILED_ENGINEER', 'repo': 'owner/repo',
                     'issue_number': 8, 'dispatch_id': 'd' * 32,
                     'finished_at': '2026-11-02T00:00:00Z',
                     'diagnostic': 'native verification failed at 41590239151'}]
            run = Drive().drive(directory, rows)
            entries, causes = self.report(directory, run)
            self.assertEqual(len(entries), 2)
            self.assertEqual(len(causes), 1)
            self.assertEqual(causes[0]['sightings'], 2)
            self.assertEqual(sorted(causes[0]['identities']), ['a' * 32, 'c' * 32])
            event = run.data['events'][-1]
            self.assertEqual(event['repeat_sightings'], 1)
            self.assertEqual(event['unique_causes'], 1)

    def test_distinct_causes_stay_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER',
                     'finished_at': '2026-11-01T00:00:00Z', 'diagnostic': 'test suite failed'},
                    {'task_id': 'c' * 32, 'status': 'FAILED_PUBLISH',
                     'finished_at': '2026-11-01T00:00:00Z', 'diagnostic': 'gh: Not Found (HTTP 404)'}]
            run = Drive().drive(directory, rows)
            _, causes = self.report(directory, run)
            self.assertEqual(len(causes), 2)

    def test_actions_rows_that_name_only_a_job_are_grouped_apart_from_stated_causes(self):
        with tempfile.TemporaryDirectory() as directory:
            run_with = lambda status: {'id': 9, 'status': 'completed', 'conclusion': 'failure',
                                      'display_title': 'bounty ' + 'e' * 32 + ' owner/repo #1',
                                      'html_url': 'u/9', 'created_at': '2026-11-03T00:00:00Z',
                                      'updated_at': '2026-11-03T00:01:00Z'}
            jobs = [{'name': 'engineer', 'conclusion': 'failure'}]
            rows = [{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER',
                     'finished_at': '2026-11-01T00:00:00Z', 'diagnostic': 'a real diagnostic'}]
            run = Drive().drive(directory, rows, runs=[run_with('failure')], jobs=jobs)
            entries, causes = self.report(directory, run)
            jobonly = [e for e in entries if run_only_cause(e['cause'])]
            self.assertEqual(len(jobonly), 1)
            fingerprints = [c['fingerprint'] for c in causes]
            self.assertIn('Actions run concluded without a stated cause; only the failing job '
                          'is known: engineer', fingerprints)
            self.assertIn(normalized_fingerprint('a real diagnostic'), fingerprints)

    def test_a_superseded_failure_is_historical_not_active(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'task_id': 'a' * 32, 'status': 'DELIVERED',
                     'finished_at': '2026-11-02T00:00:00Z', 'diagnostic': None},
                    {'task_id': 'b' * 32, 'status': 'FAILED_ENGINEER',
                     'finished_at': '2026-11-02T00:00:00Z', 'diagnostic': 'still failing'}]
            run = Drive().drive(directory, rows)
            entries, _ = self.report(directory, run)
            self.assertEqual([e['active'] for e in entries], [True])

    def test_the_receipt_keeps_its_per_sighting_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER',
                     'finished_at': '2026-11-01T00:00:00Z', 'diagnostic': 'x'}]
            run = Drive().drive(directory, rows)
            entries, causes = self.report(directory, run)
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(causes, list))


class FingerprintFidelity(unittest.TestCase):
    def test_a_shared_head_does_not_merge_different_causes(self):
        head = ('Cline deliverable invalid at /tmp/fleet-artifacts/delivery-supervisor/'
                + 'a' * 32 + '.preparation.json: action=incomplete: ')
        one = head + 'the preparation report is missing the diff it claims'
        two = head + 'the preparation report names a file it never wrote'
        self.assertNotEqual(normalized_fingerprint(one), normalized_fingerprint(two))

    def test_the_distinguishing_tail_survives(self):
        long = 'prefix ' * 60 + 'distinctive-tail-marker'
        self.assertIn('distinctive-tail-marker', normalized_fingerprint(long))

    def test_task_identity_and_numbers_do_not_split_one_cause(self):
        a = 'native verification failed at run 41577249045 for ' + 'a' * 32
        b = 'native verification failed at run 41590239151 for ' + 'b' * 32
        self.assertEqual(normalized_fingerprint(a), normalized_fingerprint(b))


class BlockedPrerequisite(unittest.TestCase):
    def test_a_named_missing_prerequisite_is_blocked_not_failed(self):
        self.assertEqual(blocker_of('Cline preparation failed: error: No Token Harbor key is '
                                    'currently ready.'), 'No model gateway key is configured and ready')
        self.assertIn('allowance', blocker_of('TokenHarbor router HTTP 429'))
        self.assertIsNone(blocker_of('test suite failed: 2 assertions'))

    def test_blocked_entries_carry_their_prerequisite_and_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'task_id': 'a' * 32, 'status': 'FAILED_ENGINEER',
                     'finished_at': '2026-11-01T00:00:00Z',
                     'diagnostic': 'TokenHarbor router HTTP 429: you have used this allowance'}]
            run = Drive().drive(directory, rows)
            run.failures()
            causes = json.loads(run.folder.joinpath('causes.json').read_text())
            self.assertEqual(causes[0]['outcome'], 'BLOCKED')
            self.assertTrue(causes[0]['prerequisite'])
            event = run.data['events'][-1]
            self.assertEqual(event['by_outcome'], {'BLOCKED': 1})
            self.assertEqual(event['blocked_causes'], 1)
            # A blocked prerequisite does not fail the surface case itself.
            self.assertEqual(run.data['coverage']['LIVE_FAILURE_SURFACE'], 'PASS')

    def test_blocked_coverage_stops_the_campaign_being_green(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Drive().drive(directory, [])
            run.record('MERGE_AND_RECONCILE_REPLAY', 'BLOCKED',
                       prerequisite='--merge-fixture was not requested')
            self.assertEqual(run.data['coverage']['MERGE_AND_RECONCILE_REPLAY'], 'BLOCKED')
            self.assertFalse(run.data['end_to_end_passed'])


class ExitAccounting(unittest.TestCase):
    def test_a_deterministic_stop_is_not_reported_as_a_timeout(self):
        self.assertTrue(issubclass(CampaignIncomplete, RuntimeError))
        self.assertFalse(issubclass(CampaignIncomplete, TimeoutError))
        self.assertTrue(issubclass(Blocked, RuntimeError))


if __name__ == '__main__':
    unittest.main(verbosity=2)
