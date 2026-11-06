"""The brief must forbid background work, because a killed turn looks like an empty market.

Measured 2026-11-06 on run 42248630305: the door's receipt read
``{"round": 1, "agent_exit": -1, "rows": 0, "refused": 0}`` and the run reported
``door_reason: NO_ROWS`` with an empty ``counts``. The agent had not concluded anything - its
turn was killed. The log shows why: "Let me run with nohup background and then read the
file", "Run 3 scanners sequentially in background", "Command completed with background
processes still running", and finally "Let me run these in background" at minute 11 of a
15-minute round.

Background processes do not survive the round, so the work inside them did not exist, and the
failure was indistinguishable from "the market had nothing in it" - which is how a $0
admission got read as a market condition for a whole evening.

These tests pin the two rules that follow: never launch background work, and write each row
the moment it is verified rather than batching verification behind investigation.
"""
import os
import unittest
from unittest import mock

import cline_entry_door as door


class TheBriefForbidsBackgroundWork(unittest.TestCase):

    def setUp(self):
        self.text = door.render_task_file()

    def test_the_brief_names_background_work_as_forbidden(self):
        self.assertIn("Do not launch background work", self.text)
        self.assertIn("foreground", self.text)

    def test_the_brief_explains_why_with_the_measured_failure(self):
        # A rule without its measurement is a preference; a rule with one is a law.
        self.assertIn("nohup", self.text)
        self.assertIn("rows=0", self.text)

    def test_write_early_is_stated_not_implied(self):
        self.assertIn("shortlist.jsonl", self.text)
        self.assertIn("immediately", self.text)

    def test_the_budget_is_stated_and_not_silently_enlarged(self):
        with mock.patch.dict(os.environ, {"BOUNTY_AGENT_TIMEOUT": "900"}, clear=False):
            text = door.render_task_file()
        self.assertIn("900 seconds", text)
        self.assertIn("not extended", text)


if __name__ == "__main__":
    unittest.main()
