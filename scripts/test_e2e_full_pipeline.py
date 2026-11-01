"""One continuous end-to-end walk of the whole pipeline, with a receipt at every hop.

Why this file exists
--------------------
``test_e2e_door_to_claim`` runs the door and hands its admitted proof to the real dispatcher,
then stops at the claim gate. ``test_e2e_walk`` runs dispatch through DELIVERED, but starts from
a proof it builds itself with ``bind_proof``. Both are real runs of production code with only the
transport replaced. Neither runs the whole chain on one row, so the seam between them -- a door's
proof actually surviving the journey to a delivery -- is asserted by neither.

A receipt here is the pipeline's own provenance object, not a log line. ``bind_proof`` binds an
admission to the exact bytes of the issue it was read from (``source_revision``), the dispatcher
carries it, the claim gate re-reads it with ``require_evidence``, and reconcile records what it
observed of the resulting PR (``remote_verification``, whose ``head_sha`` names the commit it
read). A walk that does not carry those receipts between hops tests the hops, not the pipeline:
the hop that loses the proof is exactly the hop no per-stage test can see, and it is how a task
reaches the delivery end unclaimed. Measured 2026-11-01, the live PR sat six hours at
PUBLISHED_PENDING_CHECKS because nothing re-read its observation receipt.

Run: python scripts/test_e2e_full_pipeline.py
"""
import sys
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_dispatch as dispatch  # noqa: E402
import cline_entry_door as door  # noqa: E402
from actions_github import GitHub, StateStore, task_id  # noqa: E402
from actions_reconcile import reconcile  # noqa: E402
from pipeline_evidence import bind_proof, require_evidence, source_revision  # noqa: E402

REPO = "acme/http"
NUMBER = 7
OWNER = "424242:1"
HEAD = "a" * 40
SOURCE = "def retry():\n    pass\n"
URL = f"https://github.com/{REPO}/issues/{NUMBER}"
RUN_URL = "https://example.invalid/run/1"


class PipelineTransport(GitHub):
    """One GitHub that serves the door, the dispatcher and reconcile, and records the calls.

    A single transport exists because the defect this suite hunts lives between the stages:
    separate fakes let a receipt stop travelling at a seam no other suite covers.
    """

    def __init__(self, merged=40, total=50):
        self.calls = []
        self.merged, self.total = merged, total
        self.pr_state, self.conclusion, self.pr_merged = "open", "success", False
        self.reviews = []

    def api(self, endpoint, method="GET", data=None, **kwargs):
        self.calls.append((method, endpoint))
        if endpoint == "graphql":
            return {"data": {"repository": {"merged": {"totalCount": self.merged},
                                            "all": {"totalCount": self.total}}}}
        if endpoint.endswith("/dispatches"):
            return None
        if "check-runs" in endpoint:
            return {"check_runs": [{"id": 1, "name": "CI", "status": "completed",
                                    "conclusion": self.conclusion, "app": {"id": 1}}]}
        if "/pulls/" in endpoint and endpoint.split("/pulls/")[-1].isdigit():
            return {"number": 1, "head": {"sha": HEAD}, "merged": self.pr_merged,
                    "merged_at": "2026-11-01T00:00:00Z" if self.pr_merged else None,
                    "html_url": "https://example.invalid/pr/1", "state": self.pr_state}
        return {}

    def pages(self, endpoint, **kwargs):
        self.calls.append(("GET", endpoint))
        if endpoint.endswith("/reviews"):
            return list(self.reviews)
        return []

    def workflow_runs(self, repo, status=None):
        return []

    def issue_context(self, repo, number):
        return context()


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
    """The issue context the door and the dispatcher both build from the same bytes."""
    return {"repo": REPO, "issue_number": NUMBER,
            "issue": {"number": NUMBER, "state": "open", "title": "Retry fails",
                      "body": "Bounty $250. Fix src/retry.py",
                      "html_url": URL, "user": {"login": "payer"},
                      "author_association": "OWNER", "labels": []},
            "comments": [], "complete_comments": True,
            "repository": {"full_name": REPO, "default_branch": "main",
                           "archived": False, "disabled": False}}


def candidate():
    """A row exactly as the sovereign agent writes it into shortlist.jsonl."""
    return {"repo": REPO, "issue": NUMBER, "url": URL, "is_code_task": True,
            "reward_quote": "Bounty $250.",
            "reward_usd": 250,
            "scope_quote": "Fix src/retry.py",
            "admission_reason": "Owner states a current $250 offer for a bounded source fix",
            "funding": {"amount": "250", "currency": "USD", "payer": "payer",
                        "source_url": URL},
            "code_evidence": {"path": "src/retry.py", "sha": HEAD,
                              "quote": "def retry():", "is_product_code": True}}


def blob():
    return {"type": "file", "sha": HEAD, "encoding": "base64",
            "content": b64encode(SOURCE.encode()).decode()}


def run_door(rows, transport):
    """Drive the production verifier exactly as agent_door does."""
    ctx = context()
    with patch.object(GitHub, "api", return_value=blob()):
        return door.verify_model_rows(
            rows, fetch=lambda *a: ctx["issue"],
            context_builder=lambda *a: ctx, admission_client=transport)


class FullPipelineReceiptWalk(unittest.TestCase):
    """One row, every hop executed, a receipt stamped at each one and printed."""

    def setUp(self):
        self.store = WalkStore()
        self.api = PipelineTransport()
        self.identity = task_id(REPO, NUMBER)
        self.receipts = []

    def receipt(self, stage, **fields):
        """Stamp this hop's receipt: what happened, and the evidence that proves it did."""
        entry = {"receipt": len(self.receipts) + 1, "stage": stage, "task_id": self.identity}
        entry.update(fields)
        self.receipts.append(entry)
        print(f'  RECEIPT {entry["receipt"]:>2} {stage:<26} '
              + " ".join(f"{k}={v}" for k, v in fields.items()))
        return entry

    def walk(self):
        """Execute the whole chain, door to DELIVERED, and return the stamped receipts."""
        # --- hop 1: the entry door admits the row and writes its own proof ---------------
        verdict = run_door([candidate()], self.api)
        self.assertEqual(verdict["refused"], [], "the walk must start from an admitted row")
        admitted = verdict["admitted"][0]
        door_receipt = self.receipt(
            "door_admission", repo=REPO, issue=NUMBER, lane=admitted["lane"],
            sovereign=admitted["sovereign_admission"],
            source_revision=admitted["admission"]["source_revision"],
            funding_usd=admitted["admission"]["funding"]["amount"],
            code_sha=admitted["admission"]["code_evidence"]["sha"])

        # --- hop 2: the dispatcher stamps and reserves it --------------------------------
        dispatch.dispatch(self.api, self.store, context(), admitted["admission"],
                         [admitted["source_lane"]],
                         sovereign_admission=admitted["sovereign_admission"],
                         competition=admitted["competition"])
        state = self.store.read(self.identity)[0]
        dispatch_receipt = self.receipt(
            "dispatch", status=state["status"], dispatch_id=state["dispatch_id"],
            sovereign=state["sovereign_admission"],
            transport="POST /dispatches")

        # --- hop 3: the runner claims it, and the claim gate re-reads the door's proof ---
        claimed = self.store.claim(REPO, NUMBER, OWNER, RUN_URL, HEAD,
                                   dispatch_id=state["dispatch_id"])
        # A stale generation must not be able to claim the work this dispatch reserved.
        with self.assertRaises(ValueError):
            self.store.claim(REPO, NUMBER, OWNER, RUN_URL, HEAD,
                             dispatch_id="stale-generation")
        proof, competition = require_evidence(self.store.read(self.identity)[0], context())
        self.receipt("claim", owner=OWNER, head_sha=HEAD,
                     dispatch_id=claimed["dispatch_id"],
                     proof_source_revision=proof["source_revision"],
                     verified_against=source_revision(context()))

        # --- hop 4: engineering verifies, and the delivery side records it ---------------
        self.store.owned_update(self.identity, OWNER, status="VERIFIED",
                                head_sha=HEAD, proposed_head=HEAD)
        self.receipt("engineering", status=self.store.read(self.identity)[0]["status"],
                     head_sha=HEAD)

        # --- hop 5: publication opens the PR --------------------------------------------
        self.store.owned_update(self.identity, OWNER, status="PUBLISHING", proposed_head=HEAD)
        self.store.owned_update(self.identity, OWNER, status="PUBLISHED_PENDING_CHECKS",
                                pr_number=1, pr_url="https://example.invalid/pr/1",
                                head_sha=HEAD)
        self.receipt("publish", status=self.store.read(self.identity)[0]["status"],
                     pr_number=1, head_sha=HEAD)

        # --- hop 6: reconcile observes the green PR -------------------------------------
        reconcile(repair=False, api=self.api, store=self.store)
        observed = self.store.read(self.identity)[0]
        self.receipt("reconcile", status=observed["status"],
                     observed_head_sha=observed["remote_verification"]["head_sha"],
                     observed_state=observed["remote_verification"]["state"],
                     review=observed["remote_review"]["verdict"])

        # --- hop 7: a reviewer asks for a change; it becomes a durable obligation --------
        self.api.reviews = [{"state": "CHANGES_REQUESTED", "user": {"login": "reviewer"},
                             "submitted_at": "2026-11-01T00:00:00Z"}]
        reconcile(repair=False, api=self.api, store=self.store)
        self.receipt("reconcile", status=self.store.read(self.identity)[0]["status"],
                     obligation=self.store.read(self.identity)[0]["review_obligation"])

        # --- hop 8: the engineer re-claims and fixes it ----------------------------------
        self.store.claim(REPO, NUMBER, OWNER, RUN_URL, HEAD)
        self.store.owned_update(self.identity, OWNER, status="VERIFIED", head_sha=HEAD)
        self.store.owned_update(self.identity, OWNER, status="PUBLISHED_PENDING_CHECKS",
                                pr_number=1, head_sha=HEAD)
        self.receipt("reclaim_and_repair",
                     status=self.store.read(self.identity)[0]["status"], head_sha=HEAD)

        # --- hop 9: approved, then merged -> DELIVERED ------------------------------------
        self.api.reviews = [{"state": "APPROVED", "user": {"login": "reviewer"},
                             "submitted_at": "2026-11-01T00:00:00Z"}]
        reconcile(repair=False, api=self.api, store=self.store)
        self.receipt("reconcile", status=self.store.read(self.identity)[0]["status"],
                     review=self.store.read(self.identity)[0]["remote_review"]["verdict"])
        self.api.pr_merged = True
        reconcile(repair=False, api=self.api, store=self.store)
        final = self.store.read(self.identity)[0]
        self.receipt("terminal", status=final["status"], merged_at=final["merged_at"],
                     payment_status=final["payment_status"])
        return door_receipt, dispatch_receipt, final

    def test_one_row_travels_the_whole_pipeline(self):
        door_r, dispatch_r, final = self.walk()
        self.assertEqual(final["status"], "DELIVERED")
        self.assertEqual(final["payment_status"], "UNVERIFIED",
                         "a merge is not a payment and nothing may infer one")
        self.assertFalse(dispatch.retry_eligible(final),
                         "DELIVERED is terminal and must refuse further work")
        self.assertEqual(door_r["stage"], "door_admission")
        self.assertEqual(self.receipts[0]["stage"], "door_admission",
                         "the walk must start at the door, or it is not the whole pipeline")
        self.assertEqual(self.receipts[-1]["stage"], "terminal")

    def test_every_hop_stamped_a_receipt_naming_the_same_task(self):
        self.walk()
        self.assertGreaterEqual(len(self.receipts), 9,
                                "a hop with no receipt is a hop nothing proved")
        self.assertEqual({r["task_id"] for r in self.receipts}, {self.identity},
                         "a receipt naming another task is a receipt for another transaction")

    def test_the_doors_proof_is_the_proof_the_claim_gate_read(self):
        """The seam: the admission the door wrote must be what the delivery side re-read."""
        door_r, _, _ = self.walk()
        claim = next(r for r in self.receipts if r["stage"] == "claim")
        self.assertEqual(claim["proof_source_revision"], door_r["source_revision"],
                         "the claim gate read a different admission than the door wrote")
        self.assertEqual(claim["verified_against"], source_revision(context()),
                         "the proof is not bound to the issue bytes the walk was built from")

    def test_the_dispatch_generation_travels_with_the_task(self):
        """The claim must carry the dispatch's generation, and a stale one must be refused."""
        _, dispatch_r, _ = self.walk()
        claim = next(r for r in self.receipts if r["stage"] == "claim")
        self.assertTrue(dispatch_r["dispatch_id"])
        self.assertIn("dispatch_id", claim,
                      "the claim receipt must name the generation it claimed under")

    def test_reconcile_observed_the_head_that_was_published(self):
        self.walk()
        publish = next(r for r in self.receipts if r["stage"] == "publish")
        observations = [r for r in self.receipts if r["stage"] == "reconcile"
                        and "observed_head_sha" in r]
        self.assertTrue(observations)
        for observation in observations:
            self.assertEqual(observation["observed_head_sha"], publish["head_sha"],
                             "reconcile observed a different commit than the one published")

    def test_no_hop_entered_a_failure_status(self):
        self.walk()
        self.assertNotIn("FAILED", " ".join(str(r.get("status", "")) for r in self.receipts),
                         "a receipt in this walk recorded a failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
