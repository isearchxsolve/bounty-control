"""Retry policy contracts, driven through the production decision function.

This suite used to call `kaggle_engine_worker.task_retry_decision`, which the worker no longer
has: the decision moved to `fleet_recovery_policy.recovery_decision` and its input changed from
relay orders to claim/result rows. Nine of the ten assertions therefore died with
`AttributeError` and the suite still reported a pass-only meaning nobody could rely on.

The assertions are unchanged in substance -- new task, success, active lease, expired lease,
cooldown, attempt cap, permanent failure, speculative exclusion, health -- and now run against
the function that actually decides.
"""
import unittest
from unittest.mock import patch

import fleet_recovery_policy as policy
import kaggle_engine_worker as worker

TASK = {"task_id": "policy-case", "repo": "owner/repo", "issue_number": 1}
COOLDOWN = policy.RETRY_DELAYS_SECONDS[0]


class RetryPolicyTests(unittest.TestCase):
    def decision(self, claims=(), results=(), now=1000):
        return policy.recovery_decision(TASK, list(claims), list(results), now=now)

    def claim(self, at=500, **extra):
        return {"text": "CLAIMED " + TASK["task_id"], "at": at, **extra}

    def result(self, state, at=600, body=""):
        return {"text": f"{state} {TASK['task_id']} {body}".strip(), "at": at}

    def test_new_task(self):
        self.assertEqual((self.decision().allowed, self.decision().attempt), (True, 1))

    def test_success_never_retries(self):
        self.assertFalse(self.decision(results=[self.result("SUCCESS")]).allowed)

    def test_active_claim_blocks(self):
        with patch.object(policy, "current_claim", return_value=(self.claim(), 1500)):
            self.assertFalse(self.decision(claims=[self.claim()]).allowed)

    def test_expired_claim_retries(self):
        with patch.object(policy, "current_claim", return_value=(self.claim(), 900)):
            decision = self.decision(claims=[self.claim()])
            self.assertEqual((decision.allowed, decision.attempt), (True, 2))

    def test_failure_retries_after_cooldown(self):
        decision = self.decision(results=[self.result("FAILED", body="network timeout")],
                                 now=600 + COOLDOWN)
        self.assertEqual((decision.allowed, decision.attempt), (True, 2))

    def test_failure_cooldown(self):
        decision = self.decision(results=[self.result("FAILED", body="network timeout")], now=601)
        self.assertFalse(decision.allowed)

    def test_three_attempt_limit(self):
        results = [self.result("FAILED", body="network timeout") for _ in range(3)]
        decision = self.decision(results=results, now=600 + 3 * COOLDOWN)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "attempt limit reached")

    def test_lookup_error_fails_closed(self):
        # A failure the policy cannot classify is not retried: unknown stays closed.
        decision = self.decision(results=[self.result("FAILED", body="something nobody classified")],
                                 now=600 + COOLDOWN)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "permanent or unclassified failure")

    def test_roadmap_still_excluded(self):
        self.assertTrue(worker.is_speculative_dispatch_task({"title": "[ROADMAP] Future change"}))

    def test_health_network_failure(self):
        # `startup_health` is gone too; the surviving contract is the gateway health probe, which
        # must read unhealthy rather than raise when its endpoint cannot be reached.
        with patch.object(worker, "_proxy_free_urlopen", side_effect=OSError("unit DNS failure")):
            self.assertFalse(worker._cline_proxy_is_healthy())


if __name__ == "__main__":
    unittest.main()
