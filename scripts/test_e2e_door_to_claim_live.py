"""The door-to-claim seam, wired to a real GitHub issue, on an ephemeral durable namespace.

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
| Durable ledger | ``WalkStore`` in memory | real ``StateStore``, real CAS, on an ephemeral ``live-probes/*`` branch |

Why the namespace is ephemeral (and why it is not the production ledger)
-----------------------------------------------------------------------
A probe that writes ``fleet-state/<identity>.json`` on the production ``bounty-control`` branch
is not isolated, it is racing: concurrent probe runs contend on the same blob, and the live
sweeper can read a probe's ``DISPATCHING``/``DISPATCHED`` row and dispatch real engineering work
from it. Both were measurable before this file named its own namespace -- the probe had to delete
a row production was also writing, and could only ask whether it had won the race.

So the durable ledger here is a branch of ``live-probes/door-to-claim-<uuid>`` in a repository
that has no ``repository_dispatch`` receiver, and ``setUpClass`` proves both facts before it
writes anything. Isolation is a property of *where* the bytes go, never of *what* the gates decide:
the identity is still ``task_id(repo, issue)``, ``claim``/``mutate``/``owned_update``/``delete``
are the production implementations unchanged, and every refusal below is raised by the real gate.

Run: python scripts/test_e2e_door_to_claim_live.py
Skip conditions are named, never silent: no token, the issue is no longer open, the configured
repository can act on a dispatch, or a namespace branch cannot be reclaimed.
"""
import json
import os
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote as url_quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_dispatch as dispatch  # noqa: E402
import cline_entry_door as door  # noqa: E402
from actions_github import GitHub, GitHubError, StateStore, task_id  # noqa: E402
from pipeline_evidence import require_evidence, source_revision  # noqa: E402

# The fixture issue: a real open issue whose body quotes a real file in the same repository.
REPO = os.environ.get("LIVE_SEAM_REPO", "isearchxsolve/oss-hunter-livefire")
NUMBER = int(os.environ.get("LIVE_SEAM_ISSUE", "10"))
# The durable ledger this probe writes. Deliberately NOT the production control repository:
# the sandbox has no repository_dispatch receiver (checked below), so a dispatch sent here is a
# real API call with no capable receiver behind it.
LEDGER = os.environ.get("LIVE_SEAM_LEDGER", REPO)
PRODUCTION_LEDGER = "isearchxsolve/bounty-control"
# ``LIVE_SEAM_BRANCH`` pins a namespace so a repaired run can resume its own evidence (Baba Law
# 86); the default is a fresh one, so concurrent runs never share a row.
BRANCH_PREFIX = "live-probes/door-to-claim-"
# The cited source file and a quote that must literally appear in it.
PATH = "live_cases/rc3b74de3bb46/duration.py"
QUOTE = "def days_to_seconds(days):"
SCOPE_QUOTE = "Correct the conversion for all nonnegative integer inputs"
REWARD_QUOTE = "one day has 86400 seconds"
OWNER = "live-seam-probe:1"


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


class RecordingWire(GitHub):
    """The real transport, counting the dispatch POSTs that actually left the process.

    A recording wrapper, not a stub: every call is made for real and the answer is GitHub's.
    It exists because "the second dispatch was refused" and "no second dispatch was sent" are
    two different claims, and only the second one is the invariant (Baba Law 86: never create a
    duplicate external effect).
    """

    def __init__(self):
        super().__init__()
        self.dispatches = []

    def api(self, endpoint, method="GET", data=None, paginate=False):
        result = super().api(endpoint, method, data, paginate=paginate)
        if method == "POST" and str(endpoint).endswith("/dispatches"):
            self.dispatches.append({"endpoint": endpoint,
                                    "dispatch_id": ((data or {}).get("client_payload") or {}).get("dispatch_id")})
        return result


class LiveSeam(unittest.TestCase):
    api = None
    context = None
    store = None
    branch = None
    identities = ()

    @classmethod
    def setUpClass(cls):
        if not token():
            raise unittest.SkipTest("No GH_TOKEN; the live seam needs the real API")
        if LEDGER.lower() == PRODUCTION_LEDGER.lower():
            raise unittest.SkipTest(
                "LIVE_SEAM_LEDGER names the production control ledger; a live probe must not "
                "write the rows the fleet is reconciling. Point it at a sandbox repository.")
        cls.api = RecordingWire()
        try:
            cls.context = cls.api.issue_context(REPO, NUMBER)
        except (GitHubError, ValueError) as exc:
            raise unittest.SkipTest(f"Live issue {REPO}#{NUMBER} unreadable: {exc}")
        if str(cls.context["issue"].get("state", "")).lower() != "open":
            raise unittest.SkipTest(f"Live issue {REPO}#{NUMBER} is no longer open")
        receiver = cls.dispatch_receiver()
        if receiver:
            raise unittest.SkipTest(
                f"{LEDGER} declares a repository_dispatch receiver ({receiver}); a probe "
                "dispatch would start real engineering work instead of being accepted and dropped")
        cls.branch = os.environ.get("LIVE_SEAM_BRANCH") or (BRANCH_PREFIX + uuid.uuid4().hex)
        cls.store = StateStore(cls.api, LEDGER)
        cls.store.branch = cls.branch
        cls.store.ensure()
        cls.identities = (task_id(REPO, NUMBER),)
        print(json.dumps({"phase": "LIVE_SEAM_NAMESPACE", "ledger": LEDGER,
                          "branch": cls.branch, "identity": cls.identities[0],
                          "issue": f"{REPO}#{NUMBER}"}), flush=True)

    @classmethod
    def dispatch_receiver(cls):
        """The workflow path that would accept a dispatch in this repository, or None.

        The probe must be able to POST ``/dispatches`` for real without starting work. A
        repository is only a safe target while no workflow declares the event, so the fact is
        read from the workflow bytes rather than assumed from the repository's name.
        """
        import base64
        try:
            workflows = cls.api.api(f"repos/{LEDGER}/actions/workflows").get("workflows") or []
        except (GitHubError, AttributeError):
            raise unittest.SkipTest(f"{LEDGER} workflow list is unreadable; dispatch safety unproven")
        for workflow in workflows:
            blob = cls.api.api(f"repos/{LEDGER}/contents/{workflow['path']}")
            text = base64.b64decode(blob.get("content") or "").decode("utf-8", "replace")
            if "repository_dispatch" in text:
                return workflow["path"]
        return None

    @classmethod
    def tearDownClass(cls):
        """Remove every probe row, then the namespace itself, and prove both are gone.

        Two mechanisms with two jobs. ``StateStore.delete`` exercises the production delete path
        (404 is success, 409 re-reads the CAS revision) once per identity, and deleting the ref
        afterwards is authoritative for anything a failed test left behind: one atomic operation
        removes every byte the probe ever wrote, whether or not this process remembers the row.
        """
        if cls.store is None:
            return
        for identity in cls.identities:
            cls.reclaim(cls.store, identity)
        cls.drop_branch(cls.api, LEDGER, cls.branch)
        print(json.dumps({"phase": "LIVE_SEAM_NAMESPACE_RECLAIMED", "ledger": LEDGER,
                          "branch": cls.branch}), flush=True)

    @staticmethod
    def reclaim(store, identity, tries=8):
        """Delete a durable row and confirm the branch no longer serves it.

        The contents API is read-after-write consistent in its own right but not across
        replicas: a delete that succeeded can still be followed by a read that answers with the
        old blob. So the loop re-reads after every delete and only returns once the row is
        actually absent; a row that survives every attempt is a leak and is named as one.
        """
        for attempt in range(tries):
            store.delete(identity, "live seam probe reclaim")
            if store.read(identity)[0] is None:
                return None
            time.sleep(min(0.5 * (attempt + 1), 3))
        raise AssertionError(f"durable row {identity} survived {tries} deletes on branch "
                             f"{store.branch} of {store.repo}; the probe leaked state")

    @staticmethod
    def drop_branch(api, repo, branch, tries=6):
        """Delete the ephemeral namespace ref and confirm it is gone."""
        if not branch:
            return None
        for attempt in range(tries):
            try:
                api.api(f"repos/{repo}/git/refs/heads/{branch}", "DELETE")
            except GitHubError as exc:
                if not any(code in str(exc) for code in ("404", "Not Found", "422")):
                    if attempt == tries - 1:
                        raise
            try:
                api.api(f"repos/{repo}/git/ref/heads/{branch}")
            except GitHubError as exc:
                if "404" in str(exc):
                    return None
                if attempt == tries - 1:
                    raise
            time.sleep(min(0.5 * (attempt + 1), 3))
        raise AssertionError(f"ephemeral namespace {branch} of {repo} still exists; "
                             "the probe leaked a branch")

    def setUp(self):
        self.identity = task_id(REPO, NUMBER)
        self.admitted = None
        if self.api and hasattr(self.api, "dispatches"):
            self.api.dispatches.clear()
        # The namespace is fresh, so an existing row can only be this probe's own leftover (a
        # pinned LIVE_SEAM_BRANCH) or a previous test in this class. Starting from the durable
        # absence the assertions describe is the precondition; contending with production is
        # no longer possible by construction.
        self.reclaim(self.store, self.identity)

    def tearDown(self):
        self.reclaim(self.store, self.identity)

    def door(self):
        return door.verify_model_rows([candidate(self.context, self.api)],
                                      fetch=lambda *a: self.context["issue"],
                                      context_builder=lambda *a: self.context,
                                      admission_client=self.api,
                                      source_reader=real_source_reader(self.api))

    def dispatch_admitted(self):
        """Admit the real row, dispatch it through the real dispatcher, return the row."""
        verdict = self.door()
        self.assertEqual(verdict["refused"], [], "the fixture row must be admissible")
        self.admitted = verdict["admitted"][0]
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=self.admitted["sovereign_admission"],
                          competition=self.admitted["competition"])
        state, sha = self.store.read(self.identity)
        self.assertIsNotNone(state, "the dispatch did not reach the durable ledger")
        self.assertTrue(sha, "the durable write returned no revision")
        return state

    def state(self):
        return self.store.read(self.identity)[0]

    # --- hop 1-3: the seam itself ------------------------------------------------------------

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

    def test_the_durable_row_survives_a_fresh_store_reader(self):
        """The proof must come back from the branch, not from a dict this process kept."""
        self.dispatch_admitted()
        elsewhere = StateStore(GitHub(), LEDGER)
        elsewhere.branch = self.branch
        record, _ = elsewhere.read(self.identity)
        self.assertIsNotNone(record, "the row did not survive to a fresh store reader")
        proof, _ = require_evidence(record, self.context)
        self.assertEqual(proof, self.admitted["admission"])

    def test_the_proof_revision_is_the_real_issue_revision(self):
        """The bound revision is recomputed from live bytes, so lineage is measured, not assumed."""
        state = self.dispatch_admitted()
        bound = state["admission"]["source_revision"]
        self.assertEqual(bound, source_revision(self.context),
                         "the door bound a revision the live issue bytes do not produce")
        self.assertEqual(state["admission"]["task_id"], self.identity)

    def test_the_door_proof_is_bound_to_the_source_it_was_read_from(self):
        self.dispatch_admitted()
        edited = {**self.context,
                  "issue": {**self.context["issue"],
                            "body": (self.context["issue"].get("body") or "") + "\n\nEdited by probe."}}
        with self.assertRaises(ValueError) as caught:
            require_evidence(self.state(), edited)
        self.assertIn("source changed", str(caught.exception))

    def test_a_closed_issue_cannot_be_claimed(self):
        self.dispatch_admitted()
        closed = {**self.context, "issue": {**self.context["issue"], "state": "closed"}}
        with self.assertRaises(ValueError):
            require_evidence(self.state(), closed)

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
        """A genuine blob revision that is not this file's revision, not an invented constant."""
        row = candidate(self.context, self.api)
        current = row["code_evidence"]["sha"]
        stale = self.prior_revision() or self.other_blob(current)
        self.assertNotEqual(stale, current, "no distinct real revision was available to test with")
        row["code_evidence"]["sha"] = stale
        verdict = door.verify_model_rows([row], fetch=lambda *a: self.context["issue"],
                                         context_builder=lambda *a: self.context,
                                         admission_client=self.api,
                                         source_reader=real_source_reader(self.api))
        self.assertEqual(verdict["admitted"], [])
        self.assertEqual(verdict["refused"][0]["reason"], "PRODUCT_SOURCE_REVISION_MISMATCH")

    def prior_revision(self):
        """The revision this file had before its current one, read from the real history."""
        try:
            commits = self.api.api(f"repos/{REPO}/commits?path={url_quote(PATH, safe='/')}&per_page=2")
        except GitHubError:
            return None
        if not isinstance(commits, list) or len(commits) < 2:
            return None
        older = ((commits[-1].get("commit") or {}).get("tree") or {}).get("sha")
        if not older:
            return None
        # A tree is not a blob revision. Read the same path out of the older commit's tree so
        # the value handed to the door is a revision this file really had, which is exactly
        # what a stale pointer left behind by an earlier read looks like.
        tree = self.api.api(f"repos/{REPO}/git/trees/{older}?recursive=1")
        for entry in tree.get("tree") or []:
            if entry.get("type") == "blob" and entry.get("path") == PATH:
                return entry["sha"]
        return None

    def other_blob(self, current):
        """A real blob revision in this repository that is not this file's revision."""
        branch = (self.context.get("repository") or {}).get("default_branch") or "main"
        tree = self.api.api(f"repos/{REPO}/git/trees/{branch}?recursive=1")
        for entry in tree.get("tree") or []:
            if entry.get("type") == "blob" and entry.get("sha") != current:
                return entry["sha"]
        return None

    # --- negative boundaries on the live wire -------------------------------------------------

    def harness_sha(self):
        """The real head commit of the ledger repository, used as the recorded harness."""
        if not getattr(LiveSeam, "_harness", None):
            LiveSeam._harness = self.api.api(f"repos/{LEDGER}/commits/HEAD")["sha"]
        return LiveSeam._harness

    def claim_raw(self, owner=OWNER, dispatch_id=None):
        """The production claim gate, on the real branch, with real CAS."""
        return self.store.claim(REPO, NUMBER, owner, RUN_URL, self.harness_sha(),
                                dispatch_id=dispatch_id)

    def claim_gate(self, context):
        """The two gates ``actions_delivery.claim`` composes, in the order it applies them.

        ``claim()`` in the delivery adapter first re-reads the door's proof against the live
        issue bytes (``require_evidence``) and only then reserves the task (``StateStore.claim``).
        Composing the same two production functions here means a refusal below is raised by the
        gate that actually runs, not by a copy of its rules.
        """
        state = self.state()
        proof, _ = require_evidence(state, context)
        return proof, self.claim_raw(dispatch_id=state["dispatch_id"])

    def redispatch(self):
        dispatch.dispatch(self.api, self.store, self.context, self.admitted["admission"],
                          [self.admitted["source_lane"]],
                          sovereign_admission=self.admitted["sovereign_admission"],
                          competition=self.admitted["competition"])

    @staticmethod
    def expired(seconds=3600):
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()

    def seed(self, **fields):
        """Write a durable row of this task's identity with the given facts, via real CAS."""
        base = {"task_id": self.identity, "repo": REPO, "issue_number": NUMBER,
                "probe_fixture": True}
        return self.store.mutate(self.identity, lambda old: {**base, **fields})

    def test_a_duplicate_dispatch_is_refused_naming_the_durable_state(self):
        """An already reserved task cannot be dispatched again, and no second POST leaves."""
        state = self.dispatch_admitted()
        self.assertEqual(state["status"], "DISPATCHED")
        self.assertEqual(state["dispatch_attempt"], 1)
        sent, before = len(self.api.dispatches), self.state()
        self.assertEqual(sent, 1, "the first dispatch must have reached the transport")

        with self.assertRaises(ValueError) as caught:
            self.redispatch()
        self.assertIn("Existing durable task state: DISPATCHED", str(caught.exception),
                      "the refusal must name the durable state it refused")
        self.assertEqual(len(self.api.dispatches), sent,
                         "a refused dispatch still created the external effect")
        self.assertEqual(self.state(), before, "a refused dispatch mutated the ledger")

        # The same rule holds once the work is owned rather than merely reserved.
        claimed = self.claim_raw(dispatch_id=state["dispatch_id"])
        self.assertEqual(claimed["status"], "CLAIMED")
        sent, before = len(self.api.dispatches), self.state()
        with self.assertRaises(ValueError) as caught:
            self.redispatch()
        self.assertIn("Existing durable task state: CLAIMED", str(caught.exception))
        self.assertEqual(len(self.api.dispatches), sent,
                         "a refused dispatch on a claimed task still created the external effect")
        self.assertEqual(self.state(), before, "a refused dispatch mutated the claimed row")

    def test_a_changed_source_refuses_the_claim_before_any_state_change(self):
        """The claim gate refuses on the door's revision the moment the issue bytes move."""
        state = self.dispatch_admitted()
        bound = state["admission"]["source_revision"]
        self.assertEqual(bound, source_revision(self.context),
                         "the bound proof is not the proof the live issue bytes produce")

        edited = {**self.context,
                  "issue": {**self.context["issue"],
                            "body": (self.context["issue"].get("body") or "")
                                    + "\n\nScope widened by the owner while the task waited."}}
        self.assertNotEqual(source_revision(edited), bound,
                            "the probe did not actually change the source revision")
        before = self.state()
        with self.assertRaises(ValueError) as caught:
            self.claim_gate(edited)
        self.assertIn("source changed", str(caught.exception))
        self.assertEqual(self.state(), before,
                         "a claim on changed source mutated the durable row")
        self.assertEqual(self.state()["status"], "DISPATCHED",
                         "the claimed status must not have advanced")

        # Positive control: the same gate admits the task while the source is unchanged, so the
        # refusal above is about the bytes and not about the gate refusing everything.
        proof, claimed = self.claim_gate(self.context)
        self.assertEqual(proof["source_revision"], bound)
        self.assertEqual(claimed["status"], "CLAIMED")

    def test_a_revoked_lease_is_refused_by_the_claim_gate(self):
        state = self.dispatch_admitted()
        claimed = self.claim_raw(dispatch_id=state["dispatch_id"])
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertEqual(claimed["owner"], OWNER)
        revoked = self.store.mutate(self.identity, lambda row: {**row, "owner_revoked": row["owner"]})
        self.assertEqual(revoked["owner_revoked"], OWNER)

        before = self.state()
        with self.assertRaisesRegex(ValueError, "ownership revoked"):
            self.claim_raw(dispatch_id=state["dispatch_id"])
        with self.assertRaisesRegex(ValueError, "ownership lost"):
            self.store.owned_update(self.identity, OWNER, status="PUBLISHING")
        with self.assertRaisesRegex(ValueError, "ownership lost"):
            self.store.assert_owner(self.identity, OWNER)
        self.assertEqual(self.state(), before, "a refused revocation check mutated the ledger")
        self.assertEqual(self.state()["attempt"], 1,
                         "a revoked owner consumed another attempt")

    def test_an_expired_lease_without_proof_of_death_is_not_taken_over(self):
        """Expiry alone is never proof the owner died: the claim gate keeps refusing."""
        state = self.dispatch_admitted()
        self.claim_raw(dispatch_id=state["dispatch_id"])
        # Objective fact first: the run named below genuinely does not exist, so the gate's
        # probe is answering 404 rather than the test pretending it did.
        with self.assertRaises(GitHubError):
            self.api.api(f"repos/{LEDGER}/actions/runs/{UNREACHABLE_RUN}")
        past = self.expired()
        self.store.mutate(self.identity, lambda row: {**row, "status": "CLAIMED",
                                                      "owner": UNREACHABLE_OWNER,
                                                      "claimed_at": past,
                                                      "lease_expires_at": past,
                                                      "attempt": 1})
        before = self.state()
        with self.assertRaisesRegex(ValueError, "already owns this task"):
            self.claim_raw(owner="probe-successor:2")
        self.assertEqual(self.state(), before,
                         "an unproven dead owner was taken over anyway")
        self.assertEqual(self.state()["attempt"], 1)
        self.assertEqual(self.state()["owner"], UNREACHABLE_OWNER)

    def test_an_expired_lease_with_a_provably_dead_owner_is_taken_over(self):
        """Positive control: the same gate does release a lease whose owner provably finished.

        Without this, "expired leases are refused" would also pass if the gate refused every
        lease, which would deadlock the fleet the sweeper exists to unblock.
        """
        run = self.completed_run()
        past = self.expired()
        self.seed(status="CLAIMED", owner=f"{run}:1", attempt=1,
                  claimed_at=past, lease_expires_at=past)
        taken = self.claim_raw(owner="probe-successor:2")
        self.assertEqual(taken["status"], "CLAIMED")
        self.assertEqual(taken["owner"], "probe-successor:2")
        self.assertEqual(taken["attempt"], 2, "a takeover is the next bounded attempt")
        self.assertIn("lease expired", str(taken.get("takeover_reason", "")),
                      "a takeover must record why it was allowed")

    def completed_run(self):
        """A real completed run in the ledger repository, or a named skip."""
        runs = self.api.api(f"repos/{LEDGER}/actions/runs?status=completed&per_page=1")
        rows = (runs or {}).get("workflow_runs") or []
        if not rows or rows[0].get("status") != "completed":
            self.skipTest(f"{LEDGER} has no completed Actions run; a provably dead owner "
                          "cannot be established against this repository")
        return rows[0]["id"]


RUN_URL = "https://example.invalid/live-seam-probe/run"
# An owner run id that the ledger repository does not have: the gate's liveness probe answers
# 404, which is "unknown", and unknown is never treated as dead.
UNREACHABLE_RUN = "999999999999999"
UNREACHABLE_OWNER = UNREACHABLE_RUN + ":1"


if __name__ == "__main__":
    unittest.main(verbosity=2)
