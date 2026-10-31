"""The agent's shortlist is a claim; only GitHub can make it a queue row."""

import json
import sqlite3
import unittest

import actions_dispatch


class FakeApi:
    def __init__(self, issues=None, fail=()):
        self.issues = issues or {}
        self.fail = set(fail)
        self.calls = []

    def api(self, endpoint, method="GET", data=None, paginate=False):
        self.calls.append(endpoint)
        key = endpoint.replace("repos/", "").replace("/issues/", "#")
        if key in self.fail:
            raise RuntimeError("404 Not Found")
        return self.issues[key]


def database():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
                "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending', "
                "seen_at REAL DEFAULT 0)")
    con.execute("CREATE TABLE task_expression(task_id TEXT, lane TEXT, expression TEXT, "
                "PRIMARY KEY(task_id, lane, expression))")
    return con


def issue(number, updated="2026-10-30T00:00:00Z"):
    return {"number": number, "title": "Fix the thing", "state": "open",
            "updated_at": updated, "labels": [{"name": "bounty"}],
            "body": "## Budget: $900"}


def stamped(**overrides):
    """A row as the entry door emits it: carrying its own provenance.

    queue_agent_rows() refuses a row that cannot say where it came from (2026-10-31), so
    these fixtures carry the three stamps the door writes. The refusal itself is pinned in
    test_sovereign_stamps.
    """
    row = {"repo": "a/b", "issue": 7,
           "sovereign_admission": True,
           "admission": {"funding": {"amount": "900", "usd_value": "900"}},
           "competition": {"blocking": False, "verdict": "clear: no competing claimant"}}
    row.update(overrides)
    return row


class AgentRowsAreReFetched(unittest.TestCase):
    def test_a_readable_issue_is_queued_and_stored(self):
        con = database()
        api = FakeApi({"a/b#7": issue(7)})
        result = actions_dispatch.queue_agent_rows(con, api, [stamped()])
        self.assertEqual(len(result["queued"]), 1)
        row = con.execute("SELECT payload,lanes,status FROM pending").fetchone()
        self.assertEqual(json.loads(row[1]), ["agent"])
        self.assertEqual(row[2], "pending")
        self.assertEqual(json.loads(row[0])["number"], 7)

    def test_an_unreadable_issue_is_never_queued_on_the_agents_word(self):
        con = database()
        api = FakeApi(fail={"a/b#7"})
        result = actions_dispatch.queue_agent_rows(con, api, [{"repo": "a/b", "issue": 7}])
        self.assertEqual(result["queued"], [])
        self.assertEqual(result["skipped"][0]["reason"], "ISSUE_UNREADABLE")
        self.assertEqual(con.execute("SELECT count(*) FROM pending").fetchone()[0], 0)

    def test_a_pull_request_is_not_an_issue(self):
        con = database()
        pr = issue(9)
        pr["pull_request"] = {"url": "x"}
        api = FakeApi({"a/b#9": pr})
        result = actions_dispatch.queue_agent_rows(con, api, [{"repo": "a/b", "issue": 9}])
        self.assertEqual(result["queued"], [])
        self.assertEqual(result["skipped"][0]["reason"], "NOT_AN_ISSUE")

    def test_a_malformed_row_costs_no_api_call(self):
        con = database()
        api = FakeApi()
        result = actions_dispatch.queue_agent_rows(
            con, api, [{"repo": "a/b", "issue": "seven"}, {"issue": 3}])
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(api.calls, [])

    def test_the_agent_lane_is_recorded_with_its_expression(self):
        con = database()
        api = FakeApi({"a/b#7": issue(7)})
        actions_dispatch.queue_agent_rows(con, api, [stamped()])
        lane, expression = con.execute(
            "SELECT lane,expression FROM task_expression").fetchone()
        self.assertEqual((lane, expression),
                         (actions_dispatch.AGENT_LANE, actions_dispatch.AGENT_EXPRESSION))

    def test_founder_lane_is_recorded_when_provided(self):
        con = database()
        api = FakeApi({"a/b#7": issue(7)})
        result = actions_dispatch.queue_agent_rows(con, api, [stamped(lane="founder")])
        self.assertEqual(len(result["queued"]), 1)
        row = con.execute("SELECT lanes FROM pending").fetchone()
        self.assertEqual(json.loads(row[0]), ["founder"])


if __name__ == "__main__":
    unittest.main()
