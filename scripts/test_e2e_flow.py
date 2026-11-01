"""End-to-end flow proof: every status must be terminal or have a forward path.

This is the acceptance test for "full issue flow e2e pipeline wide". It is deliberately
table-driven: the flow is data, and the assertions are about the shape of the graph rather
than about one happy path. A status that nothing observes, or that nothing can leave, fails
here instead of silently stranding a task in production.

Run: python scripts/test_e2e_flow.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_dispatch import retry_eligible  # noqa: E402
from actions_reconcile import PR_OBSERVATION_STATUSES, classify_checks, review_verdict  # noqa: E402


# The complete lifecycle, in order, as the pipeline actually writes it.
LIFECYCLE = [
    "DISPATCHING",
    "DISPATCHED",
    "CLAIMED",
    "ENGINEERING",
    "VERIFIED",
    "PUBLISHING",
    "PUBLISHED_PENDING_CHECKS",
    "AWAITING_REVIEW",
    "DELIVERED",
]

# Statuses that end a task. Nothing further is expected or possible.
TERMINAL = {"DELIVERED", "CLOSED_UNMERGED"}

# Statuses a task may sit in while a human or the platform decides. These must be re-observed
# on every reconcile pass, or the task is terminal by accident.
WAITING_ON_OTHERS = {
    "PUBLISHED_PENDING_CHECKS",
    "AWAITING_REVIEW",
    "CHECKS_HELD_FOR_APPROVAL",
    "CHANGES_REQUESTED",
    "FAILED_REMOTE_CHECKS",
}

# Statuses that mean "a real fault happened". These must be retryable so the task can be
# re-dispatched, bounded by the attempt budget.
RECOVERABLE_FAILURES = {
    "FAILED_DISPATCH",
    "FAILED_ENGINEER",
    "FAILED_PREPARE",
    "FAILED_PUBLISH",
    "FAILED_REMOTE_CHECKS",
    "FAILED_DELIVERABLE_MISSING",
    "FAILED_MISSING_TERMINAL_RECEIPT",
    "FAILED_MISSING_RECEIPT",
    "FAILED_RUNNER_SHUTDOWN",
    "FAILED_INFRASTRUCTURE",
    "FAILED_BUDGET_EXHAUSTED",
    "FAILED_PREPARATION_RACE",
}

# Refusals are verdicts, not faults. Re-dispatching one spends a run to relearn an answer
# already written down.
REFUSALS = {"REJECTED_PREPARATION"}


class FlowGraphTests(unittest.TestCase):
    """The graph itself: no orphans, no accidental terminals."""

    def test_every_waiting_status_is_observed(self):
        for status in WAITING_ON_OTHERS:
            self.assertIn(status, PR_OBSERVATION_STATUSES,
                          status + " can be written but is never read back")

    def test_every_recoverable_failure_is_retryable(self):
        for status in RECOVERABLE_FAILURES:
            self.assertTrue(retry_eligible({"status": status}),
                            status + " is a fault with no way back")

    def test_refusals_are_not_retried(self):
        for status in REFUSALS:
            self.assertFalse(retry_eligible({"status": status}),
                             status + " is a verdict, not a fault")

    def test_terminal_statuses_refuse_further_work(self):
        for status in TERMINAL:
            self.assertFalse(retry_eligible({"status": status}),
                             status + " is terminal but still accepts work")

    def test_lifecycle_is_ordered_and_ends_delivered(self):
        self.assertEqual(LIFECYCLE[-1], "DELIVERED")
        self.assertEqual(len(LIFECYCLE), len(set(LIFECYCLE)), "duplicate status in lifecycle")

    def test_no_status_is_both_terminal_and_recoverable(self):
        self.assertEqual(TERMINAL & RECOVERABLE_FAILURES, set())
        self.assertEqual(TERMINAL & WAITING_ON_OTHERS, set())


class ObservationTests(unittest.TestCase):
    """What the reconcile loop can actually see."""

    def _api(self, conclusion, status="completed"):
        class Api:
            def api(self, endpoint, method=None, payload=None):
                return {"check_runs": [{"id": 1, "name": "CI", "status": status,
                                        "conclusion": conclusion, "app": {"id": 1}}]}

            def pages(self, endpoint, **kw):
                return []
        return Api()

    def test_ci_outcomes_map_to_distinct_states(self):
        cases = {
            "success": "PASSED",
            "failure": "FAILED",
            "action_required": "HELD",
            None: "PENDING",
        }
        for conclusion, expected in cases.items():
            status = "in_progress" if conclusion is None else "completed"
            proof = classify_checks(self._api(conclusion, status), "o/r", "a" * 40)
            self.assertEqual(proof["state"], expected,
                             f"conclusion={conclusion} mapped to {proof['state']}")

    def test_held_ci_is_not_a_failure(self):
        proof = classify_checks(self._api("action_required"), "o/r", "a" * 40)
        self.assertEqual(proof["failures"], [],
                         "a workflow that never ran cannot have failed")

    def test_review_verdicts_are_distinct(self):
        def api_with(states):
            class Api:
                def pages(self, endpoint, **kw):
                    return [{"state": s, "user": {"login": "u"},
                             "submitted_at": "2026-11-01T00:00:00Z"} for s in states]
            return Api()

        self.assertEqual(review_verdict(api_with([]), "o/r", 1)["verdict"], "NONE")
        self.assertEqual(review_verdict(api_with(["COMMENTED"]), "o/r", 1)["verdict"], "COMMENTED")
        self.assertEqual(review_verdict(api_with(["APPROVED"]), "o/r", 1)["verdict"], "APPROVED")
        self.assertEqual(
            review_verdict(api_with(["APPROVED", "CHANGES_REQUESTED"]), "o/r", 1)["verdict"],
            "CHANGES_REQUESTED", "a later change request must override an earlier approval")


if __name__ == "__main__":
    unittest.main(verbosity=2)
