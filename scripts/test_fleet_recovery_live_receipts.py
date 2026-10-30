"""Recovery checks against captured live receipts and real isolated SQLite state.

No network responses or successful executions are manufactured by this suite.
The separate master suite is executed unchanged.
"""
import json
import os
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

import autonomous_icu_pipeline as dispatcher
from fleet_recovery_policy import (
    CLAIM_LEASE_SECONDS, MAX_EXECUTION_ATTEMPTS, current_claim,
    event_reference, is_nonsoftware_data_task, is_retryable_failure,
    matching_events, recovery_decision,
)


class LiveReceiptRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ['FLEET_RECOVERY_SNAPSHOT'])
        cls.snapshot = json.loads(path.read_text(encoding='utf-8'))
        cls.claims = cls.snapshot['claims']
        cls.results = cls.snapshot['results']
        cls.tasks = []
        for row in cls.snapshot['queue']:
            try:
                task = json.loads(row['text'])
                if isinstance(task, dict) and task.get('task_id'):
                    cls.tasks.append(task)
            except ValueError:
                pass
        cls.task = next(t for t in cls.tasks if t['repo'] == 'BasedHardware/omi' and t['issue_number'] == 23337)
        cls.claim = matching_events(cls.task, cls.claims)[-1]
        cls.failure = matching_events(cls.task, cls.results)[-1]

    def test_live_temporary_failure_is_retryable(self):
        self.assertTrue(is_retryable_failure(self.failure['text']))
        decision = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 3600)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.attempt, 2)

    def test_live_failure_cooldown(self):
        decision = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 1)
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.retry_at, self.failure['at'])

    def test_live_active_claim_blocks(self):
        # Evaluate the genuine claim at its original time, before its result.
        decision = recovery_decision(self.task, [self.claim], [], self.claim['at'] + 1)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'active claim lease')

    def test_live_abandoned_claim_expires(self):
        decision = recovery_decision(self.task, [self.claim], [], self.claim['at'] + CLAIM_LEASE_SECONDS + 1)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.attempt, 2)

    def test_success_and_existing_pr_never_retry(self):
        seen = 0
        for task in self.tasks:
            rows = matching_events(task, self.results)
            if any(r['text'].startswith('SUCCESS ') or 'PR exists' in r['text'] for r in rows):
                self.assertFalse(recovery_decision(task, self.claims, self.results).allowed)
                seen += 1
        self.assertGreater(seen, 0)

    def test_native_test_and_security_failures_stay_closed(self):
        rows = [r for r in self.results if 'FAILED_NO_TEST_VERIFICATION' in r['text'] or 'Security violation' in r['text']]
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertFalse(is_retryable_failure(row['text']))

    def test_real_repeated_claims_hit_attempt_limit(self):
        seen = 0
        for task in self.tasks:
            claims = [r for r in matching_events(task, self.claims) if r['text'].startswith('CLAIMED ')]
            if len(claims) >= MAX_EXECUTION_ATTEMPTS and not is_nonsoftware_data_task(task):
                decision = recovery_decision(task, claims, [], max(r['at'] for r in claims) + CLAIM_LEASE_SECONDS + 1)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, 'attempt limit reached')
                seen += 1
        self.assertGreater(seen, 0)

    def test_replaying_receipts_is_idempotent(self):
        first = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 3600)
        second = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 3600)
        self.assertEqual(first, second)

    def test_authentic_data_bounties_are_excluded(self):
        task = next(t for t in self.tasks if t['repo'] == 'zkp2p/peer-link' and t['issue_number'] == 159)
        self.assertTrue(is_nonsoftware_data_task(task))
        self.assertFalse(recovery_decision(task, self.claims, self.results).allowed)
        self.assertFalse(dispatcher.verify_genuine_icu_patient(task['title'], task['body'], [], [], task['repo'])[0])

    def test_invalid_receipt_timestamp_fails_closed(self):
        row = dict(self.claim)
        row.pop('at')
        with self.assertRaises(ValueError):
            current_claim(self.task, [row])

    def test_dispatcher_recovers_only_legacy_transient_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'recovery.db')
            dispatcher.init_db(db)
            repo, number = self.task['repo'], self.task['issue_number']
            dispatcher.mark_issue_rejected(repo, number, 'Fleet execution: ' + self.failure['text'], db)
            decision = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 3600)
            dispatcher._mark_fleet_recovery_state(repo, number, self.task['task_id'], decision, True, db)
            with closing(sqlite3.connect(db)) as con, con:
                self.assertEqual(con.execute('SELECT status FROM deliveries').fetchone()[0], 'FLEET_RETRY_WAIT')
            self.assertTrue(dispatcher.is_issue_claimed_or_delivered(repo, number, db)[0])

    def test_security_rejection_cannot_be_overridden_by_retry(self):
        row = next(r for r in self.results if 'Security violation' in r['text'])
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'recovery.db')
            dispatcher.init_db(db)
            repo, number = self.task['repo'], self.task['issue_number']
            dispatcher.mark_issue_rejected(repo, number, row['text'], db)
            decision = recovery_decision(self.task, self.claims, self.results, self.failure['at'] + 3600)
            dispatcher._mark_fleet_recovery_state(repo, number, self.task['task_id'], decision, False, db)
            with closing(sqlite3.connect(db)) as con, con:
                self.assertEqual(con.execute('SELECT status FROM deliveries').fetchone()[0], 'REJECTED_SECURITY')

    def test_real_sqlite_dispatch_reservation_and_retry_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'recovery.db')
            dispatcher.init_db(db)
            args = (self.task['repo'], self.task['issue_number'], self.task['title'], '', '', 'Recovery reservation', db)
            for attempt in range(1, MAX_EXECUTION_ATTEMPTS + 1):
                self.assertTrue(dispatcher.try_claim_issue(*args))
                self.assertFalse(dispatcher.try_claim_issue(*args))
                dispatcher.mark_dispatch_network_failure(args[0], args[1], db)
                self.assertTrue(dispatcher.is_issue_claimed_or_delivered(args[0], args[1], db)[0])
                with closing(sqlite3.connect(db)) as con, con:
                    con.execute('UPDATE deliveries SET fleet_retry_at = 0')
            self.assertFalse(dispatcher.try_claim_issue(*args))
            with closing(sqlite3.connect(db)) as con, con:
                self.assertEqual(con.execute('SELECT status FROM deliveries').fetchone()[0], 'FAILED_EXHAUSTED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
