"""The door-to-claim seam, wired to a real GitHub issue instead of a transport fake.

``test_e2e_door_to_claim`` proves the seam with ``DoorTransport`` (a ``GitHub`` subclass that
answers the endpoints) and ``WalkStore`` (an in-memory ``StateStore``). Both are faithful, but
neither is the real connection: a changed transport contract, a changed issue-reader or a changed
durable write would leave them green.

This file keeps that test's assertions and swaps the boundaries:

| Boundary | Before | Here |
|---|---|---|
| Issue context | ``context()`` literal | ``GitHub().issue_context()`` on a real open issue |
| Product source bytes | ``patch.object(GitHub, "api", return_value=blob())`` | the door's own ``source_reader`` calling the real contents API |
| Competition probe | ``DoorTransport`` graphql stub | real ``check_competing_prs`` GraphQL response |
| Durable ledger | ``WalkStore`` in memory | real ``StateStore`` on the ``bounty-control`` branch |

The task identity is derived from the real repo/issue pair, so the row written here is the row a
production dispatch of that issue would collide with. Rows are deleted again in ``tearDown``.

Run: python scripts/test_e2e_door_to_claim_live.py
Skip conditions are named, never silent: no token, or the issue is no longer open.
"""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_dispatch as dispatch  # noqa: E402
import cline_entry_door as door  # noqa: E402
from actions_github import GitHub, GitHubError, StateStore, task_id  # noqa: E402
from pipeline_evidence import require_evidence  # noqa: E402

REPO = os.environ.get("LIVE_SEAM_REPO", "isearchxsolve/oss-hunter-livefire")
NUMBER = int(os.environ.get("LIVE_SEAM_ISSUE", "10"))
CONTROL = os.environ.get("LIVE_SEAM_CONTROL", "isearchxsolve/bounty-control")
# The cited source file and a quote that must literally appear in it.
PATH = "live_cases/rc3b74de3bb46/duration.py"
QUOTE = "def days_to_seconds(days):"
SCOPE_QUOTE = "Correct the conversion for all nonnegative integer inputs"
REWARD_QUOTE = "one day has 86400 seconds"


def token():
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not tok:
        try:
            import subprocess
            res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                tok = res.stdout.strip()
        except Exception:
            pass
    return tok


def real_source_reader(api):
    """The door's own reader, unchanged in signature, calling the real contents endpoint."""
    from urllib.parse import quote as url_quote
    return lambda repo, name: api.api(f"repos/{repo}/contents/{url_quote(name, safe='/')}")


def candidate(context, api):
    """A row of the shape the agent writes, built from the real issue and its real file SHA."""
    issue = context["issue"]
    product = api.api(f"repos/{REPO}/contents/{PATH}")
    return {"repo": REPO, "issue": NUMBER, "url": issue["html_url"], "is_code_task": True,
            "is_founder_wound": True,
            "reward_quote": REWARD_QUOTE,
            "scope_quote": SCOPE_QUOTE,
            "admission_reason": "Owner states one bounded, reproducible conversion defect",
            "funding": {"amount": "0", "currency": "USD", "payer": (issue.get("user") or {}).get("login"),
                        "source_url": issue["html_url"]},
            "code_evidence": {"path": PATH, "sha": product["sha"], "quote": QUOTE,
                              "is_product_code": True}}


class LiveSeam(unittest.TestCase):
    api = None
    context = None
    store = None

    @classmethod
    def setUpClass(cls):
        if not token():
            raise unittest.SkipTest("No GH_TOKEN; the live seam needs the real API")
        cls.api = GitHub()
        try:
            cls.context = cls.api.issue_context(REPO, NUMBER)
        except (GitHubError, ValueError) as exc:
            raise unittest.SkipTest(f"Live issue {REPO}#{NUMBER} unreadable: {exc}")
        if str(cls.context["issue"].get("state", "")).lower() != "open":
            raise unittest.SkipTest(f"Live issue {REPO}#{NUMBER} is no longer open")
        cls.store = StateStore(cls.api, CONTROL)

    def setUp(self):
        self.identity = task_id(REPO, NUMBER)
        self.admitted = None
        # A real dispatch spends this identity's own dispatch budget (capped at 3 in the record),
        # so start from the pre-dispatch state the assertions describe. This sandbox issue is also
        # dispatched by production, so confirm the row is actually gone rather than assuming the
        # delete won the race.
        for attempt in range(5):
            self.store.delete(self.identity, "live seam probe start")
            if self.store.read(self.identity)[0] is None:
                break
            time.sleep(1)
        else:
            self.skipTest(f"identity {self.identity} is contended by a live delivery")

    def tearDown(self):
        self.store.delete(self.identity, "live seam probe end")

    def door(self):
        return door.verify_model_rows([candidate(self.context, self.api)],
                                     fetch=lambda *a: self.context["issue"],
                                     context_builder=lambda *a: self.context,
                                     admission_client=self.api,
                                     source_reader=real_source_reader(self.api))

    def test_an_admitted_row_survives_dispatch_and_the_claim_gate(self):
        # --- hop 1: the door admits the real row and writes its own proof ---------------
        verdict = self.door()
        self.assertEqual(verdict["refused"], [])
        self.assertEqual(len(verdict["admitted"]), 1)
        self.admitted = verdict["admitted"][0]
        self.assertTrue(self.admitted["sovereign_admission"])
        # A real owner request with no priced amount is admitted as unpriced, not guessed.
        self.assertEqual(self.admitted["admission"]["funding_status"], "UNPRICED_OWNER_REQUEST")
        self.assertEqual(self.admitted["admission"]["code_evidence"]["path"], PATH)

        # --- hop 2: the real dispatcher stamps and reserves it --------------------------
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=self.admitted["sovereign_admission"],
                          competition=self.admitted["competition"])
        state, sha = self.store.read(self.identity)
        self.assertEqual(state["status"], "DISPATCHED")
        self.assertIs(state["sovereign_admission"], True)
        self.assertTrue(sha, "the durable write returned no revision")

        # --- hop 3: the real claim gate reads that proof as binding ---------------------
        proof, competition = require_evidence(state, self.context)
        self.assertEqual(proof, self.admitted["admission"])
        self.assertIs(competition["blocking"], False)

    def test_the_durable_row_survives_a_fresh_store_read(self):
        """The proof must come back from the branch, not from a dict this process kept."""
        self.admitted = self.door()["admitted"][0]
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=True, competition=self.admitted["competition"])
        elsewhere, _ = StateStore(GitHub(), CONTROL).read(self.identity)
        self.assertIsNotNone(elsewhere, "the row did not survive to a fresh store reader")
        proof, _ = require_evidence(elsewhere, self.context)
        self.assertEqual(proof, self.admitted["admission"])

    def test_the_door_proof_is_bound_to_the_source_it_was_read_from(self):
        self.admitted = self.door()["admitted"][0]
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=True, competition=self.admitted["competition"])
        state, _ = self.store.read(self.identity)
        edited = {**self.context,
                  "issue": {**self.context["issue"],
                            "body": (self.context["issue"].get("body") or "") + "\n\nEdited by probe."}}
        with self.assertRaises(ValueError) as caught:
            require_evidence(state, edited)
        self.assertIn("source changed", str(caught.exception))

    def test_a_closed_issue_cannot_be_claimed(self):
        self.admitted = self.door()["admitted"][0]
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=True, competition=self.admitted["competition"])
        state, _ = self.store.read(self.identity)
        closed = {**self.context, "issue": {**self.context["issue"], "state": "closed"}}
        with self.assertRaises(ValueError):
            require_evidence(state, closed)

    def test_the_real_source_quote_is_checked_against_real_bytes(self):
        """A quote that is not in the file at its current SHA is refused by the real reader."""
        row = candidate(self.context, self.api)
        row["code_evidence"]["quote"] = "this sentence is not in the guard script"
        verdict = door.verify_model_rows([row], fetch=lambda *a: self.context["issue"],
                                        context_builder=lambda *a: self.context,
                                        admission_client=self.api,
                                        source_reader=real_source_reader(self.api))
        self.assertEqual(verdict["admitted"], [])
        self.assertEqual(verdict["refused"][0]["reason"], "PRODUCT_SOURCE_QUOTE_MISMATCH")

    def test_a_stale_file_sha_is_refused_by_the_real_reader(self):
        row = candidate(self.context, self.api)
        row["code_evidence"]["sha"] = "0" * 40
        verdict = door.verify_model_rows([row], fetch=lambda *a: self.context["issue"],
                                        context_builder=lambda *a: self.context,
                                        admission_client=self.api,
                                        source_reader=real_source_reader(self.api))
        self.assertEqual(verdict["admitted"], [])
        self.assertEqual(verdict["refused"][0]["reason"], "PRODUCT_SOURCE_REVISION_MISMATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
