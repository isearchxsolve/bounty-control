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


class OutcomeAttribution(unittest.TestCase):
    """Runs the real attribution SQL on a real database with hand-worked answers.

    Expected, worked by hand:
      E1 surfaces t1 (dispatched), t2 (refused, and also rejected by status: counts ONCE), t3 (open).
         -> tasks 3, dispatched 1, refused 1.
      E2 surfaces t4 (refused), t5 (dispatched).
         -> tasks 2, dispatched 1, refused 1.
    """

    def _db(self, directory):
        con = sqlite3.connect(Path(directory) / "attr.sqlite3")
        con.executescript("""
            CREATE TABLE task_expression(task_id TEXT, lane TEXT, expression TEXT,
                                         PRIMARY KEY(task_id, lane, expression));
            CREATE TABLE task_outcome(task_id TEXT PRIMARY KEY, outcome TEXT, at REAL);
            CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT,
                                 signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending');
        """)
        con.executemany("INSERT INTO task_expression VALUES(?,?,?)", [
            ("t1", "startup", "E1"), ("t2", "startup", "E1"), ("t3", "startup", "E1"),
            ("t4", "startup", "E2"), ("t5", "startup", "E2")])
        con.executemany("INSERT INTO task_outcome VALUES(?,?,0)", [
            ("t1", "dispatched"), ("t2", "refused"), ("t4", "refused"), ("t5", "dispatched")])
        con.executemany("INSERT INTO pending(task_id,payload,lanes,signature,status) VALUES(?,?,?,?,?)", [
            ("t1", "{}", "[]", "s", "checked"), ("t2", "{}", "[]", "s", "rejected_repository_intent"),
            ("t3", "{}", "[]", "s", "checked"), ("t4", "{}", "[]", "s", "query_excluded_assigned"),
            ("t5", "{}", "[]", "s", "checked")])
        con.commit()
        return con

    def test_counts_match_the_hand_worked_answers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            con = self._db(d)
            ledger = {}
            credited = sp.attribute(con, ledger)
            con.close()
        self.assertEqual(credited, 2)
        e1, e2 = ledger["startup|E1"], ledger["startup|E2"]
        self.assertEqual((e1["tasks"], e1["dispatched"], e1["refused"]), (3, 1, 1),
                         "a task refused AND rejected by status must count once")
        self.assertEqual((e2["tasks"], e2["dispatched"], e2["refused"]), (2, 1, 1))

    def test_rerunning_attribution_does_not_double_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            con = self._db(d)
            ledger = {}
            sp.attribute(con, ledger)
            sp.attribute(con, ledger)
            con.close()
        self.assertEqual(ledger["startup|E1"]["tasks"], 3)


class OutcomeIsDurable(unittest.TestCase):
    """An outcome must be visible to another connection the moment it is recorded.

    Regression for run 41042914871: hooks written after a commit were never committed, so the
    table stayed empty while hundreds of tasks were refused. A second connection cannot see an
    uncommitted write, so reading through one is the proof.
    """

    def test_a_recorded_outcome_is_visible_to_another_connection(self):
        import tempfile
        import actions_dispatch as ad
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.sqlite3"
            writer = sqlite3.connect(path)
            writer.execute("CREATE TABLE task_outcome(task_id TEXT PRIMARY KEY, outcome TEXT, at REAL)")
            writer.commit()
            ad.record_outcome(writer, "task-9", "refused")
            reader = sqlite3.connect(path)
            rows = reader.execute("SELECT outcome FROM task_outcome WHERE task_id='task-9'").fetchall()
            reader.close()
            writer.close()
        self.assertEqual(rows, [("refused",)], "the outcome was not committed")


if __name__ == "__main__":
    unittest.main()
