"""Sovereign entry door: admission is decided once, at the door.

Baba 2026-10-31: 42 delivery runs started, 38 engineering runs succeeded, 0 pull requests were
published. The door admitted the issue, the dispatcher admitted it again, and then the delivery
engine was asked to classify the issue a third time and wrote ``rejected_preparation`` on 42 of
42 - after forty minutes of runner time each. The law is now two rules:

* the entry door runs the whole battery (admission, competition, state) and stamps its proof;
* the delivery side executes that proof as fact and judges only its own engineering.

One competition decision stays here on purpose: a claimant that appears while the fix is being
verified is a race, and a race must be caught before the pull request is opened.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import actions_delivery as delivery
from pipeline_evidence import bind_proof


class FakeGitHub:
    """Only the reads ``claim`` makes: the issue context."""

    def __init__(self, context):
        self.context = context
        self.token = ""

    def issue_context(self, repo, number):
        return json.loads(json.dumps(self.context))


class FakeStore:
    def __init__(self, previous=None):
        self.previous = previous
        self.repo = "isearchxsolve/bounty-control"
        self.claimed = None

    def read(self, identity):
        return self.previous, None

    def claim(self, repo, number, owner, run_url, sha, recovery, budget_seconds=None, dispatch_id=None):
        self.claimed = {"repo": repo, "number": number, "owner": owner}
        return {"owner": owner, "attempt": 0, "status": "CLAIMED"}


ISSUE_CONTEXT = {
    "repo": "acme/http", "issue_number": 5, "title": "Retry drops the last attempt",
    "body": "The client gives up after one attempt.", "comments": [],
    "issue": {"state": "open", "body": "Bounty $250"}, "complete_comments": True,
    "repository": {"full_name": "acme/http", "default_branch": "main"},
}


class ClaimTakesTheDoorVerdictAsFact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "FLEET_ARTIFACT_DIR": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"),
            "GITHUB_RUN_ID": "4242",
            "GITHUB_SHA": "c" * 40,
            "GITHUB_REPOSITORY": "isearchxsolve/bounty-control",
        })
        env.start()
        self.addCleanup(env.stop)

    def _claim(self, payload, store=None):
        event = self.root / "event.json"
        event.write_text(json.dumps({"client_payload": {
            "repo": "acme/http", "issue_number": 5, "mode": "deliver", **payload}}),
            encoding="utf-8")
        store = store or FakeStore({"admission": payload.get("admission"),
            "competition": payload.get("competition"), "dispatch_id": payload.get("dispatch_id"),
            "sovereign_admission": True})
        with mock.patch.object(delivery, "GitHub", return_value=FakeGitHub(ISSUE_CONTEXT)), \
                mock.patch.object(delivery, "StateStore", return_value=store), \
                mock.patch.object(delivery, "competition") as competing:
            delivery.claim(event)
        return json.loads((self.root / "claim.json").read_text(encoding="utf-8")), competing

    def test_a_missing_door_decision_is_never_manufactured(self):
        with self.assertRaisesRegex(ValueError, "dispatch generation required"):
            self._claim({})
        self.assertFalse((self.root / "claim.json").exists())

    def test_the_door_proof_travels_into_the_claim(self):
        proof = bind_proof({"funding": {"amount": "250", "currency": "USD"}, "lane": "founder"}, ISSUE_CONTEXT)
        document, _ = self._claim({"admission": proof,
                                   "dispatch_id": "generation-1",
                                   "competition": {"blocking": False, "verdict": "clear: door verdict"}})
        self.assertEqual(document["context"]["admission"], proof)
        self.assertEqual(document["context"]["lane"], "founder")
        self.assertEqual(document["context"]["competition"], "clear: door verdict")

    def test_a_partial_dispatcher_row_cannot_authorize_an_event(self):
        with self.assertRaisesRegex(ValueError, "dispatch generation required"):
            self._claim({}, store=FakeStore({"admission": {"funding": {"amount": "250"}}}))

    def test_the_last_minute_race_check_still_runs(self):
        """Baba 2026-10-31: competing PR checks stay at delivery for race conditions."""
        proof = bind_proof({"funding": {"amount": "250"}}, ISSUE_CONTEXT)
        _, competing = self._claim({"admission": proof, "dispatch_id": "generation-1",
                                    "competition": {"blocking": False}})
        competing.assert_called_once()


class QualityRefusalsAreInvariantViolations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "FLEET_ARTIFACT_DIR": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"),
        })
        env.start()
        self.addCleanup(env.stop)

    def _blocked(self, reason):
        class Blocked(Exception):
            def __init__(self, report):
                self.report = report
                super().__init__("Cline preparation blocked: " + reason)
        return Blocked({"action": "blocked", "reason": reason})

    def test_a_quality_refusal_is_not_recorded_as_a_refusal(self):
        for reason in ("this is a marketing deliverable, not code",
                       "market validation request without a repository change",
                       "already implemented by an open pull request",
                       "competing pull request already resolves it"):
            with self.assertRaises(ValueError) as raised:
                delivery.reject_preparation(self._blocked(reason),
                                            {"task_id": "a" * 32}, "acme/http", 5)
            self.assertIn("Delivery invariant violated", str(raised.exception), reason)
            self.assertFalse((self.root / "engineering-result.json").exists(), reason)
            self.assertFalse((self.root / "output.txt").exists(), reason)

    def test_an_engineering_refusal_still_stands(self):
        delivery.reject_preparation(
            self._blocked("documented as expected/by-design"),
            {"task_id": "a" * 32}, "acme/http", 5)
        written = json.loads((self.root / "engineering-result.json").read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "REJECTED_PREPARATION")
        self.assertEqual(written["declared_reason"], "documented as expected/by-design")

    def test_the_engineer_prompt_forbids_judging_the_issue(self):
        source = (Path(__file__).resolve().parent / "kaggle_engine_worker.py").read_text(
            encoding="utf-8")
        self.assertIn("SUPREME MANDATE: ZERO JUDGMENT OF ISSUE QUALITY", source)
        self.assertIn('strictly forbidden from writing action="blocked"', source)
        self.assertNotIn("classify the issue from its complete text", source)
        self.assertNotIn("If it is market validation", source)


if __name__ == "__main__":
    unittest.main()
