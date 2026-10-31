"""Tests for the agent door: it must never be able to take discovery down or invent a row."""

import os
import unittest
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
        source = open(agent_door.__file__, encoding="utf-8").read()
        self.assertIn("127.0.0.1", source)
        self.assertNotIn("integrate.api.nvidia.com", source)


if __name__ == "__main__":
    unittest.main()
