"""A verified refusal must survive the ledger as a refusal.

Measured need (2026-10-27): the first real dispatch reached Cline, Cline inspected
Expensify/App#105153 and returned ``action=blocked`` with its actual diagnosis, the contract
verified that answer -- and then ``run_cline_claim_intake`` raised a plain ``RuntimeError``.
The host wrote ``engineer-failure.json`` with ``FAILED_ENGINEER`` and the ledger recorded a
broken pipeline instead of a correct decision. Nothing was wrong with the engineering; the
report simply did not warrant a code change.

Two behaviours are pinned here, and they pull in opposite directions:

* A refusal (``REJECTED_*``) is terminal and is never rewritten as ``FAILED_*``, and it never
  consumes the bounded recovery budget -- retrying it would buy the same verdict again.
* A genuine failure is still a failure: it keeps its ``FAILED_*`` status and is still recorded
  in ``failures``. Loosening that would hide real breakage, which is worse than the bug.

``finish()`` is exercised against a fake store so the test never touches the network, and the
publish job is never armed by a refusal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from actions_dispatch import retry_eligible

HERE = Path(__file__).resolve().parent
IDENTITY = "a" * 32


class Blocked(Exception):
    """Stand-in for kaggle_engine_worker.PreparationBlocked (importing it is heavy)."""

    def __init__(self, report, reason=None):
        self.report = report
        detail = reason or report.get("reason") or "unresolved prerequisite"
        super().__init__("Cline preparation blocked: " + str(detail))


class FakeStore:
    def __init__(self, previous):
        self.previous = previous
        self.written = None

    def read(self, identity):
        return self.previous, None

    def owned_update(self, identity, who, **fields):
        self.written = {"identity": identity, "owner": who, **fields}


class TerminalOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            "FLEET_ARTIFACT_DIR": str(self.root),
            "GITHUB_RUN_ID": "1",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(self.root / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.delivery = self._import_delivery()

    @staticmethod
    def _import_delivery():
        import sys
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import actions_delivery
        return actions_delivery

    def _claim(self):
        (self.root / "claim.json").write_text(json.dumps({
            "mode": "deliver", "context": {"task_id": IDENTITY, "repo": "Expensify/App",
                                           "issue_number": 105153},
            "state": {"owner": "1:1"}}), encoding="utf-8")

    def _run(self, result, job_status="failure"):
        self._claim()
        if result is not None:
            (self.root / "engineering-result.json").write_text(
                json.dumps(result), encoding="utf-8")
        store = FakeStore({"owner": "1:1", "failures": []})
        with mock.patch.object(self.delivery, "StateStore", return_value=store):
            self.delivery.finish(job_status)
        return store.written

    def test_a_verified_refusal_is_recorded_as_a_refusal(self):
        written = self._run({"status": "REJECTED_PREPARATION", "declared_reason":
                             "Not a concrete, warranted code change", "task_id": IDENTITY})
        self.assertEqual(written["status"], "REJECTED_PREPARATION")
        self.assertNotIn("failures", written, "a refusal must not consume the recovery budget")
        self.assertEqual(written["declared_reason"], "Not a concrete, warranted code change")

    def test_a_genuine_failure_stays_a_failure_and_is_recorded(self):
        written = self._run({"status": "BLOCKED_ON_CAPABILITY", "error": "boom"})
        self.assertEqual(written["status"], "FAILED_BLOCKED_ON_CAPABILITY")
        self.assertEqual(len(written["failures"]), 1)
        self.assertEqual(written["failures"][0]["status"], "FAILED_BLOCKED_ON_CAPABILITY")

    def test_a_verified_release_without_publication_is_a_missing_publication(self):
        written = self._run({"status": "VERIFIED"}, job_status="success")
        self.assertEqual(written["status"], "FAILED_PUBLICATION_MISSING")

    def test_a_publication_record_wins(self):
        (self.root / "publication.json").write_text(json.dumps(
            {"status": "PUBLISHED_PENDING_CHECKS", "pr_url": "https://example.invalid/pr/1"}),
            encoding="utf-8")
        written = self._run({"status": "REJECTED_PREPARATION"}, job_status="success")
        self.assertEqual(written["status"], "PUBLISHED_PENDING_CHECKS")

    def test_the_refusal_reaches_the_job_summary(self):
        self._run({"status": "REJECTED_PREPARATION",
                   "declared_reason": "This works as designed. It is not a bug."})
        summary = (self.root / "summary.md").read_text(encoding="utf-8")
        self.assertIn("REJECTED_PREPARATION", summary)
        self.assertIn("works as designed", summary)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            "FLEET_ARTIFACT_DIR": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        import sys
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import actions_delivery
        self.delivery = actions_delivery

    def test_the_refusal_is_written_with_its_evidence_and_arms_nothing(self):
        blocked = Blocked({"action": "blocked", "reason": "documented as expected/by-design",
                           "worktree": "/tmp/wt", "base_sha": "b" * 40,
                           "default_branch": "main", "sources": [{"path": "package.json"}]})
        task = {"task_id": IDENTITY, "run_url": "https://example.invalid/run/1",
                "admission": {"funding": {"amount": "175", "currency": "USD"}}}
        self.delivery.reject_preparation(blocked, task, "Expensify/App", 105153)
        written = json.loads((self.root / "engineering-result.json").read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "REJECTED_PREPARATION")
        self.assertEqual(written["declared_reason"], "documented as expected/by-design")
        self.assertEqual(written["evidence"]["base_sha"], "b" * 40)
        self.assertEqual(written["evidence"]["admission"]["amount"], "175")
        self.assertEqual(written["issue_number"], 105153)
        outputs = (self.root / "output.txt").read_text(encoding="utf-8")
        self.assertEqual(outputs.strip(), "verdict=rejected_preparation")

    def test_the_worker_raises_the_carrying_exception_and_no_longer_a_bare_runtime_error(self):
        source = (HERE / "kaggle_engine_worker.py").read_text(encoding="utf-8")
        self.assertIn("class PreparationBlocked(RuntimeError):", source)
        self.assertIn("raise PreparationBlocked(report)", source)
        self.assertNotIn("raise RuntimeError('Cline preparation blocked:", source)

    def test_the_workflow_gates_publish_on_the_verdict(self):
        workflow = (HERE.parent / ".github" / "workflows" / "engine2.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"outputs:\s*\n\s+verdict: \$\{\{ steps\.engineer\.outputs\.verdict \}\}")
        self.assertRegex(workflow, r"id: engineer")
        self.assertRegex(workflow, r"needs\.engineer\.outputs\.verdict\s*\n?\s*== 'verified'")


class RedispatchTests(unittest.TestCase):
    """A terminal refusal must not be re-admitted on the next cycle.

    Measured 2026-10-27: Expensify/App#105153 was refused as by-design at 17:57 and
    re-dispatched at 18:44, because a refusal recorded as FAILED_ENGINEER looks retryable.
    """

    def test_a_verified_refusal_is_terminal(self):
        self.assertFalse(retry_eligible({"status": "REJECTED_PREPARATION"}))

    def test_an_unstarted_issue_is_eligible(self):
        self.assertTrue(retry_eligible(None))
        self.assertTrue(retry_eligible({}))

    def test_a_real_failure_stays_retryable(self):
        for status in ("FAILED_ENGINEER", "FAILED_PUBLICATION_MISSING", "FAILED_DISPATCH"):
            self.assertTrue(retry_eligible({"status": status}), status)

    def test_a_delivered_issue_is_not_redispatched(self):
        for status in ("DELIVERED", "PUBLISHED_PENDING_CHECKS", "CLOSED_UNMERGED"):
            self.assertFalse(retry_eligible({"status": status}), status)

    def test_the_dispatch_gate_counts_a_refusal_separately(self):
        source = (HERE / "actions_dispatch.py").read_text(encoding="utf-8")
        self.assertIn("terminal_refusal", source)
        self.assertNotIn('if state and not state["status"].startswith("FAILED"):', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
