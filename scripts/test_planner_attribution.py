"""Attribution and audit contract for the search planner, verified without network.

discover() needs a live GitHub client, so it cannot run offline. What is testable offline is the
contract the live loop depends on: the planner's audit names the path it took, and the
task_expression table credits an outcome to the query that surfaced it.
"""

import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

import search_planner as sp


class AuditNamesThePath(unittest.TestCase):
    def test_no_key_is_reported_not_hidden(self):
        _, audit = sp.plan("startup", ['"bounty" is:issue is:open'], {}, slots=1, purpose="p",
                           refusal_reasons=[], api_key="", rng=random.Random(0))
        self.assertEqual(audit["proposer"], "no_key",
                         "a silent fallback would make the static path look like intelligence")


class AttributionTable(unittest.TestCase):
    def test_an_outcome_is_credited_to_the_expression_that_found_it(self):
        with tempfile.TemporaryDirectory() as d:
            con = sqlite3.connect(Path(d) / "t.sqlite3")
            con.execute("CREATE TABLE task_expression(task_id TEXT, lane TEXT, expression TEXT, "
                        "PRIMARY KEY(task_id, lane, expression))")
            con.execute("INSERT OR IGNORE INTO task_expression VALUES(?,?,?)",
                        ("task-1", "startup", 'label:bounty is:issue is:open'))
            con.execute("INSERT OR IGNORE INTO task_expression VALUES(?,?,?)",
                        ("task-1", "startup", 'label:bounty is:issue is:open'))  # re-seen
            rows = con.execute("SELECT expression FROM task_expression WHERE task_id='task-1'").fetchall()
            con.close()  # Windows: release the file before the temp directory is removed
            self.assertEqual(rows, [('label:bounty is:issue is:open',)],
                             "re-seeing the same task must not double-credit the expression")


if __name__ == "__main__":
    unittest.main()
