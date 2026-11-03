"""Master state/claim assertions using the production store on an isolated real branch.

Fault rows are inputs, never delivery receipts. Production ledger is never modified.
The branch is retained for inspection. No workflow is dispatched by this suite.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import unittest
import uuid

from actions_github import GitHub, GitHubError, StateStore, task_id


class LiveStateFailureMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = GitHub()
        cls.control = os.environ.get('LIVE_PROBE_CONTROL', 'isearchxsolve/bounty-control')
        cls.target = os.environ.get('LIVE_PROBE_TARGET', 'isearchxsolve/oss-hunter-livefire')
        cls.branch = 'live-probes/' + uuid.uuid4().hex
        cls.store = StateStore(cls.api, cls.control)
        cls.store.branch = cls.branch
        cls.store.ensure()
        cls.harness = cls.api.api(f'repos/{cls.control}/commits/HEAD')['sha']
        print('Retained real fault branch: ' + cls.branch, flush=True)

    def setUp(self):
        self.number = 1
        self.identity = task_id(self.target, self.number)
        self.generation = uuid.uuid4().hex
        self.seed(status='DISPATCHED', attempt=0, dispatch_id=self.generation)

    def seed(self, **fields):
        return self.store.mutate(self.identity, lambda old: {
            'task_id': self.identity, 'repo': self.target, 'issue_number': self.number,
            'fault_fixture': True, **fields})

    def claim(self, owner='probe-owner:1', **kwargs):
        return self.store.claim(self.target, self.number, owner,
            'https://example.invalid/fault-input', self.harness, **kwargs)

    def test_remote_roundtrip_and_fresh_client_preserve_bytes(self):
        text = 'Unicode \u20b9 \u65e5\u672c\u8a9e\nsecond line'
        self.seed(status='FAULT_FIXTURE', text=text)
        fresh = StateStore(GitHub(), self.control)
        fresh.branch = self.branch
        row, sha = fresh.read(self.identity)
        self.assertEqual(row['text'], text)
        self.assertTrue(sha)

    def test_stale_write_is_rejected_without_losing_winning_update(self):
        old, sha = self.store.read(self.identity)
        self.store.mutate(self.identity, lambda row: {**row, 'count': 9})
        with self.assertRaises(GitHubError) as caught:
            self.store.write(self.identity, {**old, 'count': 1}, sha)
        self.assertTrue(any(code in str(caught.exception) for code in ('409', '422')))
        self.assertEqual(self.store.read(self.identity)[0]['count'], 9)

    def test_concurrent_claim_has_one_winner_and_one_attempt(self):
        barrier = threading.Barrier(2)
        def claimant(owner):
            barrier.wait(timeout=20)
            try:
                return self.claim(owner, dispatch_id=self.generation)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claimant, ['probe-a:1', 'probe-b:1']))
        self.assertEqual(sum(row is not None for row in results), 1)
        self.assertEqual(self.store.read(self.identity)[0]['attempt'], 1)

    def test_same_owner_replay_does_not_consume_attempt(self):
        first = self.claim(dispatch_id=self.generation)
        again = self.claim(dispatch_id=self.generation)
        self.assertEqual(first['attempt'], again['attempt'])

    def test_wrong_generation_never_changes_ledger(self):
        before = self.store.read(self.identity)
        with self.assertRaisesRegex(ValueError, 'generation mismatch'):
            self.claim(dispatch_id='stale-' + self.generation)
        self.assertEqual(self.store.read(self.identity), before)

    def test_wrong_owner_cannot_publish(self):
        self.claim(dispatch_id=self.generation)
        before = self.store.read(self.identity)
        with self.assertRaisesRegex(ValueError, 'ownership lost'):
            self.store.owned_update(self.identity, 'wrong:1', status='PUBLISHING')
        self.assertEqual(self.store.read(self.identity), before)

    def test_revoked_owner_cannot_continue(self):
        self.claim(dispatch_id=self.generation)
        self.store.mutate(self.identity, lambda row: {**row, 'owner_revoked': row['owner']})
        with self.assertRaisesRegex(ValueError, 'ownership lost'):
            self.store.assert_owner(self.identity, 'probe-owner:1')

    def test_bounded_attempts_refuse_without_resetting_counter(self):
        self.seed(status='FAILED_RUNNER_SHUTDOWN', attempt=3)
        before = self.store.read(self.identity)
        with self.assertRaisesRegex(ValueError, 'Bounded recovery attempts exhausted'):
            self.claim()
        self.assertEqual(self.store.read(self.identity), before)

    def test_unexpired_owner_is_never_double_dispatched(self):
        self.claim(dispatch_id=self.generation)
        with self.assertRaisesRegex(ValueError, 'already owns this task'):
            self.claim('another:1')
        self.assertEqual(self.store.read(self.identity)[0]['attempt'], 1)

    def test_expired_lease_unreachable_owner_is_not_proof_of_death(self):
        expired = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.seed(status='CLAIMED', owner='999999999999999:1', attempt=1,
                  claimed_at=expired, lease_expires_at=expired)
        with self.assertRaisesRegex(ValueError, 'already owns this task'):
            self.claim()
        self.assertEqual(self.store.read(self.identity)[0]['attempt'], 1)

    def test_truncated_remote_json_is_not_empty_success(self):
        row, sha = self.store.read(self.identity)
        endpoint = f'repos/{self.control}/contents/fleet-state/{self.identity}.json'
        result = self.api.api(endpoint, 'PUT', {
            'message': 'live probe: truncated fault input', 'branch': self.branch,
            'sha': sha, 'content': base64.b64encode(b'{"status":').decode()})
        try:
            with self.assertRaises(json.JSONDecodeError):
                self.store.read(self.identity)
        finally:
            self.store.write(self.identity, row, result['content']['sha'])
        self.assertEqual(self.store.read(self.identity)[0], row)


if __name__ == '__main__':
    unittest.main(verbosity=2)
