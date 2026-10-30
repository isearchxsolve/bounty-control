"""Refusal gates added 2026-10-30, pinned against the measured Cline refusals.

Two contracts, in this order of importance:

1. No false negative. The 45 hand-labelled ``needs_code_change`` items in
   ``f11_sample/f11_labeling_sample_60.json`` must still be admitted. A precision gain that
   refuses a real bug is a loss, not a win.
2. Each measured refusal class is refused, with a class token the dispatcher can count.

Fixtures are written by ``scripts/replay_refusals.py --write-fixtures``; they are real issue
text, not invented samples. If the fixture file is absent the class tests skip rather than
pass silently, so a missing measurement can never look like coverage.
"""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from actions_dispatch import is_code_change_request  # noqa: E402

REFUSALS = HERE / "f9_sample" / "f9_refusals_16.json"
SAMPLE = HERE / "f11_sample" / "f11_labeling_sample_60.json"

# The token each class must produce, so the dispatcher's counters stay stable.
# Only classes that survived the false-negative measurement appear here:
# BOT_ADVERTISEMENT is already covered by the external branch (pinned below), and
# keyword_spam was disqualified for refusing a genuine code-change request.
EXPECTED_TOKEN = {
    "AUTO_DIGEST": "auto_digest",
    "QUESTION": "question_without_defect",
    "UMBRELLA": "umbrella_request",
    "HARDWARE_PRODUCT": "hardware_product",
    "VIDEO_DELIVERABLE": "video_deliverable",
}


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class ZeroFalseNegativeTests(unittest.TestCase):
    """The guard that outranks every gate."""

    def test_no_gate_refuses_a_labelled_code_change(self):
        refused = []
        for item in load(SAMPLE):
            if item["hand_label"] != "needs_code_change":
                continue
            admitted, reason = is_code_change_request(
                item.get("title", ""), item.get("body_preview", ""), item.get("labels", []))
            if not admitted:
                refused.append((item["repo"], item["number"], reason))
        self.assertEqual(refused, [], "a gate refused a genuine code-change request: "
                                      + json.dumps(refused[:5]))


class RefusalGateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not REFUSALS.exists():
            raise unittest.SkipTest(
                "run scripts/replay_refusals.py --write-fixtures " + str(REFUSALS))
        cls.cases = load(REFUSALS)

    def test_the_fixture_still_carries_its_labels(self):
        """A rerun of replay_refusals.py once erased expected_class, every case was skipped and
        this file passed green with no coverage at all. Pin the label count."""
        labelled = [c for c in self.cases if c.get("expected_class")]
        self.assertEqual(len(labelled), len(self.cases),
                         "unlabelled fixtures: " + str(len(self.cases) - len(labelled)))
        gated = [c for c in self.cases if c.get("expected_class") in EXPECTED_TOKEN]
        self.assertGreaterEqual(len(gated), 8,
                                "too few gated fixtures to be meaningful: " + str(len(gated)))

    def test_every_gated_class_is_refused(self):
        missed = []
        seen = 0
        for case in self.cases:
            expected = case.get("expected_class")
            if expected not in EXPECTED_TOKEN:
                continue
            seen += 1
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            if admitted or EXPECTED_TOKEN[expected] not in reason:
                missed.append((case["repo"] + "#" + str(case["number"]),
                               expected, reason))
        self.assertEqual(missed, [], "gated refusals that still pass: "
                                     + json.dumps(missed[:5]))
        self.assertGreaterEqual(seen, 8, "the loop examined too few cases")

    def test_the_three_already_caught_cases_stay_refused(self):
        """ALREADY_CAUGHT rows are refused today by the external branch - pin that, do not
        duplicate the rule with a second gate."""
        for case in self.cases:
            if case.get("expected_class") != "ALREADY_CAUGHT":
                continue
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            self.assertFalse(admitted, "regressed: " + case["repo"] + "#" + str(case["number"]))
            self.assertIn("external", reason)

    def test_a_refusal_reason_is_countable(self):
        """The dispatcher counts the whole reason string; it must not carry issue text."""
        for case in self.cases:
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            if admitted:
                continue
            self.assertNotIn(case["title"][:20].lower(), reason.lower(),
                             "reason must be a fixed string, not interpolated issue text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
