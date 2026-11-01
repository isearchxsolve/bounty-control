"""One continuous walk from the entry door to the claim gate, on one row.

Why this file exists
--------------------
``test_e2e_walk`` walks DISPATCHING -> DELIVERED, and it starts from a proof it builds itself
with ``bind_proof``. That is the back half. The front half -- the door deciding a row, the
dispatcher stamping it, the delivery side reading that stamp as binding -- was covered only by
unit tests of each hop in isolation, each with its own hand-made proof.

Measured 2026-11-01: the door emitted twenty-four refusal reasons that appeared in no table the
agent could read, and ``repository_intent`` ran nowhere on the live path while the brief promised
it did. Neither defect was reachable from the existing e2e, because the existing e2e never calls
the door.

This module walks the real seam: ``verify_model_rows`` (the verifier production passes to
``iterate``) admits a row, the admitted row's proof is handed to the real ``dispatch``, and the
real ``require_evidence`` claim gate reads it back. Only the transport is replaced.

Run: python scripts/test_e2e_door_to_claim.py
"""
import base64
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_dispatch as dispatch  # noqa: E402
import cline_entry_door as door  # noqa: E402
from actions_github import GitHub, StateStore, task_id  # noqa: E402
from pipeline_evidence import require_evidence  # noqa: E402

REPO = "acme/http"
NUMBER = 7
SHA = "a" * 40
SOURCE = "def retry():\n    pass\n"
URL = f"https://github.com/{REPO}/issues/{NUMBER}"


class DoorTransport:
    """Answers the endpoints the door and the dispatcher actually call, and records them."""

    def __init__(self, merged=40, total=50):
        self.calls = []
        self.merged, self.total = merged, total

    def api(self, endpoint, method="GET", data=None, **kwargs):
        self.calls.append((method, endpoint))
        if endpoint == "graphql":
            return {"data": {"repository": {"merged": {"totalCount": self.merged},
                                            "all": {"totalCount": self.total}}}}
        if endpoint.endswith("/dispatches"):
            return None
        return {}

    def pages(self, endpoint, **kwargs):
        self.calls.append(("GET", endpoint))
        return []

    def workflow_runs(self, repo, status=None):
        return []


class WalkStore(StateStore):
    """The real StateStore contract, in memory. Only storage is replaced."""

    def __init__(self):
        self.repo = "unit/control"
        self.rows = {}

    def ensure(self):
        return None

    def read(self, identity):
        return (dict(self.rows[identity]) if identity in self.rows else None), None

    def mutate(self, identity, change):
        from actions_github import utcnow
        document = change(dict(self.rows[identity]) if identity in self.rows else None)
        document["updated_at"] = utcnow()
        self.rows[identity] = document
        return document

    def records(self):
        return [dict(row) for row in self.rows.values()]


def context():
    """The issue context the dispatcher and the door both build."""
    return {"repo": REPO, "issue_number": NUMBER,
            "issue": {"number": NUMBER, "state": "open", "title": "Retry fails",
                      "body": "Bounty $250. Fix src/retry.py",
                      "html_url": URL, "user": {"login": "payer"},
                      "author_association": "OWNER", "labels": []},
            "comments": [], "complete_comments": True,
            "repository": {"full_name": REPO, "default_branch": "main",
                           "archived": False, "disabled": False}}


def candidate():
    """A row exactly as the agent writes it into shortlist.jsonl."""
    return {"repo": REPO, "issue": NUMBER, "url": URL, "is_code_task": True,
            "reward_quote": "Bounty $250.",
            "reward_usd": 250,
            "scope_quote": "Fix src/retry.py",
            "admission_reason": "Owner states a current $250 offer for a bounded source fix",
            "funding": {"amount": "250", "currency": "USD", "payer": "payer",
                        "source_url": URL},
            "code_evidence": {"path": "src/retry.py", "sha": SHA,
                              "quote": "def retry():", "is_product_code": True}}


def blob():
    return {"type": "file", "sha": SHA, "encoding": "base64",
            "content": base64.b64encode(SOURCE.encode()).decode()}


def run_door(rows, transport=None):
    """Drive the production verifier exactly as agent_door does."""
    transport = transport or DoorTransport()
    ctx = context()
    with patch.object(GitHub, "api", return_value=blob()):
        return door.verify_model_rows(
            rows, fetch=lambda *a: ctx["issue"],
            context_builder=lambda *a: ctx, admission_client=transport)


class TheDoorToClaimSeam(unittest.TestCase):
    """The proof the door writes is the proof the claim gate reads."""

    def setUp(self):
        self.store = WalkStore()
        self.api = DoorTransport()
        self.identity = task_id(REPO, NUMBER)

    def test_an_admitted_row_survives_dispatch_and_the_claim_gate(self):
        # --- hop 1: the door admits the row and writes its own proof ------------------
        verdict = run_door([candidate()], self.api)
        self.assertEqual(verdict["refused"], [])
        self.assertEqual(len(verdict["admitted"]), 1)
        admitted = verdict["admitted"][0]
        self.assertTrue(admitted["sovereign_admission"])
        self.assertEqual(admitted["lane"], "founder")

        # --- hop 2: the real dispatcher stamps and reserves it ------------------------
        dispatch.dispatch(self.api, self.store, context(), admitted["admission"],
                          [admitted["source_lane"]],
                          sovereign_admission=admitted["sovereign_admission"],
                          competition=admitted["competition"])
        state = self.store.read(self.identity)[0]
        self.assertEqual(state["status"], "DISPATCHED")
        self.assertIs(state["sovereign_admission"], True)

        # --- hop 3: the real claim gate reads that proof as binding -------------------
        proof, competition = require_evidence(state, context())
        self.assertEqual(proof, admitted["admission"])
        self.assertEqual(proof["funding"]["amount"], "250")
        self.assertIs(competition["blocking"], False)

    def test_the_door_proof_is_bound_to_the_source_it_was_read_from(self):
        """A claim gate that cannot detect a changed issue is not a gate."""
        admitted = run_door([candidate()], self.api)["admitted"][0]
        dispatch.dispatch(self.api, self.store, context(), admitted["admission"],
                          ["bounty"], sovereign_admission=True,
                          competition=admitted["competition"])
        state = self.store.read(self.identity)[0]
        edited = context()
        edited["issue"]["body"] = "Bounty $250. Fix src/retry.py. Offer withdrawn."
        with self.assertRaises(ValueError) as caught:
            require_evidence(state, edited)
        self.assertIn("source changed", str(caught.exception))

    def test_a_closed_issue_cannot_be_claimed(self):
        """Closing the issue changes the source digest, so the revision gate catches it first.

        ``source_revision`` hashes the whole issue document, ``state`` included, so a closed
        issue is refused as changed evidence before the explicit open check is reached. Both
        are real; the earlier one wins. Asserted as a refusal rather than a specific string,
        because pinning the later message would be pinning an unreachable branch.
        """
        admitted = run_door([candidate()], self.api)["admitted"][0]
        dispatch.dispatch(self.api, self.store, context(), admitted["admission"],
                          ["bounty"], sovereign_admission=True,
                          competition=admitted["competition"])
        state = self.store.read(self.identity)[0]
        closed = context()
        closed["issue"]["state"] = "closed"
        with self.assertRaises(ValueError):
            require_evidence(state, closed)


class TheIntentGateRunsAtTheDoor(unittest.TestCase):
    """Measured 2026-11-01: this gate ran nowhere on the live path while the brief promised it."""

    def test_a_repository_that_never_merges_is_refused_at_the_door(self):
        verdict = run_door([candidate()], DoorTransport(merged=0, total=4458))
        self.assertEqual(verdict["admitted"], [])
        self.assertEqual(verdict["refused"][0]["reason"], "REPOSITORY_DOES_NOT_MERGE")

    def test_a_young_repository_is_not_refused_on_silence(self):
        """Absence of evidence is never rejection: too few pull requests to judge."""
        verdict = run_door([candidate()], DoorTransport(merged=0, total=3))
        self.assertEqual(verdict["refused"], [])
        self.assertEqual(len(verdict["admitted"]), 1)

    def test_an_unreadable_probe_is_not_a_verdict(self):
        """A throttled GraphQL call says nothing about the repository."""
        class Unreadable(DoorTransport):
            def api(self, endpoint, method="GET", data=None, **kwargs):
                if endpoint == "graphql":
                    raise OSError("graphql unavailable")
                return super().api(endpoint, method, data, **kwargs)

        verdict = run_door([candidate()], Unreadable())
        self.assertEqual(verdict["refused"], [])
        self.assertEqual(len(verdict["admitted"]), 1)

    def test_the_probe_is_paid_once_per_repository(self):
        """Two rows in one repository must not cost two GraphQL calls."""
        transport = DoorTransport()
        second = candidate()
        second["issue"] = 8
        second["url"] = f"https://github.com/{REPO}/issues/8"
        run_door([candidate(), second], transport)
        graphql = [call for call in transport.calls if call[1] == "graphql"]
        self.assertEqual(len(graphql), 1)


class TheFeedbackClosesTheLoop(unittest.TestCase):
    """A refused row must come back to the agent with a cause it can act on."""

    def test_a_refusal_from_the_live_path_is_explained_to_the_agent(self):
        transport = DoorTransport(merged=0, total=4458)
        verdict = run_door([candidate()], transport)
        refusals = verdict["refused"]
        self.assertTrue(refusals)

        meanings = door.render_meanings(refusals)
        for entry in refusals:
            self.assertIn(door.refusal_code(entry), meanings)
        self.assertNotIn("no meaning recorded", meanings)
        # And the meaning is the gate's own words, not a placeholder.
        self.assertIn("does not merge outside work", meanings)

    def test_the_prompt_renders_with_no_unfilled_slots(self):
        refusals = [{"row": {"repo": REPO, "issue": NUMBER},
                     "reason": "REPOSITORY_DOES_NOT_MERGE"}]
        listed = "\n".join(
            "- {repo}#{issue}: {reason}".format(
                repo=e["row"]["repo"], issue=e["row"]["issue"], reason=e["reason"])
            for e in refusals)
        prompt = door.FEEDBACK_PROMPT.format(
            refusals=listed, meanings=door.render_meanings(refusals),
            shape=door.render_shape_note([]))
        self.assertNotIn("{meanings}", prompt)
        self.assertNotIn("{refusals}", prompt)
        self.assertNotIn("{shape}", prompt)
        self.assertIn("REPOSITORY_DOES_NOT_MERGE", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
