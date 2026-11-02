#!/usr/bin/env python3
"""F8 contract: the discovery heartbeat measures, it never assumes.

Every hold and every fire has one reason, and a malformed timestamp is never treated as
freshness. The installed cron is asserted from the workflow itself, because the recorded
defect was that 15 of 16 discovery runs were manual.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_heartbeat import heartbeat_decision, parse_stamp  # noqa: E402

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)


def run(minutes_ago, status="completed"):
    return {"status": status, "conclusion": "success",
            "createdAt": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


class DecisionTests(unittest.TestCase):
    def test_a_queued_or_running_run_holds(self):
        for status in ("queued", "in_progress", "requested", "waiting", "pending"):
            fire, reason = heartbeat_decision([run(120, status)], NOW)
            self.assertFalse(fire)
            self.assertEqual(reason, "already_running")

    def test_a_recent_fire_is_cooled_down(self):
        fire, reason = heartbeat_decision([run(120)], NOW,
                                          last_fire=(NOW - timedelta(minutes=5)).isoformat())
        self.assertFalse(fire)
        self.assertEqual(reason, "cooldown")

    def test_no_history_fires_because_nothing_else_will_start_it(self):
        self.assertEqual(heartbeat_decision([], NOW), (True, "no_history"))
        self.assertEqual(heartbeat_decision(None, NOW), (True, "no_history"))

    def test_a_fresh_run_holds(self):
        fire, reason = heartbeat_decision([run(3)], NOW, max_age_minutes=20)
        self.assertFalse(fire)
        self.assertEqual(reason, "fresh")

    def test_a_stale_run_fires(self):
        fire, reason = heartbeat_decision([run(45)], NOW, max_age_minutes=20)
        self.assertTrue(fire)
        self.assertEqual(reason, "stale")

    def test_the_newest_run_decides_not_the_first(self):
        runs = [run(120), run(2)]
        self.assertFalse(heartbeat_decision(runs, NOW, max_age_minutes=20)[0])

    def test_a_malformed_timestamp_is_not_freshness(self):
        # Dropped, not trusted: with no usable stamp the answer is no_history (fire).
        runs = [{"status": "completed", "createdAt": "not-a-date"}]
        self.assertEqual(heartbeat_decision(runs, NOW), (True, "no_history"))

    def test_non_dict_rows_are_ignored(self):
        self.assertEqual(heartbeat_decision(["junk", None, run(45)], NOW, max_age_minutes=20),
                         (True, "stale"))

    def test_parse_stamp_normalises_and_refuses(self):
        self.assertIsNone(parse_stamp(""))
        self.assertIsNone(parse_stamp("yesterday"))
        self.assertIsNotNone(parse_stamp("2026-10-29T12:00:00Z"))
        naive = datetime(2026, 10, 29, 12, 0, 0)
        self.assertIsNotNone(parse_stamp(naive).tzinfo)


class InstalledScheduleTests(unittest.TestCase):
    def test_discovery_is_actually_scheduled(self):
        text = (WORKFLOWS / "bounty-discovery.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", text)
        self.assertIn("cron:", text)

    def test_the_hydration_drain_is_actually_scheduled(self):
        # Recorded defect 2026-11-02: the drain's schedule was retired on 2026-10-31 while
        # discovery kept filling the durable queue. 41 tasks sat pending with no automated
        # path to dispatch and nothing failed, because only discovery's schedule was asserted.
        text = (WORKFLOWS / "bounty-hydration.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", text, "The durable backlog has no automated drain")
        self.assertIn("cron:", text, "The drain schedule carries no cron expression")

    def test_the_drain_does_not_share_the_discovery_concurrency_group(self):
        # A shared group makes the schedule decorative: the drain queues behind a ~25-minute
        # discovery run and is bumped by the next. Safety is the ledger CAS, not serialisation.
        def group(name):
            for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("group:"):
                    return line.split(":", 1)[1].strip()
            return None

        self.assertIsNotNone(group("bounty-discovery.yml"))
        self.assertNotEqual(group("bounty-hydration.yml"), group("bounty-discovery.yml"),
                            "A scheduled drain in discovery's group never gets a slot")

    def test_the_heartbeat_daemon_is_present(self):
        self.assertTrue((Path(__file__).resolve().parent / "discovery_heartbeat.py").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
