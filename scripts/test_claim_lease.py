#!/usr/bin/env python3
"""F5 contract: a claim must have a lease, and a dead owner must be evictable.

These tests drive the real ``StateStore.claim()`` decision path and the real
``sweep_stale_runs`` against a fake durable store. Nothing here asserts on log strings: each
case asserts the admission decision or the persisted status the pipeline actually depends on.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_dispatch import retry_eligible  # noqa: E402
from actions_github import (  # noqa: E402
    CLAIM_LEASE_GRACE_SECONDS, CLAIM_TTL_SECONDS, DEFAULT_CLINE_TOTAL_BUDGET_SECONDS,
    GitHubError, StateStore, _lease_expires_at, lease_seconds)
from actions_reconcile import DEFAULT_JOB_TIMEOUT_SECONDS, sweep_stale_runs  # noqa: E402

REPO = "unit/runtime"


def stamp(delta_seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class FakeAPI:
    """Serves run status by run id; ``fail`` makes every probe an API error."""

    def __init__(self, runs=None, fail=False):
        self.runs = dict(runs or {})
        self.fail = fail
        self.calls = []

    def api(self, path, method="GET", body=None):
        self.calls.append((method, path))
        if self.fail:
            raise GitHubError("503 upstream unavailable")
        run_id = path.rstrip("/").rsplit("/", 1)[-1]
        return self.runs.get(run_id, {"status": "in_progress", "created_at": stamp(-60)})


class FakeStore:
    """A durable store that behaves like StateStore for the sweeper's purposes."""

    def __init__(self, rows):
        self.repo = REPO
        self.rows = [dict(row) for row in rows]
        self.writes = []

    def records(self):
        return [dict(row) for row in self.rows]

    def mutate(self, identity, change):
        for index, current in enumerate(self.rows):
            if current["task_id"] == identity:
                updated = change(dict(current))
                updated.setdefault("updated_at", stamp(1))
                self.rows[index] = updated
                self.writes.append((identity, updated.get("status")))
                return updated
        raise AssertionError("sweep touched an unknown identity")


def claimable(api, current):
    """A StateStore whose durable write is captured instead of sent to GitHub."""

    store = StateStore(api=api, repo=REPO)
    store.mutate = lambda identity, change: change(current)
    return store


def record(status="CLAIMED", owner="1234:attempt-1", **over):
    claimed = stamp(-60)
    base = {"task_id": "a" * 32, "repo": REPO, "issue_number": 7, "status": status,
            "owner": owner, "attempt": 1, "claimed_at": claimed,
            "lease_expires_at": _lease_expires_at(claimed), "updated_at": stamp(0)}
    base.update(over)
    return base


class LeaseDerivationTests(unittest.TestCase):
    def test_lease_is_derived_from_the_workflow_budget_not_a_short_ttl(self):
        # F5 target semantics 1: the lease can never be shorter than a legitimate run.
        self.assertGreaterEqual(lease_seconds(),
                                DEFAULT_CLINE_TOTAL_BUDGET_SECONDS + CLAIM_LEASE_GRACE_SECONDS)
        self.assertGreater(lease_seconds(), CLAIM_TTL_SECONDS)

    def test_a_huge_budget_extends_the_lease_and_a_tiny_one_still_respects_the_floor(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"CLINE_TOTAL_BUDGET_SECONDS": "7200"}):
            self.assertEqual(lease_seconds(), 7200 + CLAIM_LEASE_GRACE_SECONDS)
        with patch.dict(os.environ, {"CLINE_TOTAL_BUDGET_SECONDS": "60"}):
            self.assertEqual(lease_seconds(), CLAIM_TTL_SECONDS)

    def test_a_malformed_budget_falls_back_to_the_workflow_default(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"CLINE_TOTAL_BUDGET_SECONDS": "not-a-number"}):
            self.assertEqual(lease_seconds(),
                             DEFAULT_CLINE_TOTAL_BUDGET_SECONDS + CLAIM_LEASE_GRACE_SECONDS)


class ClaimAdmissionTests(unittest.TestCase):
    def test_1_a_live_owner_is_never_double_dispatched(self):
        store = claimable(FakeAPI({"1234": {"status": "in_progress"}}),
                          record(lease_expires_at=stamp(3600)))
        with self.assertRaisesRegex(ValueError, "A live Actions run already owns this task"):
            store.claim(REPO, 7, "9999:attempt-1", "https://example.invalid/run", "sha")

    def test_2_an_unexpired_lease_with_a_live_run_is_refused(self):
        # Expiry is a precondition, never on its own a reason to take over.
        store = claimable(FakeAPI({"1234": {"status": "in_progress"}}),
                          record(lease_expires_at=stamp(600)))
        with self.assertRaisesRegex(ValueError, "already owns this task"):
            store.claim(REPO, 7, "9999:attempt-1", "https://example.invalid/run", "sha")

    def test_3_expired_lease_with_an_unreachable_probe_is_not_proof_of_death(self):
        store = claimable(FakeAPI(fail=True),
                          record(claimed_at=stamp(-(lease_seconds() + 120)),
                                 lease_expires_at=stamp(-120)))
        with self.assertRaisesRegex(ValueError, "already owns this task"):
            store.claim(REPO, 7, "9999:attempt-1", "https://example.invalid/run", "sha")

    def test_4_a_provably_dead_owner_is_taken_over_and_the_takeover_is_recorded(self):
        store = claimable(FakeAPI({"1234": {"status": "completed"}}),
                          record(claimed_at=stamp(-(lease_seconds() + 120)),
                                 lease_expires_at=stamp(-120)))
        claimed = store.claim(REPO, 7, "9999:attempt-1", "https://example.invalid/run", "sha")
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertEqual(claimed["owner"], "9999:attempt-1")
        self.assertEqual(claimed["previous_owner"], "1234:attempt-1")
        self.assertEqual(claimed["previous_status"], "CLAIMED")
        self.assertIn("takeover_reason", claimed)
        self.assertIn("takeover_at", claimed)
        self.assertEqual(claimed["attempt"], 2)


class SweeperTests(unittest.TestCase):
    def test_5_a_run_past_its_job_window_is_cancelled_and_released(self):
        outstanding = record(owner="1234:attempt-1", claimed_at=stamp(-(DEFAULT_JOB_TIMEOUT_SECONDS + 600)))
        store = FakeStore([outstanding])
        api = FakeAPI({"1234": {"status": "in_progress",
                                "created_at": stamp(-(DEFAULT_JOB_TIMEOUT_SECONDS + 600))}})
        receipts = sweep_stale_runs(api, store, job_timeout_seconds=DEFAULT_JOB_TIMEOUT_SECONDS,
                                    cancel_wait_seconds=0)
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["swept"])
        self.assertEqual(receipts[0]["status"], "FAILED_RUNNER_SHUTDOWN")
        released = store.rows[0]
        self.assertEqual(released["status"], "FAILED_RUNNER_SHUTDOWN")
        self.assertTrue(released["swept"])
        self.assertEqual(released["swept_run"], "1234")
        self.assertEqual(released["job_timeout_seconds"], DEFAULT_JOB_TIMEOUT_SECONDS)
        self.assertTrue(any(method == "POST" and path.endswith("/1234/cancel")
                            for method, path in api.calls))
        # The attempt counter is untouched, so the ordinary bounded budget still applies.
        self.assertEqual(released["attempt"], 1)

    def test_5b_the_released_task_is_retryable_after_the_sweep(self):
        self.assertFalse(retry_eligible({"status": "CLAIMED"}))
        self.assertTrue(retry_eligible({"status": "FAILED_RUNNER_SHUTDOWN"}))

    def test_6_the_selector_is_never_widened(self):
        # The sweeper changes the state; retry_eligible itself must still refuse CLAIMED.
        self.assertFalse(retry_eligible({"status": "CLAIMED"}))
        self.assertFalse(retry_eligible({"status": "ENGINEERING"}))

    def test_7_the_bounded_attempt_cap_still_holds_after_a_sweep(self):
        swept = record(status="FAILED_RUNNER_SHUTDOWN", attempt=3,
                       claimed_at=stamp(-120), lease_expires_at=stamp(-60))
        store = claimable(FakeAPI({"1234": {"status": "completed"}}), swept)
        with self.assertRaisesRegex(ValueError, "Bounded recovery attempts exhausted"):
            store.claim(REPO, 7, "9999:attempt-1", "https://example.invalid/run", "sha")

    def test_8_a_malformed_owner_is_reported_never_guessed(self):
        store = FakeStore([record(owner="")])
        api = FakeAPI({})
        receipts = sweep_stale_runs(api, store, job_timeout_seconds=60, cancel_wait_seconds=0)
        self.assertEqual(receipts[0]["status"], "FAILED_MISSING_TERMINAL_RECEIPT")
        self.assertFalse(receipts[0]["swept"])
        self.assertEqual(store.rows[0]["status"], "FAILED_MISSING_TERMINAL_RECEIPT")
        self.assertIn("malformed", store.rows[0]["diagnostic"])
        self.assertEqual(api.calls, [])  # nothing was probed on a guessed run id

    def test_9_a_live_run_inside_its_window_is_left_alone(self):
        store = FakeStore([record()])
        api = FakeAPI({"1234": {"status": "in_progress", "created_at": stamp(-600)}})
        self.assertEqual(sweep_stale_runs(api, store, job_timeout_seconds=18000,
                                          cancel_wait_seconds=0), [])
        self.assertEqual(store.rows[0]["status"], "CLAIMED")

    def test_10_a_completed_run_belongs_to_the_existing_branch_not_the_sweeper(self):
        store = FakeStore([record()])
        api = FakeAPI({"1234": {"status": "completed", "created_at": stamp(-999999)}})
        self.assertEqual(sweep_stale_runs(api, store, job_timeout_seconds=60,
                                          cancel_wait_seconds=0), [])
        self.assertEqual(store.rows[0]["status"], "CLAIMED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
