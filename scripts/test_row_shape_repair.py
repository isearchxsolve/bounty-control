"""The row the door threw away on a field name, and the repair round that never ran.

Measured 2026-11-02, run 41517665373. The agent produced a complete, verified row:
correct repo, OWNER-authored issue, bug reproduced by execution, blob SHA confirmed
against the GitHub API, zero competing PRs. It named the issue ``issue_number``.
The door read ``issue``, got None, and refused the whole row as MALFORMED_ROW. The
run died with rows=1, admitted=0, refused=1.

Two defects, and the second is the one that made the first fatal:

1. verify_rows() read one field name and discarded the row when it was spelled
   differently. A field name is a fact, not a judgement.
2. agent_door.find_issues() defaulted to rounds=1, so the repair machinery that
   exists to catch exactly this -- FEEDBACK_PROMPT, render_meanings(),
   render_shape_note() -- was unreachable in the live path.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_door  # noqa: E402
import cline_entry_door as door  # noqa: E402

# The row, verbatim from the retained shortlist.jsonl of run 41517665373.
MEASURED_ROW = {
    "repo": "isearchxsolve/oss-hunter-livefire",
    "issue_number": 10,
    "source_lane": "founder",
    "is_founder_wound": True,
    "funding": {"payer": "isearchxsolve",
                "source_url": "https://github.com/isearchxsolve/oss-hunter-livefire/issues/10"},
    "scope_quote": "Correct the conversion for all nonnegative integer inputs.",
    "code_evidence": {"path": "live_cases/rc3b74de3bb46/duration.py",
                      "sha": "9b8722e2cfd731b799beaff71d56ca9dfb92bf57",
                      "quote": "    return days * 3600", "is_product_code": True},
}


class RowIssueFieldNames(unittest.TestCase):
    """The measured row must be readable under the name the agent actually used."""

    def test_the_measured_row_yields_its_issue_number(self):
        self.assertEqual(door.row_issue(MEASURED_ROW), 10)

    def test_the_canonical_name_still_wins(self):
        self.assertEqual(door.row_issue({"repo": "a/b", "issue": 7}), 7)

    def test_a_numeric_string_is_read_not_refused(self):
        self.assertEqual(door.row_issue({"repo": "a/b", "issue": "42"}), 42)
        self.assertEqual(door.row_issue({"repo": "a/b", "issue_number": " 42 "}), 42)

    def test_a_boolean_is_not_an_issue_number(self):
        # True == 1 in Python; a bool must never be read as issue 1.
        self.assertIsNone(door.row_issue({"repo": "a/b", "issue": True}))

    def test_a_missing_issue_stays_missing(self):
        self.assertIsNone(door.row_issue({"repo": "a/b"}))
        self.assertIsNone(door.row_issue({"repo": "a/b", "issue": None}))
        self.assertIsNone(door.row_issue({"repo": "a/b", "issue": "not-a-number"}))


class TheMeasuredRowIsNoLongerMalformed(unittest.TestCase):
    """End to end through verify_rows: the row must get past the shape gate."""

    def test_the_measured_row_is_not_refused_as_malformed(self):
        fetched = {"state": "open", "title": "duration helper", "body": "fix it",
                   "comments": 0, "author_association": "OWNER"}
        result = door.verify_rows([MEASURED_ROW], fetch=lambda repo, number: fetched,
                                  limit=0)
        reasons = [entry.get("reason") for entry in result["refused"]]
        self.assertNotIn("MALFORMED_ROW", reasons,
                         "a complete row must not be refused for its field name")

    def test_a_row_with_no_repo_is_still_malformed(self):
        result = door.verify_rows([{"issue": 10}], fetch=lambda r, n: None, limit=0)
        self.assertEqual([e.get("reason") for e in result["refused"]], ["MALFORMED_ROW"])


class TheRepairRoundIsReachable(unittest.TestCase):
    """rounds=1 made the whole feedback path dead code in the live pipeline."""

    def test_the_live_door_runs_more_than_one_round(self):
        import inspect
        default = inspect.signature(agent_door.find_issues).parameters["rounds"].default
        self.assertGreater(default, 1,
                           "a single round means a refused row is never repaired")

    def test_the_repair_prompt_names_shape_faults(self):
        refusals = [{"row": MEASURED_ROW, "reason": "MALFORMED_ROW"}]
        note = door.render_shape_note([], refusals)
        self.assertIn("MALFORMED_ROW", note)
        self.assertIn("field by field", note)

    def test_the_repair_prompt_explains_the_reason_it_fired(self):
        refusals = [{"row": MEASURED_ROW, "reason": "MALFORMED_ROW"}]
        meanings = door.render_meanings(refusals)
        self.assertIn("MALFORMED_ROW", meanings)
        self.assertIn("repo and issue", meanings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
