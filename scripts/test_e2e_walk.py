"""One continuous end-to-end walk: DISPATCHING -> DELIVERED, on a single record.

Why this file exists
--------------------
The existing end-to-end coverage is real but split. ``test_e2e_flow`` asserts the shape of the
status graph (no orphans, every waiting status observed, every fault retryable) and
``FullLifecycleTests`` walks a task from ``AWAITING_REVIEW`` to ``DELIVERED``. Neither walks the
front half. ``test_every_status_is_terminal_or_has_a_way_forward`` declares the chain

    DISPATCHED -> CLAIMED -> ENGINEERING -> VERIFIED -> PUBLISHING -> ...

as a list literal and then asserts properties of the list. A list literal is a claim about the
flow, not a run of it. Nothing executed the hops, so nothing could catch a hop that does not
exist.

That is not hypothetical. ``ENGINEERING`` is declared in the chain, listed in
``ACTIVE_STATUSES``, accepted by the claim gate and read by the reconcile loop -- but no
production module ever writes it. The real path is ``CLAIMED`` -> ``VERIFIED``. The declared
chain has a status in it that the pipeline cannot enter.

This module walks the real thing: one store, one task, one transport, driven through the actual
``dispatch``, ``StateStore.claim``, ``owned_update`` and ``reconcile`` functions in order, with
every hop asserted. It is the acceptance test for "full flow e2e, pipeline wide".

Run: python scripts/test_e2e_walk.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_dispatch as dispatch  # noqa: E402
import actions_reconcile as reconcile_mod  # noqa: E402
from actions_github import GitHub, StateStore, task_id  # noqa: E402
from actions_reconcile import reconcile  # noqa: E402
from pipeline_evidence import bind_proof  # noqa: E402

REPO = "acme/http"
NUMBER = 7
OWNER = "424242:1"
HEAD = "a" * 40


class WalkStore(StateStore):
    """The real StateStore contract, in memory.

    Only the transport is replaced. ``claim``, ``owned_update``, ``assert_owner`` and every
    ownership gate stay the production implementations, so the walk exercises the real rules
    rather than a friendlier copy of them.
    """

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


class WalkTransport(GitHub):
    """A GitHub that answers the endpoints the pipeline actually calls, and records them."""

    def __init__(self):
        self.calls = []
        self.merged = False
        self.pr_state = "open"
        self.conclusion = "success"
        self.reviews = []

    def api(self, endpoint, method="GET", data=None, **kwargs):
        self.calls.append((method, endpoint))
        if endpoint.endswith("/dispatches"):
            return None
        if endpoint.endswith("/check-runs?per_page=100&page=1"):
            return {"check_runs": [{"id": 1, "name": "CI", "status": "completed",
                                    "conclusion": self.conclusion, "app": {"id": 1}}]}
        if "/pulls/" in endpoint and endpoint.split("/pulls/")[-1].isdigit():
            return {"number": 1, "head": {"sha": HEAD}, "merged": self.merged,
                    "merged_at": "2026-11-01T00:00:00Z" if self.merged else None,
                    "html_url": "https://example.invalid/pr/1", "state": self.pr_state}
        if "/actions/runs/" in endpoint:
            return {"status": "in_progress", "conclusion": None,
                    "html_url": "https://example.invalid/run"}
        return {}

    def pages(self, endpoint, **kwargs):
        self.calls.append(("GET", endpoint))
        if endpoint.endswith("/reviews"):
            return list(self.reviews)
        return []

    def workflow_runs(self, repo, status=None):
        return []

    def issue_context(self, repo, number):
        return {}


def context():
    return {"repo": REPO, "issue_number": NUMBER, "title": "Retry fails",
            "body": "Fix src/retry.py",
            "issue": {"state": "open", "title": "Retry fails",
                      "body": "Bounty $250. Fix src/retry.py"},
            "comments": [], "complete_comments": True,
            "repository": {"full_name": REPO, "default_branch": "main"}}


def proof():
    return bind_proof({"funding": {"amount": "250", "usd_value": "250"}}, context())


def competition():
    """The door's competition stamp. Dispatch refuses to run without one."""
    return {"blocking": False, "nominal": [], "verified": True, "verdict": "clear"}


class FullPipelineWalkTests(unittest.TestCase):
    """One task, one record, every hop executed in order."""

    def setUp(self):
        self.store = WalkStore()
        self.api = WalkTransport()
        self.identity = task_id(REPO, NUMBER)

    def status(self):
        return self.store.read(self.identity)[0]["status"]

    def test_dispatch_to_delivered_on_one_record(self):
        # --- hop 1: dispatch reserves the task and acknowledges the transport -----------
        dispatch.dispatch(self.api, self.store, context(), proof(), ["bounty"],
                          competition=competition())
        self.assertEqual(self.status(), "DISPATCHED",
                         "dispatch must leave the record DISPATCHED, not DISPATCHING")
        record = self.store.read(self.identity)[0]
        self.assertTrue(record["dispatch_id"], "a dispatch without a generation is unclaimable")
        self.assertTrue(any(m == "POST" and e.endswith("/dispatches") for m, e in self.api.calls),
                        "the dispatch was never sent to the transport")

        # --- hop 2: the runner claims it, carrying the dispatch generation --------------
        claimed = self.store.claim(REPO, NUMBER, OWNER, "https://example.invalid/run",
                                   HEAD, dispatch_id=record["dispatch_id"])
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertEqual(claimed["owner"], OWNER)

        # --- hop 3: engineering verifies, and the delivery side records it --------------
        # The production path is CLAIMED -> VERIFIED. There is no ENGINEERING hop; see the
        # module docstring. This asserts what the code does, not what the chain claims.
        self.store.owned_update(self.identity, OWNER, status="VERIFIED",
                                head_sha=HEAD, proposed_head=HEAD)
        self.assertEqual(self.status(), "VERIFIED")

        # --- hop 4: publication opens the PR -------------------------------------------
        self.store.owned_update(self.identity, OWNER, status="PUBLISHING", proposed_head=HEAD)
        self.assertEqual(self.status(), "PUBLISHING")
        self.store.owned_update(self.identity, OWNER, status="PUBLISHED_PENDING_CHECKS",
                                pr_number=1, pr_url="https://example.invalid/pr/1",
                                head_sha=HEAD)
        self.assertEqual(self.status(), "PUBLISHED_PENDING_CHECKS")

        # --- hop 5: reconcile observes CI green and moves it to review ------------------
        reconcile(repair=False, api=self.api, store=self.store)
        self.assertEqual(self.status(), "AWAITING_REVIEW",
                         "a green PR with no reviews must be awaiting review")

        # --- hop 6: a reviewer asks for a change; it becomes a durable obligation -------
        self.api.reviews = [{"state": "CHANGES_REQUESTED", "user": {"login": "r"},
                             "submitted_at": "2026-11-01T00:00:00Z"}]
        reconcile(repair=False, api=self.api, store=self.store)
        self.assertEqual(self.status(), "CHANGES_REQUESTED")
        self.assertEqual(self.store.read(self.identity)[0]["review_obligation"], "address_review")
        self.assertTrue(dispatch.retry_eligible({"status": "CHANGES_REQUESTED"}),
                        "a change request must be work the pipeline can pick back up")

        # --- hop 7: the engineer re-claims and fixes it ---------------------------------
        reclaimed = self.store.claim(REPO, NUMBER, OWNER, "https://example.invalid/run2", HEAD)
        self.assertEqual(reclaimed["status"], "CLAIMED",
                         "the claim gate must let a change request back into engineering")
        self.store.owned_update(self.identity, OWNER, status="VERIFIED", head_sha=HEAD)
        self.store.owned_update(self.identity, OWNER, status="PUBLISHED_PENDING_CHECKS",
                                pr_number=1, pr_url="https://example.invalid/pr/1",
                                head_sha=HEAD)

        # --- hop 8: approved, green, merged -> DELIVERED, payment still unknown ---------
        self.api.reviews = [{"state": "APPROVED", "user": {"login": "r"},
                             "submitted_at": "2026-11-01T00:00:00Z"}]
        reconcile(repair=False, api=self.api, store=self.store)
        self.assertEqual(self.status(), "AWAITING_REVIEW")

        self.api.merged, self.api.pr_state = True, "closed"
        reconcile(repair=False, api=self.api, store=self.store)
        final = self.store.read(self.identity)[0]
        self.assertEqual(final["status"], "DELIVERED")
        self.assertEqual(final["payment_status"], "UNVERIFIED",
                         "a merge is not a payment and nothing may infer one")
        self.assertFalse(dispatch.retry_eligible(final),
                         "DELIVERED is terminal and must refuse further work")

    def test_every_hop_lands_in_a_status_the_graph_knows(self):
        """No hop may write a status that is neither terminal, observed, nor retryable."""
        observed = set(reconcile_mod.PR_OBSERVATION_STATUSES)
        terminal = {"DELIVERED", "CLOSED_UNMERGED"}
        active = set(reconcile_mod.ACTIVE_STATUSES)
        written = []

        dispatch.dispatch(self.api, self.store, context(), proof(), ["bounty"],
                          competition=competition())
        written.append(self.status())
        record = self.store.read(self.identity)[0]
        written.append(self.store.claim(REPO, NUMBER, OWNER, "https://example.invalid/run",
                                        HEAD, dispatch_id=record["dispatch_id"])["status"])
        for status in ("VERIFIED", "PUBLISHING", "PUBLISHED_PENDING_CHECKS"):
            written.append(self.store.owned_update(self.identity, OWNER, status=status,
                                                   pr_number=1, head_sha=HEAD)["status"])
        reconcile(repair=False, api=self.api, store=self.store)
        written.append(self.status())

        for status in written:
            self.assertTrue(
                status in observed or status in terminal or status in active
                or status.startswith("FAILED")
                or status in ("DISPATCHING", "DISPATCHED"),
                status + " is written but is neither observed, terminal, active, nor retryable")

    def test_declared_chain_matches_what_the_code_can_enter(self):
        """The chain the graph test declares must be reachable, not just listable.

        Reachability is taken from the walk itself, not from grepping source: a status written
        inside a conditional expression is still reachable, and a regex over source cannot tell
        the difference. The walk is the evidence.
        """
        transitions = []

        dispatch.dispatch(self.api, self.store, context(), proof(), ["bounty"],
                          competition=competition())
        transitions.append(self.status())
        record = self.store.read(self.identity)[0]
        transitions.append(self.store.claim(REPO, NUMBER, OWNER, "https://example.invalid/run",
                                            HEAD, dispatch_id=record["dispatch_id"])["status"])
        for status in ("VERIFIED", "PUBLISHING", "PUBLISHED_PENDING_CHECKS"):
            transitions.append(self.store.owned_update(
                self.identity, OWNER, status=status, pr_number=1, head_sha=HEAD)["status"])
        reconcile(repair=False, api=self.api, store=self.store)
        transitions.append(self.status())
        self.api.merged, self.api.pr_state = True, "closed"
        reconcile(repair=False, api=self.api, store=self.store)
        transitions.append(self.status())

        declared = ["DISPATCHED", "CLAIMED", "VERIFIED", "PUBLISHING",
                    "PUBLISHED_PENDING_CHECKS", "AWAITING_REVIEW", "DELIVERED"]
        for status in declared:
            self.assertIn(status, transitions,
                          status + " is declared in the lifecycle but the walk never enters it")

        # The declared chain must also be ordered: each hop after the first must follow the
        # one before it, or the "chain" is a bag of statuses rather than a path.
        positions = [transitions.index(status) for status in declared]
        self.assertEqual(positions, sorted(positions),
                         "the declared chain is not the order the walk actually takes")

    def test_engineering_is_declared_but_never_written(self):
        """ENGINEERING is in the lifecycle, the claim gate and the sweeper, but nothing writes it.

        Pinned so the discrepancy stays visible. If a future change starts writing ENGINEERING,
        this fails and the declared chain should be updated to include it.
        """
        here = Path(__file__).resolve().parent
        writers = ""
        for module in ("actions_delivery.py", "actions_github.py", "actions_dispatch.py",
                       "actions_reconcile.py"):
            writers += (here / module).read_text(encoding="utf-8")
        self.assertNotIn('status="ENGINEERING"', writers,
                         "ENGINEERING is now written -- add it to the declared chain")
        self.assertNotIn('"status": "ENGINEERING"', writers,
                         "ENGINEERING is now written -- add it to the declared chain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
