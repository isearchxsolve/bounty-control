"""Isolated policy tests. Mocks are unit-test inputs, never live fleet receipts."""
import io
import json
import unittest
from unittest.mock import patch

import kaggle_engine_worker as worker


class RetryPolicyTests(unittest.TestCase):
    def decision(self, events, now=1000):
        payload = {"orders": [{"text": json.dumps(event)} for event in events]}
        with patch.object(worker.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            return worker.task_retry_decision({"task_id": "policy-case"}, now)

    def event(self, state, attempt=1, **extra):
        return dict(task_id="policy-case", state=state, attempt=attempt, at=500, expires_at=1500, **extra)

    def test_new_task(self):
        self.assertEqual(self.decision([])[::2], (True, 1))

    def test_success_never_retries(self):
        self.assertFalse(self.decision([self.event("SUCCESS")])[0])

    def test_active_claim_blocks(self):
        self.assertFalse(self.decision([self.event("CLAIMED")])[0])

    def test_expired_claim_retries(self):
        self.assertEqual(self.decision([self.event("CLAIMED")], now=1600)[::2], (True, 2))

    def test_failure_retries_after_cooldown(self):
        self.assertEqual(self.decision([self.event("CLAIMED"), self.event("FAILED")])[::2], (True, 2))

    def test_failure_cooldown(self):
        self.assertFalse(self.decision([self.event("FAILED")], now=600)[0])

    def test_three_attempt_limit(self):
        self.assertFalse(self.decision([self.event("FAILED", attempt=3)])[0])

    def test_lookup_error_fails_closed(self):
        with patch.object(worker.urllib.request, "urlopen", side_effect=OSError("unit network failure")):
            with self.assertRaises(OSError):
                worker.task_retry_decision({"task_id": "policy-case"})

    def test_roadmap_still_excluded(self):
        self.assertTrue(worker.is_speculative_dispatch_task({"title": "[ROADMAP] Future change"}))

    def test_health_network_failure(self):
        with patch.object(worker.urllib.request, "urlopen", side_effect=OSError("unit DNS failure")):
            self.assertFalse(worker.startup_health()[0])


if __name__ == "__main__":
    unittest.main()
