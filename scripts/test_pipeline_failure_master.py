"""Deterministic fault injection at production boundaries; no external services."""
import copy
import contextlib
from functools import lru_cache
import json
import os
import subprocess
import unittest
from unittest.mock import Mock, patch

import actions_dispatch as dispatch
from actions_github import GitHub, GitHubError, StateStore, task_id
from pipeline_evidence import bind_proof, require_evidence, source_revision


def transport_client(**kwargs):
    if os.environ.get('PIPELINE_TRANSPORT_LIVE') == '1':
        from live_transport_bindings import client
        return client(**kwargs)
    return GitHub(**kwargs)


@contextlib.contextmanager
def transport_boundary(kind, value=None):
    if os.environ.get('PIPELINE_TRANSPORT_LIVE') == '1':
        from live_transport_bindings import fault
        actual = ('missing' if isinstance(value, FileNotFoundError) else 'timeout') if kind == 'launch' else kind
        with fault(actual, value if kind == 'status' else 500) as wire:
            yield (wire.run, wire.sleep) if kind == 'throttle' else wire.run
        return
    with contextlib.ExitStack() as stack:
        if kind == 'launch':
            run = stack.enter_context(patch('actions_github.subprocess.run', side_effect=value))
        elif kind == 'status':
            run = stack.enter_context(patch('actions_github.subprocess.run', return_value=
                subprocess.CompletedProcess([], 1, b'', f'HTTP {value}'.encode())))
        elif kind == 'json':
            run = stack.enter_context(patch('actions_github.subprocess.run', return_value=
                subprocess.CompletedProcess([], 0, b'{"partial":', b'')))
        elif kind == 'throttle':
            run = stack.enter_context(patch('actions_github.subprocess.run', return_value=
                subprocess.CompletedProcess([], 1, b'', b'rate limit exceeded')))
            stack.enter_context(patch.object(GitHub, 'rate_limit_wait', return_value=1))
            sleep = stack.enter_context(patch('actions_github.time.sleep'))
        elif kind == 'deadline':
            stack.enter_context(patch('actions_github.time.monotonic', return_value=10))
            run = stack.enter_context(patch('actions_github.subprocess.run'))
        elif kind == 'page':
            run = stack.enter_context(patch.object(GitHub, 'api', return_value=[[{'id': 1}], {'message': 'error'}]))
        yield (run, sleep) if kind == 'throttle' else run


@lru_cache(maxsize=1)
def live_context():
    return GitHub().issue_context(
        os.environ.get('LIVE_EVIDENCE_REPO', 'mgillr/acfa-rs'),
        int(os.environ.get('LIVE_EVIDENCE_ISSUE', '93')))


def context():
    if os.environ.get('PIPELINE_EVIDENCE_LIVE') == '1':
        # Same context contract; only the provider changes in explicit live mode.
        return copy.deepcopy(live_context())
    return {"repo": "acme/http", "issue_number": 7,
            "issue": {"state": "open", "body": "Bounty $250. Fix retry.", "title": "Retry"},
            "comments": [], "complete_comments": True,
            "repository": {"archived": False, "disabled": False}}


class MemoryStore(StateStore):
    def __init__(self):
        self.repo = "unit/control"
        self.rows = {}

    def read(self, identity):
        return copy.deepcopy(self.rows.get(identity)), None

    def mutate(self, identity, change):
        result = change(copy.deepcopy(self.rows.get(identity)))
        self.rows[identity] = copy.deepcopy(result)
        return result


class EvidenceFailureMatrix(unittest.TestCase):
    def test_each_source_mutation_invalidates_prior_proof(self):
        original = context()
        row = {"sovereign_admission": True, "admission": bind_proof({}, original),
               "competition": {"blocking": False}}
        mutations = {
            "body edit": lambda c: c["issue"].update(body="Offer withdrawn"),
            "title edit": lambda c: c["issue"].update(title="Different scope"),
            "new comment": lambda c: c["comments"].append({"body": "Withdrawn"}),
            "wrong issue": lambda c: c.update(issue_number=8),
            "wrong repo": lambda c: c.update(repo="other/http"),
            "incomplete pagination": lambda c: c.update(complete_comments=False),
            "archived": lambda c: c["repository"].update(archived=True),
            "disabled": lambda c: c["repository"].update(disabled=True),
            "closed": lambda c: c["issue"].update(state="closed"),
        }
        for name, mutate in mutations.items():
            with self.subTest(fault=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                with self.assertRaises(ValueError):
                    require_evidence(row, changed)
        require_evidence(row, original)

    def test_missing_or_ambiguous_stamps_never_mean_approval(self):
        original = {"sovereign_admission": True, "admission": bind_proof({}, context()),
                    "competition": {"blocking": False}}
        faults = [("sovereign_admission", v) for v in (None, False, 1, "true")]
        faults += [("admission", v) for v in (None, {}, [], "approved")]
        faults += [("competition", v) for v in
                   (None, {}, {"blocking": True}, {"blocking": 0},
                    {"blocking": False, "verified": False},
                    {"blocking": False, "verdict": "unverified_api_failure"})]
        for field, value in faults:
            with self.subTest(field=field, value=value):
                row = copy.deepcopy(original)
                row[field] = value
                with self.assertRaises(ValueError):
                    require_evidence(row, context())

    def test_observation_timestamp_is_not_a_source_edit(self):
        original = context()
        refreshed = copy.deepcopy(original)
        refreshed.update(fetched_at="2099-01-01", base_branch="release")
        self.assertEqual(source_revision(original), source_revision(refreshed))


class TransportFailureMatrix(unittest.TestCase):
    def test_cli_missing_and_timeout_are_explicit_transport_failures(self):
        for fault in (FileNotFoundError("gh"), subprocess.TimeoutExpired("gh", 90)):
            with self.subTest(fault=type(fault).__name__), transport_boundary('launch', fault) as run:
                with self.assertRaises(GitHubError):
                    transport_client(token="synthetic").api("repos/acme/http")
                self.assertEqual(run.call_count, 1)

    def test_auth_not_found_and_server_errors_do_not_return_empty_success(self):
        for status in (401, 403, 404, 422, 500, 502, 503):
            with self.subTest(status=status), transport_boundary('status', status):
                with self.assertRaises(GitHubError):
                    transport_client(token="synthetic").api("repos/acme/http")

    def test_bad_json_cannot_become_success(self):
        with transport_boundary('json'):
            with self.assertRaises(json.JSONDecodeError):
                transport_client(token="synthetic").api("repos/acme/http")

    def test_throttle_retry_is_bounded(self):
        with transport_boundary('throttle') as (run, sleep):
            with self.assertRaises(GitHubError):
                transport_client(token="synthetic").api("repos/acme/http")
            self.assertEqual(run.call_count, GitHub.THROTTLE_TRIES)
            self.assertEqual(sleep.call_count, GitHub.THROTTLE_TRIES - 1)

    def test_expired_deadline_prevents_any_transport(self):
        with transport_boundary('deadline') as run:
            with self.assertRaisesRegex(GitHubError, "deadline"):
                transport_client(token="synthetic", deadline=9).api("repos/acme/http")
            run.assert_not_called()

    def test_malformed_page_never_becomes_empty_supply(self):
        with transport_boundary('page'):
            with self.assertRaises(GitHubError):
                list(transport_client().pages("issues"))


class DurableStateFaults(unittest.TestCase):
    @staticmethod
    def live():
        return os.environ.get('PIPELINE_DURABLE_LIVE') == '1'

    def resource(self, store):
        self.branch, self.control = store.branch, store.repo

    @contextlib.contextmanager
    def retry_fixture(self, identity):
        if self.live():
            from live_durable_bindings import conflict
            with conflict(identity) as fixture:
                self.resource(fixture[0])
                yield fixture
            return
        store = StateStore(api=Mock(), repo="unit/control")
        with patch.object(store, "ensure"), patch.object(store, "read", side_effect=[
                ({"status": "CLAIMED", "count": 1}, "old"),
                ({"status": "CLAIMED", "count": 9}, "new")]), \
                patch.object(store, "write", side_effect=[GitHubError("409 conflict"), None]) as write, \
                patch("actions_github.time.sleep"):
            from types import SimpleNamespace
            yield store, write, SimpleNamespace(sha='new')

    @contextlib.contextmanager
    def exhausted_fixture(self, identity, status):
        if self.live():
            from live_durable_bindings import write_failure
            with write_failure(identity, status) as fixture:
                self.resource(fixture[0])
                yield fixture
            return
        store = StateStore(api=Mock(), repo="unit/control")
        with patch.object(store, "ensure"), patch.object(store, "read", return_value=(None, None)), \
                patch.object(store, "write", side_effect=GitHubError(str(status))) as write, \
                patch("actions_github.time.sleep"):
            yield store, write

    def dispatch_fixture(self):
        if self.live():
            from live_durable_bindings import dispatch_fixture
            store, api = dispatch_fixture()
            self.resource(store)
            return store, api, context()
        return MemoryStore(), Mock(), context()

    @contextlib.contextmanager
    def reservation_failure(self, store):
        if self.live():
            from live_durable_bindings import unavailable_reservation
            with unavailable_reservation(store):
                yield
            return
        with patch.object(store, "mutate", side_effect=GitHubError("storage unavailable")):
            yield

    def test_conflict_rereads_latest_state_before_retry(self):
        identity = task_id(context()['repo'], context()['issue_number'])
        with self.retry_fixture(identity) as (store, write, latest):
            result = store.mutate(identity, lambda old: {**old, "count": old["count"] + 1})
        self.assertEqual(result["count"], 10)
        self.assertEqual(write.call_args.args[2], latest.sha)

    def test_exhausted_conflicts_and_permission_errors_propagate(self):
        for status, attempts in ((409, 5), (422, 5), (403, 1), (500, 1)):
            with self.subTest(status=status):
                identity = task_id(context()['repo'], context()['issue_number'])
                with self.exhausted_fixture(identity, status) as (store, write):
                    with self.assertRaises(GitHubError):
                        store.mutate(identity, lambda old: {"status": "DISPATCHING"})
                    self.assertEqual(write.call_count, attempts)

    def test_ambiguous_dispatch_failure_keeps_reservation_and_blocks_duplicate(self):
        store, api, ctx = self.dispatch_fixture()
        api.api.side_effect = GitHubError("response lost after POST")
        proof = bind_proof({}, ctx)
        with self.assertRaises(GitHubError):
            dispatch.dispatch(api, store, ctx, proof, ["normal"],
                              sovereign_admission=True, competition={"blocking": False})
        record = store.read(task_id(ctx['repo'], ctx['issue_number']))[0]
        self.assertEqual(record["status"], "DISPATCHING")
        self.assertTrue(record["dispatch_id"])
        with self.assertRaises(ValueError):
            dispatch.dispatch(api, store, ctx, proof, ["normal"],
                              sovereign_admission=True, competition={"blocking": False})
        self.assertEqual(api.api.call_count, 1)

    def test_bounded_dispatch_attempts_refuse_beyond_the_bound(self):
        """The reservation counts attempts per task, and refusing at the bound is what stops a
        task that can never reserve from being retried into an infinite dispatch loop.

        Measured by mutation 2026-11-02: with the bound's guard removed this suite still ran
        green, which is how a missing coverage is found. Every other guard this matrix pins was
        caught the same way.
        """
        store, api, ctx = self.dispatch_fixture()
        # The first attempt succeeds, so a successful dispatch still works.
        dispatch.dispatch(api, store, ctx, bind_proof({}, ctx), ["normal"],
                          sovereign_admission=True, competition={"blocking": False})
        identity = task_id(ctx['repo'], ctx['issue_number'])
        self.assertEqual(api.api.call_count, 1)
        # A task left in a non-retryable state is refused with the durable state named, which
        # is the guard a duplicate dispatch actually meets.
        with self.assertRaisesRegex(ValueError, "Existing durable task state"):
            dispatch.dispatch(api, store, ctx, bind_proof({}, ctx), ["normal"],
                             sovereign_admission=True, competition={"blocking": False})
        self.assertEqual(api.api.call_count, 1, "the refusal happened before any POST")
        # And the bound itself: a request whose attempt counter is already at the ceiling is
        # refused by the bound rather than by the state.
        store.rows[identity]["dispatch_attempt"] = 3
        store.rows[identity]["status"] = "REJECTED_PREPARATION"
        with self.assertRaisesRegex(ValueError, "Bounded dispatch attempts exhausted"):
            dispatch.dispatch(api, store, ctx, bind_proof({}, ctx), ["normal"],
                             sovereign_admission=True, competition={"blocking": False})
        self.assertEqual(api.api.call_count, 1)

    def test_fast_runner_claim_survives_late_dispatch_ack(self):
        store, api, ctx = self.dispatch_fixture()
        identity = task_id(ctx['repo'], ctx['issue_number'])
        def accepted(*args):
            store.claim(ctx['repo'], ctx['issue_number'], "123:1", "https://example.invalid/run", "a" * 40,
                        dispatch_id=store.rows[identity]["dispatch_id"])
        api.api.side_effect = accepted
        dispatch.dispatch(api, store, ctx, bind_proof({}, ctx), ["normal"],
                          sovereign_admission=True, competition={"blocking": False})
        self.assertEqual(store.rows[identity]["status"], "CLAIMED")
        self.assertEqual(store.rows[identity]["owner"], "123:1")

    def test_failed_reservation_prevents_dispatch_post(self):
        store, api, ctx = self.dispatch_fixture()
        with self.reservation_failure(store):
            with self.assertRaises(GitHubError):
                dispatch.dispatch(api, store, ctx, bind_proof({}, ctx), ["normal"],
                                  sovereign_admission=True, competition={"blocking": False})
        api.api.assert_not_called()




class ReleaseFailureMatrix(unittest.TestCase):
    def test_independent_release_bundle_and_fault_mutations(self):
        from live_release_bindings import run_release_probes
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            results = run_release_probes(Path(tmp))
            for row in results:
                with self.subTest(case=row['case']):
                    self.assertEqual(row.get('status'), 'PASS', row.get('diagnostic') or row.get('refusal'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
