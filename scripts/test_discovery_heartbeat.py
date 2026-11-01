"""The discovery heartbeat must never duplicate a run and never spin.

Why this exists: on 2026-10-27 the discovery workflow declared ``*/15 * * * *``, was active,
and had been on the default branch for hours -- and every one of its nine runs that day was a
manual ``workflow_dispatch``. GitHub's scheduler never fired. The remedy is a heartbeat, and a
heartbeat is dangerous in exactly two ways, so both are pinned here:

* it dispatches on top of a live run (duplicate pass, concurrency conflict), or
* it dispatches in a tight loop because it cannot tell that it already fired.

Every other test exists to keep those two honest without over-holding: a heartbeat that
refuses forever is the stall it was built to cure.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import discovery_heartbeat as heartbeat  # noqa: E402

NOW = datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)


def run(minutes_ago, status="completed", conclusion="success", number=1):
    return {"databaseId": number, "status": status, "conclusion": conclusion,
            "createdAt": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
            "url": f"https://example.invalid/run/{number}"}


class DecisionTests(unittest.TestCase):
    def decide(self, runs, **kwargs):
        return heartbeat.heartbeat_decision(runs, NOW, **kwargs)

    def test_a_queued_run_holds_of_even_when_the_list_is_ancient(self):
        self.assertEqual(self.decide([run(0, status="queued"), run(600)]),
                         (False, "already_running"))

    def test_an_in_flight_run_holds(self):
        self.assertEqual(self.decide([run(3, status="in_progress", conclusion=None)]),
                         (False, "already_running"))

    def test_a_recent_run_holds(self):
        self.assertEqual(self.decide([run(5)]), (False, "fresh"))

    def test_default_stale_threshold_matches_one_discovery_interval_plus_delay(self):
        self.assertEqual(self.decide([run(19)]), (False, "fresh"))
        self.assertEqual(self.decide([run(20)]), (True, "stale"))

    def test_the_newest_run_decides_not_the_oldest(self):
        self.assertEqual(self.decide([run(10, number=2), run(400, number=1)]), (False, "fresh"))

    def test_an_old_run_fires(self):
        self.assertEqual(self.decide([run(60)]), (True, "stale"))

    def test_the_age_boundary_is_inclusive(self):
        self.assertEqual(self.decide([run(19)], max_age_minutes=20), (False, "fresh"))
        self.assertEqual(self.decide([run(20)], max_age_minutes=20), (True, "stale"))

    def test_no_history_fires_because_nothing_else_will_start_it(self):
        self.assertEqual(self.decide([]), (True, "no_history"))

    def test_unusable_timestamps_fall_back_to_no_history(self):
        self.assertEqual(self.decide([{"status": "completed", "createdAt": "not-a-time"}]),
                         (True, "no_history"))

    def test_a_recent_fire_holds_inside_the_cooldown(self):
        self.assertEqual(self.decide([run(120)], cooldown_minutes=20,
                                     last_fire=(NOW - timedelta(minutes=5)).isoformat()),
                         (False, "cooldown"))

    def test_an_expired_cooldown_fires_again(self):
        self.assertEqual(self.decide([run(120)], cooldown_minutes=20,
                                     last_fire=(NOW - timedelta(minutes=25)).isoformat()),
                         (True, "stale"))

    def test_the_cooldown_does_not_override_a_live_run(self):
        self.assertEqual(self.decide([run(1, status="queued")], last_fire=None),
                         (False, "already_running"))


class RefResolutionTests(unittest.TestCase):
    """The ref must be read, not guessed.

    Measured 2026-11-01 (run 41256276495): a compiled-in ref of ``master`` was dispatched
    against a repository whose default branch is ``main``, so every dispatch was answered
    "HTTP 422: No ref found for: master" and the heartbeat -- the fallback for a discovery
    cron that does not fire -- was itself dark. An unreadable answer must hold, because a
    guessed ref is a refusal that looks like a healthy beat.
    """

    def resolve(self, returncode=0, stdout="main\n", stderr=""):
        with mock.patch.object(heartbeat.subprocess, "run",
                               return_value=SimpleNamespace(returncode=returncode,
                                                            stdout=stdout, stderr=stderr)):
            return heartbeat.resolve_ref("isearchxsolve/bounty-control")

    def test_the_default_branch_is_read_from_the_repository(self):
        self.assertEqual(self.resolve(), "main")

    def test_an_unreadable_repository_returns_none_rather_than_a_guess(self):
        self.assertIsNone(self.resolve(returncode=1, stdout="", stderr="gh: not found"))

    def test_an_empty_answer_is_not_a_ref(self):
        self.assertIsNone(self.resolve(returncode=0, stdout="  \n"))


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.state = self.root / "heartbeat.jsonl"
        self.args = argparse.Namespace(
            repo="isearchxsolve/anonym-family-archive", workflow="bounty-discovery.yml",
            ref="master", max_age_minutes=20, cooldown_minutes=20, state=str(self.state))

    def evaluate(self, runs, dry_run=False, ok=True):
        buffer = io.StringIO()
        with mock.patch.object(heartbeat, "probe", return_value=runs), \
                mock.patch.object(heartbeat, "dispatch", return_value=(ok, "dispatched")) as fired, \
                redirect_stdout(buffer):
            status = heartbeat.evaluate(self.args, dry_run)
        return status, fired, buffer.getvalue()

    def test_stale_fires_once_and_writes_a_receipt(self):
        status, fired, out = self.evaluate([run(90)])
        self.assertEqual(status, 0)
        fired.assert_called_once_with(self.args.repo, self.args.workflow, self.args.ref)
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertTrue(receipt["fired"])
        self.assertEqual(receipt["decision"], "stale")
        self.assertIn("VERDICT: FIRED", out)

    def test_the_fire_immediately_arms_the_cooldown_so_the_loop_cannot_spin(self):
        self.evaluate([run(90)])
        status, fired, out = self.evaluate([run(90)])
        self.assertEqual(status, 0)
        fired.assert_not_called()
        self.assertIn("VERDICT: HOLD cooldown", out)

    def test_a_dry_run_reports_intent_and_touches_nothing(self):
        status, fired, out = self.evaluate([run(90)], dry_run=True)
        self.assertEqual(status, 0)
        fired.assert_not_called()
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertFalse(receipt["fired"])
        self.assertTrue(receipt["would_fire"])
        self.assertIn("(dry run)", out)

    def test_a_live_run_is_never_duplicated(self):
        status, fired, out = self.evaluate([run(2, status="queued")])
        self.assertEqual(status, 0)
        fired.assert_not_called()
        self.assertIn("already_running", out)

    def test_a_probe_error_is_fail_closed(self):
        buffer = io.StringIO()
        with mock.patch.object(heartbeat, "probe",
                               side_effect=heartbeat.ProbeError("gh: not authenticated")), \
                mock.patch.object(heartbeat, "dispatch") as fired, \
                redirect_stdout(buffer):
            status = heartbeat.evaluate(self.args, False)
        self.assertEqual(status, 0)
        fired.assert_not_called()
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertEqual(receipt["decision"], "probe_error")
        self.assertIn("not authenticated", receipt["probe_error"])

    def test_a_failed_dispatch_is_reported_not_swallowed(self):
        status, fired, out = self.evaluate([run(90)], ok=False)
        self.assertEqual(status, 2)
        fired.assert_called_once()
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertFalse(receipt["fired"])
        self.assertEqual(receipt["decision"], "dispatch_failed")

    def test_a_ref_from_the_repository_is_dispatched_not_the_compiled_in_guess(self):
        args = argparse.Namespace(
            repo="isearchxsolve/bounty-control", workflow="bounty-discovery.yml",
            ref=None, max_age_minutes=20, cooldown_minutes=20, state=str(self.state))
        buffer = io.StringIO()
        with mock.patch.object(heartbeat, "probe", return_value=[run(90)]), \
                mock.patch.object(heartbeat, "resolve_ref", return_value="main"), \
                mock.patch.object(heartbeat, "dispatch",
                                  return_value=(True, "dispatched")) as fired, \
                redirect_stdout(buffer):
            status = heartbeat.evaluate(args, False)
        self.assertEqual(status, 0)
        fired.assert_called_once_with(args.repo, args.workflow, "main")
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertTrue(receipt["fired"])
        self.assertEqual(receipt["ref"], "main")
        self.assertIn("VERDICT: FIRED", buffer.getvalue())

    def test_an_unresolvable_ref_holds_instead_of_dispatching_a_guess(self):
        args = argparse.Namespace(
            repo="isearchxsolve/bounty-control", workflow="bounty-discovery.yml",
            ref=None, max_age_minutes=20, cooldown_minutes=20, state=str(self.state))
        buffer = io.StringIO()
        with mock.patch.object(heartbeat, "probe", return_value=[run(90)]), \
                mock.patch.object(heartbeat, "resolve_ref", return_value=None), \
                mock.patch.object(heartbeat, "dispatch") as fired, \
                redirect_stdout(buffer):
            status = heartbeat.evaluate(args, False)
        self.assertEqual(status, 2)
        fired.assert_not_called()
        receipt = json.loads(self.state.read_text(encoding="utf-8").strip())
        self.assertFalse(receipt["fired"])
        self.assertEqual(receipt["decision"], "ref_unresolved")
        # A failed ref must never be mistaken for a healthy hold on a fresh pipeline.
        self.assertIn("ref_unresolved", buffer.getvalue())

    def test_an_explicit_ref_is_still_honored(self):
        status, fired, out = self.evaluate([run(90)])
        fired.assert_called_once_with(self.args.repo, self.args.workflow, "master")


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_only_one_evaluator_runs(self):
        path = self.root / "beat.lock"
        first = heartbeat.acquire_lock(path, stale_minutes=15)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(heartbeat.acquire_lock(path, stale_minutes=15))
        finally:
            import os
            os.close(first)

    def test_a_stale_lock_is_taken_over(self):
        import os
        import time as clock
        path = self.root / "beat.lock"
        path.write_text("999999", encoding="utf-8")
        old = clock.time() - 3600
        os.utime(path, (old, old))
        handle = heartbeat.acquire_lock(path, stale_minutes=15)
        self.assertIsNotNone(handle)
        os.close(handle)

    def test_a_held_lock_renews_its_lease(self):
        import os
        import time as clock
        path = self.root / "beat.lock"
        handle = heartbeat.acquire_lock(path, stale_minutes=15)
        self.assertIsNotNone(handle)
        try:
            old = clock.time() - 3600
            os.utime(path, (old, old))
            heartbeat.refresh_lock(handle)
            self.assertGreater(path.stat().st_mtime, old + 1800)
            self.assertEqual(path.read_text(encoding="ascii").split()[0], str(os.getpid()))
        finally:
            os.close(handle)

    def test_stale_lock_that_cannot_be_unlinked_holds_without_crashing(self):
        import os
        import time as clock
        path = self.root / "beat.lock"
        path.write_text("999999", encoding="ascii")
        old = clock.time() - 3600
        os.utime(path, (old, old))
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("lock is open")):
            self.assertIsNone(heartbeat.acquire_lock(path, stale_minutes=15))


if __name__ == "__main__":
    unittest.main(verbosity=2)
