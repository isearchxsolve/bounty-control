"""Check dispatch integrity and screening against genuine saved fleet and GitHub receipts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest

import autonomous_icu_pipeline as dispatcher
import fleet_local_relay as relay
import kaggle_engine_worker as worker
from fleet_recovery_policy import non_engineering_dispatch_reason, recovery_decision


class AuthenticDispatchRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(Path(os.environ['DISPATCH_REGRESSION_FIXTURES']).read_text(encoding='utf-8'))

    def test_actual_archive_and_program_budget_records_are_excluded(self):
        exclusions = {'CodeYHJ/hackernews-daily', 'lessuselesss/bounty-crawl', 'B1nary-Calhoun-Partnership/MPC-Spec'}
        found = set()
        for task in self.fixtures['complete_tasks']:
            if task['repo'] not in exclusions:
                continue
            with self.subTest(repo=task['repo']):
                found.add(task['repo'])
                self.assertTrue(non_engineering_dispatch_reason(task))
                self.assertTrue(worker.is_mirror_dispatch_task(task))
                accepted, _ = dispatcher.verify_genuine_icu_patient(
                    task['title'], task['body'], [], task.get('labels', []), task['repo'],
                    author_assoc='OWNER', author=task.get('author'), live_delivery_mode=True,
                )
                self.assertFalse(accepted)
        self.assertEqual(found, exclusions)

    def test_source_audit_is_not_rejected_only_for_its_daily_review_title(self):
        audit = next(t for t in self.fixtures['complete_tasks'] if t['repo'] == 'up2itnow0822/ClawPowers-Skills' and t['issue_number'] == 126)
        self.assertEqual(non_engineering_dispatch_reason(audit), '')
        self.assertFalse(worker.is_mirror_dispatch_task(audit))

    def test_real_git_status_keeps_the_first_modified_filename(self):
        original = self.fixtures['actual_package_lock'].encode()
        self.assertEqual(hashlib.sha256(original).hexdigest(), self.fixtures['actual_package_lock_sha256'])
        with tempfile.TemporaryDirectory(prefix='git-status-column-regression-') as temporary:
            path = Path(temporary) / 'package-lock.json'
            subprocess.run(['git', 'init', '-q', temporary], check=True, capture_output=True)
            path.write_bytes(original)
            subprocess.run(['git', '-C', temporary, 'add', 'package-lock.json'], check=True, capture_output=True)
            subprocess.run(['git', '-C', temporary, '-c', 'user.name=Regression verifier',
                            '-c', 'user.email=verification@localhost', 'commit', '-qm', 'Record authentic upstream lock bytes'],
                           check=True, capture_output=True)
            # A whitespace-only change gives Git a real unstaged modification.
            # The lockfile remains valid and has the actual reported filename.
            path.write_bytes(original + b'\n')
            for module in (dispatcher, worker):
                output, error, code = module.run_cmd(['git', '-C', temporary, 'status', '--porcelain'], retries=1)
                self.assertEqual(code, 0, error)
                self.assertTrue(output.startswith(' M package-lock.json'), repr(output))
                parsed, files, diagnostic = worker._status_paths_from_porcelain(output)
                self.assertTrue(parsed, diagnostic)
                self.assertEqual(files, ['package-lock.json'])
            _, error = worker._git_checked(['git', '-C', temporary, 'status', '--porcelain'], 10, 'status')
            self.assertIsNone(error)
            _, error = worker._git_checked(['git', '-C', temporary, 'add', '--', *files], 10, 'add verified files')
            self.assertIsNone(error)

    def test_actual_staging_failure_retries_without_resetting_attempts(self):
        task = next(t for t in self.fixtures['complete_tasks'] if t['repo'] == 'up2itnow0822/ClawPowers-Skills' and t['issue_number'] == 126)
        events = self.fixtures['actual_git_staging_events']
        claims = [row for row in events if row['text'].startswith(('CLAIMED ', 'HEARTBEAT '))]
        failures = [row for row in events if row['text'].startswith('FAILED ')]
        self.assertEqual(len(failures), 1)
        self.assertIn("pathspec 'ackage-lock.json'", failures[0]['text'])
        decision = recovery_decision(task, claims, failures, now=max(row['at'] for row in events) + 3600)
        self.assertTrue(decision.allowed, decision.reason)
        self.assertEqual(decision.attempt, 2)

    def test_full_actual_task_survives_dispatch_store_and_fetch(self):
        task = self.fixtures['large_task']
        expected = self.fixtures['large_task_text']
        self.assertGreater(len(expected), 20000)
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), self.fixtures['large_task_text_sha256'])
        old = (relay.DB_PATH, dispatcher.FLEET_DOOR, worker.DOOR)
        with tempfile.TemporaryDirectory(prefix='real-task-integrity-') as temporary:
            relay.DB_PATH = Path(temporary) / 'ledger.sqlite3'
            relay.initialize()
            server = ThreadingHTTPServer(('127.0.0.1', 0), relay.Handler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_address[1]}'
            dispatcher.FLEET_DOOR = worker.DOOR = base
            try:
                self.assertTrue(dispatcher.dispatch_task_to_fleet(task))
                with relay.connection() as database:
                    stored = database.execute('SELECT text FROM fleet_events').fetchone()[0]
                self.assertEqual(stored, expected)
                self.assertEqual(worker.fetch_tasks(), [task])
                bad = [row for row in self.fixtures['authentic_events']
                       if row['channel'] == 'BOUNTY_FLEET_QUEUE_V2' and len(row['text']) == 20000]
                self.assertGreaterEqual(len(bad), 2)
                for row in bad:
                    payload = json.dumps({'body': row['channel'], 'text': row['text']}).encode()
                    request = Request(base + '/say?token=' + relay.TOKEN, data=payload,
                                      headers={'Content-Type': 'application/json'})
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(request, timeout=5)
                    self.assertEqual(caught.exception.code, 400)
                    self.assertEqual(json.load(caught.exception)['err'], 'invalid_fleet_task_json')
                # Preserve a genuine historical corruption in the isolated ledger
                # to verify that readers diagnose it without executing it.
                with relay.connection() as database:
                    database.execute('INSERT INTO fleet_events(channel,text,at) VALUES(?,?,?)',
                                     (bad[0]['channel'], bad[0]['text'], str(bad[0]['at'])))
                worker._invalid_queue_record_digests.clear()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(worker.fetch_tasks(), [task])
                self.assertIn('INVALID_TASK_JSON chars=20000', output.getvalue())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                relay.DB_PATH, dispatcher.FLEET_DOOR, worker.DOOR = old


if __name__ == '__main__':
    unittest.main(verbosity=2)
