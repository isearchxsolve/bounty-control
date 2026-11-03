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


class FullPipelineDefault(unittest.TestCase):
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
