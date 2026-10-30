#!/usr/bin/env python3
"""F9 contract: the class-level "is this a code change at all?" gate.

The gate must refuse only what it can prove is external or process intent, and fail open
otherwise. Fail-open matters: a false refusal silently removes real supply.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_dispatch import is_code_change_request  # noqa: E402

# The dispatch loop normalises GitHub's dict labels to names before calling the gate, so
# these fixtures use the same shape the live path uses.


class AdmissionTests(unittest.TestCase):
    def test_a_real_bug_report_with_a_file_reference_is_admitted(self):
        admitted, reason = is_code_change_request(
            "Fix crash when parsing config", "The parser in internal/config/parse.go panics.",
            ["bug"])
        self.assertTrue(admitted)
        self.assertEqual(reason, "needs_code_change")

    def test_an_escrow_advertisement_is_refused(self):
        admitted, reason = is_code_change_request(
            "Bounty Seguro (Ver enlace)", "Pago garantizado, see view link", ["escrow"])
        self.assertFalse(admitted)
        self.assertTrue(reason.startswith("REFUSED_NOT_A_CODE_CHANGE"))

    def test_a_triage_or_meta_issue_is_refused(self):
        admitted, reason = is_code_change_request(
            "Triage board for maintainers", "Monthly meta checklist", ["triage"])
        self.assertFalse(admitted)
        self.assertTrue(reason.startswith("REFUSED_NOT_A_CODE_CHANGE"))

    def test_an_unclassifiable_issue_fails_open(self):
        admitted, reason = is_code_change_request("Something feels off", "Not sure.", [])
        self.assertTrue(admitted)
        self.assertIn(reason, ("needs_code_change", "unclear_fail_open"))

    def test_an_external_pattern_with_a_real_code_label_is_still_admitted(self):
        # Fail-open: a bug label overrides the weaker external signal.
        admitted, _ = is_code_change_request(
            "Payment guaranteed", "escrow bot body", ["bug"])
        self.assertTrue(admitted)

    def test_the_refusal_names_its_class(self):
        admitted, reason = is_code_change_request(
            "Off-repo request", "third-party tooling question", [])
        self.assertFalse(admitted)
        self.assertIn(":", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
