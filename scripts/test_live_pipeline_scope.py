"""Contract regression: an unfiltered master run starts the whole pipeline."""
from types import SimpleNamespace
import base64
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from live_pipeline_integration import LiveRun, retained_admissions
from actions_github import GitHubError
from actions_github import task_id
from pipeline_evidence import bind_proof
import sovereign_discovery


class FullPipelineDefault(unittest.TestCase):
    def test_full_pipeline_surfaces_failures_even_when_intake_fails(self):
        class API:
            def api(self, endpoint):
                if endpoint == 'user':
                    return {'login': 'owner'}
                if endpoint == 'repos/owner/control':
                    return {'default_branch': 'main'}
                return {'sha': 'a' * 40}
        class StopAtEntry(Exception):
            pass
        with tempfile.TemporaryDirectory() as folder:
            run = LiveRun.__new__(LiveRun)
            run.args = SimpleNamespace(issue=None, model_timeout=60)
            run.data, run.api, run.control, run.folder = {}, API(), 'owner/control', Path(folder)
            run.command = lambda *args, **kwargs: 'a' * 40
            run.save = lambda: None
            events = []
            run.record = lambda case, status, **evidence: events.append((case, status))
            def broken_intake():
                raise AssertionError('actual intake failed')
            run.intake = broken_intake
            run.failures = lambda: events.append(('LIVE_FAILURE_SURFACE', 'PASS'))
            with patch.object(sovereign_discovery, 'discover', side_effect=StopAtEntry):
                with self.assertRaises(StopAtEntry):
                    run.pipeline()
            self.assertIn(('LIVE_INTAKE', 'FAIL'), events)
            self.assertIn(('LIVE_FAILURE_SURFACE', 'PASS'), events)

    def test_empty_issue_does_not_enter_fixture_or_single_issue_path(self):
        run = LiveRun.__new__(LiveRun)
        run.args = SimpleNamespace(issue=None)
        run.data = {}
        entered = []
        def pipeline():
            entered.append('production-entry-door')
            return 'full-pipeline'
        run.pipeline = pipeline
        self.assertEqual(run.run(), 'full-pipeline')
        self.assertEqual(entered, ['production-entry-door'])

    def test_interrupted_entry_reuses_only_current_source_bound_admissions(self):
        current = {'repo': 'owner/repo', 'issue_number': 7,
                   'issue': {'number': 7, 'state': 'open'}, 'comments': [],
                   'complete_comments': True, 'repository': {'archived': False}}
        row = {'repo': 'owner/repo', 'issue': 7, 'sovereign_admission': True,
               'admission': bind_proof({'lane': 'founder'}, current),
               'competition': {'blocking': False, 'verified': True}}
        class API:
            def __init__(self, source):
                self.source = source
            def issue_context(self, repo, number):
                return self.source
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'agent-queue.sqlite3'
            with contextlib.closing(sqlite3.connect(database)) as con, con:
                con.execute('CREATE TABLE decisions(task_id TEXT,payload TEXT,disposition TEXT)')
                con.execute('INSERT INTO decisions VALUES(?,?,?)',
                            (task_id('owner/repo', 7), json.dumps(row), 'capacity_wait'))
            self.assertEqual(retained_admissions(folder, API(current)), [task_id('owner/repo', 7)])
            changed = {**current, 'comments': [{'id': 1, 'body': 'changed'}]}
            self.assertEqual(retained_admissions(folder, API(changed)), [])


class DiscoveryReceiptTests(unittest.TestCase):
    """Intake causes a discovery run instead of sampling a throttled cron."""

    def harness(self, folder, runs, *, intake_max_age_minutes=90):
        class API:
            def __init__(self):
                self.runs = runs
            def api(self, endpoint, method='GET', body=None):
                if '/runs' not in endpoint:
                    raise GitHubError('unexpected endpoint ' + endpoint)
                status = endpoint.split('status=')[1].split('&')[0] if 'status=' in endpoint else None
                return {'workflow_runs': [r for r in self.runs if status is None or r['status'] == status]}
        run = LiveRun.__new__(LiveRun)
        run.args = SimpleNamespace(intake_max_age_minutes=intake_max_age_minutes)
        run.data, run.api, run.control, run.folder = {}, API(), 'owner/control', Path(folder)
        run.save = lambda: None
        events, commands = [], []
        run.record = lambda case, status, **evidence: events.append((case, status, evidence))
        run.command = lambda argv, **kwargs: commands.append(argv) or 'dispatched'
        return run, events, commands

    @staticmethod
    def stamp(minutes_ago):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace('+00:00', 'Z')

    def test_stale_completed_run_dispatches_instead_of_failing_on_a_throttled_cron(self):
        stale = {'id': 1, 'status': 'completed', 'conclusion': 'success',
                 'event': 'workflow_dispatch', 'html_url': 'u/1', 'created_at': self.stamp(400),
                 'updated_at': self.stamp(395)}
        fresh = {'id': 2, 'status': 'completed', 'conclusion': 'success',
                 'event': 'workflow_dispatch', 'html_url': 'u/2', 'created_at': self.stamp(4),
                 'updated_at': self.stamp(3)}
        with tempfile.TemporaryDirectory() as folder:
            run, events, commands = self.harness(folder, [stale])
            # The dispatch lands between the first poll and the next one.
            original_command = run.command
            def land(argv, **kwargs):
                original_command(argv, **kwargs)
                run.api.runs.append(fresh)
                return 'dispatched'
            run.command = land
            self.assertEqual(run.ensure_discovery_receipt()['id'], 2)
            self.assertEqual(len(commands), 1)
            self.assertIn('bounty-discovery.yml', commands[0])
            self.assertEqual(events[0][0], 'LIVE_DISCOVERY_DISPATCH')
            self.assertEqual(events[0][2]['previous_run'], 'u/1')
            self.assertGreater(events[0][2]['previous_age_minutes'], 90)

    def test_fresh_completed_run_is_used_without_dispatching(self):
        fresh = {'id': 3, 'status': 'completed', 'conclusion': 'success',
                 'event': 'schedule', 'html_url': 'u/3', 'created_at': self.stamp(9),
                 'updated_at': self.stamp(8)}
        with tempfile.TemporaryDirectory() as folder:
            run, events, commands = self.harness(folder, [fresh])
            self.assertEqual(run.ensure_discovery_receipt()['id'], 3)
            self.assertEqual(commands, [])
            self.assertEqual(events, [])

    def test_in_flight_run_is_waited_for_not_doubled(self):
        stale = {'id': 1, 'status': 'completed', 'conclusion': 'success',
                 'event': 'workflow_dispatch', 'html_url': 'u/1', 'created_at': self.stamp(400),
                 'updated_at': self.stamp(395)}
        running = {'id': 4, 'status': 'in_progress', 'conclusion': None,
                   'event': 'workflow_dispatch', 'html_url': 'u/4', 'created_at': self.stamp(80),
                   'updated_at': self.stamp(79)}
        clock = iter(range(0, 10_000, 30))
        with tempfile.TemporaryDirectory() as folder, \
                patch('live_pipeline_integration.time.sleep'), \
                patch('live_pipeline_integration.time.monotonic', lambda: next(clock)):
            run, events, commands = self.harness(folder, [stale, running], intake_max_age_minutes=1)
            with self.assertRaises(AssertionError) as caught:
                run.ensure_discovery_receipt()
            # Never doubles a run the production concurrency group would queue behind.
            self.assertEqual(commands, [])
            message = str(caught.exception)
            self.assertIn('u/4', message)
            self.assertIn('in_progress', message)
            self.assertIn('Cancel or repair that run', message)

    def test_cadence_reports_the_observed_schedule_interval(self):
        runs = [{'event': 'schedule', 'created_at': self.stamp(7 * 60 * n), 'updated_at': self.stamp(7 * 60 * n)}
                for n in (0, 1, 2)]
        with tempfile.TemporaryDirectory() as folder:
            run, _, _ = self.harness(folder, runs)
            cadence = run.discovery_cadence()
            self.assertEqual(cadence['scheduled_runs_sampled'], 3)
            self.assertAlmostEqual(cadence['observed_interval_hours'], 7.0, places=1)


class ProgressReceiptTests(unittest.TestCase):
    def test_status_receipt_is_throttled_and_excludes_diagnostics_and_task_bodies(self):
        class API:
            def __init__(self):
                self.written = []

            def api(self, endpoint, method='GET', body=None):
                if method == 'GET':
                    raise GitHubError('404 missing progress receipt')
                self.written.append((endpoint, body))
                return {'content': {'sha': 'actual-contents-response-sha'}}

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'LIVE_PIPELINE_PROGRESS': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}):
            api = API()
            run = LiveRun(SimpleNamespace(run_dir=Path(folder), issue=None,
                          target='owner/original', control='owner/control'), api=api)
            run.data['private_prompt'] = 'DO_NOT_TRANSMIT'
            run.record('PIPELINE_ENTRY', 'PENDING', diagnostic='DO_NOT_TRANSMIT')
            run.record('PIPELINE_ENTRY', 'PENDING', diagnostic='DO_NOT_TRANSMIT')
            self.assertEqual(len(api.written), 1)
            run.record('PIPELINE_MEMBER', 'FAIL', diagnostic='DO_NOT_TRANSMIT')
            self.assertEqual(len(api.written), 2)
            run.publish_progress(force=True)
            self.assertEqual(len(api.written), 3)
            endpoint, body = api.written[-1]
            self.assertTrue(endpoint.endswith('/contents/live-integration/123-2.json'))
            self.assertEqual(body['branch'], 'bounty-control')
            self.assertEqual(body['sha'], 'actual-contents-response-sha')
            raw = base64.b64decode(body['content']).decode()
            receipt = json.loads(raw)
            self.assertNotIn('DO_NOT_TRANSMIT', raw)
            self.assertFalse(receipt['end_to_end_passed'])
            self.assertEqual(receipt['events'][-1]['status'], 'FAIL')

    def test_observability_failure_preserves_the_actual_failed_case(self):
        class API:
            def api(self, *args):
                raise GitHubError('403 unavailable')

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'LIVE_PIPELINE_PROGRESS': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}):
            run = LiveRun(SimpleNamespace(run_dir=Path(folder), issue=None,
                          target='owner/original', control='owner/control'), api=API())
            run.record('LIVE_INTAKE', 'FAIL')
            self.assertEqual(run.data['coverage']['LIVE_INTAKE'], 'FAIL')
            self.assertFalse(run.data['end_to_end_passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
