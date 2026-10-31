"""Pins the three defects found in the 2026-10-31 sovereign stamp audit.

A. The door's verdicts must travel. `dispatch()` used to build its client_payload with
   none of the three sovereign stamps, so `sovereign_competition()` on the delivery side
   always fell through to its hardcoded default and reported a door ruling that had been
   thrown away. Measured before the fix:

       client_payload stamps:  sovereign_admission MISSING, admission MISSING, competition MISSING
       durable state stamps:   sovereign_admission MISSING, admission PRESENT, competition MISSING
       door verdict preserved: False

B. The door's script entry point must not silently skip its own gates. `main()` called
   `iterate(workdir)` with no admission client, and `verify_rows` only runs the sovereign
   block when a client is present, so rows were admitted with no funding or competition
   check and nothing said so.

C. `admission_refusal()` carried a `client` parameter that was never read.

These are runtime tests: they drive the real functions with mocked transports, so the
assertions are receipts rather than readings of the source.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import actions_dispatch
import actions_delivery
import cline_entry_door as door


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.repo = "isearchxsolve/bounty-control"

    def mutate(self, identity, change):
        self.rows[identity] = change(self.rows.get(identity))

    def read(self, identity):
        return self.rows.get(identity), None


class FakeAPI:
    def __init__(self):
        self.posted = None

    def api(self, endpoint, method="GET", data=None, paginate=False):
        if endpoint.endswith("/dispatches"):
            self.posted = data
            return {}
        return {}


PROOF = {"funding": {"amount": "250", "usd_value": "250"}, "lane": "bounty"}
DOOR_VERDICT = {"blocking": False,
                "verdict": "clear: no competing claimant at the entry door; nominal open "
                           "pull requests are not competition"}


def dispatch_once(competition=None, sovereign_admission=None, proof=PROOF):
    store, api = FakeStore(), FakeAPI()
    context = {"repo": "acme/http", "issue_number": 7}
    actions_dispatch.dispatch(api, store, context, proof, ["founder"],
                              competition=competition,
                              sovereign_admission=sovereign_admission)
    payload = api.posted["client_payload"]
    return payload, store.rows[payload["task_id"]]


class StampsTravelToTheDeliverySide(unittest.TestCase):
    """A: the three fields must be present in both the payload and the durable row."""

    def test_every_stamp_is_in_the_client_payload(self):
        payload, _state = dispatch_once(competition=DOOR_VERDICT)
        for stamp in actions_dispatch.SOVEREIGN_STAMPS:
            with self.subTest(stamp=stamp):
                self.assertIn(stamp, payload)

    def test_every_stamp_is_in_the_durable_dispatch_state(self):
        _payload, state = dispatch_once(competition=DOOR_VERDICT)
        for stamp in actions_dispatch.SOVEREIGN_STAMPS:
            with self.subTest(stamp=stamp):
                self.assertIn(stamp, state)

    def test_the_payload_and_the_durable_row_agree(self):
        payload, state = dispatch_once(competition=DOOR_VERDICT)
        for stamp in actions_dispatch.SOVEREIGN_STAMPS:
            with self.subTest(stamp=stamp):
                self.assertEqual(payload[stamp], state[stamp])

    def test_the_doors_competition_verdict_is_preserved_verbatim(self):
        """The defect: delivery substituted its own default for the door's ruling."""
        payload, state = dispatch_once(competition=DOOR_VERDICT)
        self.assertEqual(payload["competition"], DOOR_VERDICT)
        got = actions_delivery.sovereign_competition(payload, state)
        self.assertEqual(got, DOOR_VERDICT["verdict"])
        self.assertNotEqual(got, "clear: the entry door found no competing claimant",
                            "delivery must not fall back to its own wording")

    def test_the_doors_admission_proof_arrives_intact(self):
        payload, state = dispatch_once(competition=DOOR_VERDICT)
        self.assertEqual(payload["admission"], PROOF)
        self.assertEqual(actions_delivery.sovereign_admission(payload, state, "bounty"), PROOF)

    def test_sovereign_admission_is_true_when_a_proof_exists(self):
        payload, _state = dispatch_once(competition=DOOR_VERDICT)
        self.assertIs(payload["sovereign_admission"], True)

    def test_no_proof_never_manufactures_sovereignty(self):
        """Deriving a stamp must not invent provenance that the door never gave."""
        with self.assertRaisesRegex(ValueError, "evidence missing"):
            dispatch_once(competition=DOOR_VERDICT, proof=None)

    def test_a_caller_that_supplies_no_competition_still_sends_one(self):
        """Absent is not the same as omitted: the field must exist either way."""
        with self.assertRaisesRegex(ValueError, "Competition evidence missing"):
            dispatch_once()


class QueueRejectsARowWithoutProvenance(unittest.TestCase):
    """A, queue side: a row missing a stamp is skipped loudly, never queued silently."""

    def _queue(self, rows):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
                    "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending', "
                    "seen_at REAL)")
        con.execute("CREATE TABLE task_expression(task_id TEXT, lane TEXT, expression TEXT, "
                    "PRIMARY KEY(task_id, lane, expression))")

        class Api:
            def api(self, endpoint, method="GET", data=None, paginate=False):
                return {"number": 7, "state": "open", "title": "t", "body": "b",
                        "updated_at": "2026-10-31T00:00:00Z", "labels": []}

        return actions_dispatch.queue_agent_rows(con, Api(), rows)

    def _row(self, **overrides):
        base = {"repo": "acme/http", "issue": 7, "sovereign_admission": True,
                "admission": PROOF, "competition": DOOR_VERDICT}
        base.update(overrides)
        return base

    def test_a_fully_stamped_row_is_queued(self):
        result = self._queue([self._row()])
        self.assertEqual(len(result["queued"]), 1)
        self.assertEqual(result["skipped"], [])

    def test_a_row_missing_a_stamp_is_skipped_not_queued(self):
        result = self._queue([self._row(competition=None)])
        self.assertEqual(result["queued"], [])
        self.assertEqual(result["skipped"][0]["reason"], "SOVEREIGN_STAMP_MISSING")
        self.assertIn("competition", result["skipped"][0]["detail"])

    def test_every_missing_stamp_is_named(self):
        result = self._queue([{"repo": "acme/http", "issue": 7}])
        detail = result["skipped"][0]["detail"]
        for stamp in actions_dispatch.SOVEREIGN_STAMPS:
            with self.subTest(stamp=stamp):
                self.assertIn(stamp, detail)

    def test_the_stamps_reach_the_pending_payload(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
                    "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending', "
                    "seen_at REAL)")
        con.execute("CREATE TABLE task_expression(task_id TEXT, lane TEXT, expression TEXT, "
                    "PRIMARY KEY(task_id, lane, expression))")

        class Api:
            def api(self, endpoint, method="GET", data=None, paginate=False):
                return {"number": 7, "state": "open", "title": "t", "body": "b",
                        "updated_at": "2026-10-31T00:00:00Z", "labels": []}

        actions_dispatch.queue_agent_rows(con, Api(), [self._row()])
        payload = json.loads(con.execute("SELECT payload FROM pending").fetchone()[0])
        for stamp in actions_dispatch.SOVEREIGN_STAMPS:
            with self.subTest(stamp=stamp):
                self.assertIn(stamp, payload)


class DoorRefusesToRunWithoutItsGates(unittest.TestCase):
    """B: the script entry point must not silently admit unchecked rows."""

    def test_main_returns_a_loud_verdict_when_no_client_can_be_built(self):
        import unittest.mock as mock
        with mock.patch.object(door, "sovereign_client", lambda: None), \
             mock.patch.object(door, "iterate") as iterate:
            self.assertEqual(door.main(), 2)
            iterate.assert_not_called()

    def test_main_passes_the_client_into_the_loop(self):
        import unittest.mock as mock
        sentinel = object()
        captured = {}

        def fake_iterate(workdir, **kwargs):
            captured.update(kwargs)
            return {"admitted": [], "refused": [], "unpriced": [], "history": []}

        with mock.patch.object(door, "sovereign_client", lambda: sentinel), \
             mock.patch.object(door, "iterate", fake_iterate):
            door.main()
        self.assertIs(captured.get("admission_client"), sentinel)

    def test_the_loop_forwards_the_client_to_verify(self):
        """iterate() must not drop the client on its way to verify_rows."""
        seen = {}

        def verify(rows, limit=12, admission_client=None):
            seen["client"] = admission_client
            return {"admitted": [], "refused": [], "unpriced": []}

        sentinel = object()
        door.iterate("W", rounds=1, run=lambda *a, **k: {"exit_code": 0, "rows": [],
                                                         "tail": "", "wrote_file": True},
                     verify=verify, admission_client=sentinel)
        self.assertIs(seen["client"], sentinel)

    def test_without_a_client_the_sovereign_block_does_not_run(self):
        """Documents the reason B mattered: no client means no gate, silently."""
        import unittest.mock as mock
        called = []
        with mock.patch.object(door, "admission_refusal",
                               lambda *a, **k: called.append(1) or (None, None, PROOF)):
            door.verify_rows([{"repo": "acme/http", "issue": 7, "is_code_task": True,
                               "reward_quote": "We pay a $250 bounty for a fix."}],
                             fetch=lambda r, n: {"state": "open", "title": "t",
                                                 "body": "We pay a $250 bounty for a fix.",
                                                 "updated_at": "2026-10-31T00:00:00Z"},
                             admission_client=None)
        self.assertEqual(called, [], "no client must mean no admission call")


class DeadParameterIsGone(unittest.TestCase):
    """C: a parameter that looks like it controls the gate but does not."""

    def test_admission_refusal_takes_no_client(self):
        import inspect
        params = inspect.signature(door.admission_refusal).parameters
        self.assertNotIn("client", params)
        self.assertIn("context_builder", params)

    def test_calling_it_with_a_client_is_a_type_error_not_a_silent_ignore(self):
        with self.assertRaises(TypeError):
            door.admission_refusal("acme/http", 7, client=object())


if __name__ == "__main__":
    unittest.main(verbosity=2)
