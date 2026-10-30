"""F1: a prepared baseline is compared by content, not by SHA equality.

Measured need. Two of thirty recorded dispatches died as ``BASELINE_MISMATCH`` because the
gate demanded ``base_sha == live HEAD``. Expensify/App merges ~9.7 pull requests an hour, so
a preparation window of any realistic length always loses that equality -- while the patch
itself may touch a file nobody else changed. Run ``40719193494`` is the proof: the base was
committed at 15:45:21Z, the gate ran at 16:28:18Z, and eight unrelated commits landed inside
those forty-two minutes. The dispatch was thrown away for a race it could not have avoided.

The rule that replaces it is distinctness: the base must still be on the declared branch's
line of history, and no file the plan will touch may have moved since. Anything else keeps
the old refusal, because a patch built on a SHA that is no longer in history is genuinely
unsafe -- the librepods artefact (base ``android/rewrite`` HEAD declared as ``main``) must
still be refused, and test 4 here is its permanent regression guard.

Everything under test is a pure decision over a GitHub compare payload: no network, no git,
no dispatch. The payload shapes are the real API's.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_delivery  # noqa: E402  (path must be set first)

COMPONENT = "src/components/DatePicker/CalendarPicker/Day.tsx"


def comparison(status, live_sha, ahead_by, files):
    """A GitHub ``compare`` payload with only the fields the decision reads."""
    return {"status": status, "ahead_by": ahead_by, "commits": [{"sha": live_sha}],
            "files": [{"filename": name} for name in files]}


class BaselineOverlapTests(unittest.TestCase):
    def test_1_identical_comparison_admits_with_no_overlap(self):
        status, live, overlap, unknown = actions_delivery.baseline_overlap(
            comparison("identical", "a" * 40, 0, []), {COMPONENT})
        self.assertEqual(status, "identical")
        self.assertEqual(overlap, set())
        self.assertFalse(unknown, "an empty file list is a measurement, not an unknown")
        self.assertEqual(live, "a" * 40)

    def test_2_ahead_with_unrelated_churn_is_admitted(self):
        """The Expensify case: eight commits landed, none of them on our component."""
        moved = ["package.json", "src/components/Charts/x.ts", "docs/README.md"]
        status, live, overlap, unknown = actions_delivery.baseline_overlap(
            comparison("ahead", "b" * 40, 8, moved), {COMPONENT})
        self.assertEqual(status, "ahead")
        self.assertEqual(overlap, set(), "unrelated churn must not block a correct patch")
        self.assertFalse(unknown)
        self.assertEqual(live, "b" * 40)

    def test_3_ahead_with_the_component_moved_is_a_race(self):
        moved = ["package.json", COMPONENT]
        _, live, overlap, unknown = actions_delivery.baseline_overlap(
            comparison("ahead", "c" * 40, 8, moved), {COMPONENT})
        self.assertEqual(overlap, {COMPONENT})
        self.assertFalse(unknown)
        race = actions_delivery.PreparationRace("c" * 40, live, sorted(overlap))
        self.assertTrue(race.unknown is False)
        self.assertIn("overlap=", str(race))
        self.assertIn(COMPONENT, str(race))

    def test_4_diverged_is_still_a_refusal(self):
        """Permanent guard: the librepods false base must never become deliverable."""
        status, _, _, _ = actions_delivery.baseline_overlap(
            comparison("diverged", "d" * 40, 0, []), {COMPONENT})
        self.assertEqual(status, "diverged")
        with self.assertRaises(ValueError) as raised:
            actions_delivery.require_baseline_relationship(status)
        self.assertIn("not the current upstream default", str(raised.exception))

    def test_only_ancestry_or_equality_is_admitted(self):
        """``behind`` is a descendant base: not reachable from the branch head either."""
        for admitted in ("identical", "ahead"):
            with self.subTest(status=admitted):
                self.assertEqual(
                    actions_delivery.require_baseline_relationship(admitted), admitted)
        for refused in ("diverged", "behind", None, "unknown-status"):
            with self.subTest(status=refused):
                with self.assertRaises(ValueError):
                    actions_delivery.require_baseline_relationship(refused)

    def test_a_missing_files_key_never_reaches_a_decision_for_a_diverged_base(self):
        """Unknown overlap must not soften the history rule: diverged refuses first."""
        payload = comparison("diverged", "d" * 40, 0, [])
        del payload["files"]
        status, _, overlap, unknown = actions_delivery.baseline_overlap(payload, {COMPONENT})
        self.assertEqual(overlap, set())
        self.assertTrue(unknown)
        with self.assertRaises(ValueError):
            actions_delivery.require_baseline_relationship(status)

    def test_5_unrelated_paths_do_not_cause_false_positives(self):
        moved = ["internal/other/file.go", "internal/painter/atlas.go"]
        _, _, overlap, _ = actions_delivery.baseline_overlap(
            comparison("ahead", "e" * 40, 3, moved), {"internal/painter/gl/painter.go"})
        self.assertEqual(overlap, set())

    def test_6_equal_to_live_head_is_admitted_with_ahead_by_zero(self):
        payload = comparison("identical", "f" * 40, 0, [])
        _, live, overlap, _ = actions_delivery.baseline_overlap(payload, {COMPONENT})
        self.assertEqual(live, "f" * 40)
        self.assertEqual(payload["ahead_by"], 0)
        self.assertEqual(overlap, set())

    def test_7_missing_files_key_refuses_closed_and_stays_retryable(self):
        """An absent ``files`` list cannot prove disjointness, so it is unknown, not empty."""
        payload = {"status": "ahead", "ahead_by": 5, "commits": [{"sha": "9" * 40}]}
        _, live, overlap, unknown = actions_delivery.baseline_overlap(payload, {COMPONENT})
        self.assertTrue(unknown, "a missing key is never evidence that nothing changed")
        self.assertEqual(overlap, set())
        race = actions_delivery.PreparationRace("9" * 40, live, set(), unknown=True)
        self.assertTrue(race.unknown)
        self.assertIn("overlap unknown", str(race))

    def test_touched_files_are_derived_from_the_contract_plan(self):
        prepared = {"plan": {"component": COMPONENT}, "regression_plan": {"component": COMPONENT}}
        self.assertEqual(actions_delivery.prepared_touched_files(prepared), {COMPONENT})

    def test_entries_without_a_filename_are_ignored(self):
        payload = comparison("ahead", "7" * 40, 1, [])
        payload["files"] = [{}, {"filename": ""}, {"filename": "other.py"}]
        self.assertEqual(actions_delivery.baseline_overlap(payload, {COMPONENT})[2], set())


class BaselineRelationshipReceiptTests(unittest.TestCase):
    def test_the_receipt_records_every_field_the_blueprint_names(self):
        """The artefact must be readable without a log dig (F1 acceptance criterion)."""
        import tempfile

        names = {"base", "base_branch", "branch_head", "live_sha", "status", "ahead_by",
                 "overlap", "overlap_unknown"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline-relationship.json"
            actions_delivery.write_json_atomic(path, {
                "base": "a" * 40, "base_branch": "main", "branch_head": "b" * 40,
                "live_sha": "b" * 40, "status": "ahead", "ahead_by": 8,
                "overlap": [], "overlap_unknown": False,
            })
            document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(document), names)
        self.assertEqual(document["overlap"], [])


if __name__ == "__main__":
    unittest.main()
