"""Tests for the agent door: it must never be able to take discovery down or invent a row."""

import contextlib
import io
import json
import os
import unittest
import tempfile
from pathlib import Path
from unittest import mock

import agent_door


class DoorIsOffByDefault(unittest.TestCase):
    def test_no_flag_means_no_agent_is_started(self):
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": ""}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline") as cline:
                result = agent_door.find_issues()
        cline.assert_not_called()
        self.assertEqual(result["reason"], "DOOR_DISABLED")
        self.assertEqual(result["rows"], [])


class DoorFailsClosed(unittest.TestCase):
    def test_missing_cline_is_a_named_reason(self):
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline"}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline", return_value=None):
                result = agent_door.find_issues()
        self.assertEqual(result["reason"], "CLINE_UNAVAILABLE")

    def test_missing_gateway_is_a_named_reason(self):
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline"}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline", return_value="/usr/bin/cline"):
                with mock.patch.object(agent_door, "start_gateway", return_value=False):
                    result = agent_door.find_issues()
        self.assertEqual(result["reason"], "GATEWAY_UNAVAILABLE")

    def test_an_exception_in_the_agent_is_contained(self):
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline"}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline", return_value="/usr/bin/cline"):
                with mock.patch.object(agent_door, "start_gateway", return_value=True):
                    with mock.patch.object(agent_door.cline_entry_door, "scaffold_workspace",
                                           return_value="/tmp/w"):
                        with mock.patch.object(agent_door.cline_entry_door, "iterate",
                                               side_effect=RuntimeError("agent died")):
                            result = agent_door.find_issues()
        self.assertEqual(result["reason"], "DOOR_FAILED")
        self.assertEqual(result["rows"], [])

    def test_gateway_with_no_keys_does_not_start_a_server(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(agent_door, "PROXY_PORT", 65533):
                self.assertFalse(agent_door.start_gateway(timeout=1))


class DoorReturnsWhatTheGateAdmitted(unittest.TestCase):
    @mock.patch.object(agent_door.cline_entry_door, "ingest_founder_watch_leads", return_value=[])
    def test_rows_come_from_admitted_only(self, _leads):
        admitted = [{"repo": "a/b", "issue": 1}]
        outcome = {"admitted": admitted, "refused": [{"reason": "X"}], "history": [{"round": 1}]}
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline"}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline", return_value="/usr/bin/cline"):
                with mock.patch.object(agent_door, "start_gateway", return_value=True):
                    with mock.patch.object(agent_door.cline_entry_door, "scaffold_workspace",
                                           return_value="/tmp/w"):
                        with mock.patch.object(agent_door.cline_entry_door, "iterate",
                                               return_value=outcome):
                            result = agent_door.find_issues()
        self.assertEqual(result["reason"], "OK")
        self.assertEqual(result["rows"], admitted)


class TheAgentIsNeverPointedStraightAtTheProvider(unittest.TestCase):
    def test_the_door_uses_the_local_gateway(self):
        source = Path(agent_door.__file__).read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", source)
        self.assertNotIn("integrate.api.nvidia.com", source)


class ResearchContinuity(unittest.TestCase):
    def test_existing_research_survives_workspace_recreation_without_becoming_a_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = agent_door.research_memory_path(directory)
            self.assertIn('Unverified', path.read_text(encoding='utf-8'))
            path.write_text('Unverified lead: revisit its live source before citing.\n', encoding='utf-8')
            self.assertEqual(agent_door.research_memory_path(directory).read_text(encoding='utf-8'),
                             'Unverified lead: revisit its live source before citing.\n')
            self.assertEqual([file.name for file in Path(directory).iterdir()], ['RESEARCH.md'])


class TheSummaryNamesTheBrain(unittest.TestCase):
    """The run's own receipt cannot answer "why zero rows" without naming the model.

    Measured 2026-11-06 on the production path (BOUNTY_ENTRY_DOOR=cline): the static
    summary already carried a brain receipt, but the door returns early into the agent
    path, so the only receipt that ever printed stopped at workspace/admitted/refused.
    A zero-admission run was therefore indistinguishable from a broken one.
    """

    @mock.patch.object(agent_door.cline_entry_door, "ingest_founder_watch_leads", return_value=[])
    def test_the_entry_door_summary_carries_the_brain(self, _leads):
        outcome = {"admitted": [], "refused": [{"reason": "NO_ESCROW"}], "history": []}
        delivered = io.StringIO()
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline",
                                          "BOUNTY_ENTRY_MODEL": "measured-brain"}, clear=False):
            with mock.patch.object(agent_door, "ensure_cline", return_value="/usr/bin/cline"):
                with mock.patch.object(agent_door, "start_gateway", return_value=True):
                    with mock.patch.object(agent_door.cline_entry_door, "scaffold_workspace",
                                           return_value="/tmp/w"):
                        with mock.patch.object(agent_door.cline_entry_door, "iterate",
                                               return_value=outcome):
                            with contextlib.redirect_stdout(delivered):
                                result = agent_door.find_issues()
        summary = None
        for line in delivered.getvalue().splitlines():
            if '"ENTRY_DOOR"' not in line:
                continue
            summary = json.loads(line)
        self.assertIsNotNone(summary, "the door printed no ENTRY_DOOR summary")
        self.assertEqual(result["reason"], "NO_ROWS")
        self.assertIn("brain", summary)
        self.assertEqual(summary["brain"]["entry_model"], "measured-brain")
        self.assertEqual(summary["brain"]["roster"]["verdict"], "CLEAN")

    def test_the_receipt_never_breaks_the_door_when_the_roster_cannot_be_read(self):
        # A receipt is evidence, not a dependency: if the audit or the roster file blows
        # up, the door must still run and the summary must say UNAUDITED. The guard is
        # inside brain_receipt(), so the fault is injected at the audit seam, not at
        # builtins.open - pathlib reads through io.open, so patching builtins.open
        # silently does nothing and the test would pass a working receipt as broken.
        import query_quality_audit
        with mock.patch.dict(os.environ, {"BOUNTY_ENTRY_DOOR": "cline"}, clear=False):
            with mock.patch.object(query_quality_audit, "audit", side_effect=OSError("roster missing")):
                receipt = agent_door.cline_entry_door.brain_receipt()
        self.assertEqual(receipt["roster"]["verdict"], "UNAUDITED")
        self.assertIn("entry_model", receipt)


if __name__ == "__main__":
    unittest.main()
