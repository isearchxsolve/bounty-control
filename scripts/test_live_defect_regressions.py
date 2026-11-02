"""Regression contracts for the four defects surfaced by the live pipeline suite.

Each test names the run it came from and asserts the behaviour that was wrong, so the
defect cannot come back silently. These are the gate-level facts, not the whole pipeline.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_release as release  # noqa: E402
import live_pipeline_integration as live  # noqa: E402


class BaseRegressionCorroboration(unittest.TestCase):
    """Run 41496156712: a genuinely red base was rejected for phrasing, not for being green."""

    # The exact declaration the agent wrote, and the exact output unittest printed.
    DECLARED = "days_to_seconds(1) == 86400"
    OUTPUT = ("FAIL: test_one_day (r33c5cf9b171f.test_regression.DaysToSecondsRegression.test_one_day)\n"
              "  File \"/tmp/x/live_cases/r33c5cf9b171f/test_regression.py\", line 11, in test_one_day\n"
              "    self.assertEqual(days_to_seconds(1), 86400)\n"
              "AssertionError: 3600 != 86400\n"
              "\nRan 30 tests in 0.007s\n\nFAILED (failures=5)\n")

    def test_a_source_expression_is_corroborated_by_the_traceback_it_produced(self):
        self.assertTrue(release.failure_corroborated(self.DECLARED, self.OUTPUT))

    def test_a_literal_message_still_passes(self):
        self.assertTrue(release.failure_corroborated("AssertionError: 3600 != 86400", self.OUTPUT))

    def test_an_invented_assertion_is_still_refused(self):
        # The run never printed this; a gate that accepts it would accept any claim.
        self.assertFalse(release.failure_corroborated("AssertionError: 1 != 2", self.OUTPUT))
        self.assertFalse(release.failure_corroborated("outage count = 1440", self.OUTPUT))

    def test_a_partially_matching_claim_is_refused(self):
        # One true token is not corroboration: every distinctive token must appear.
        self.assertFalse(release.failure_corroborated("days_to_seconds(1) == 99999", self.OUTPUT))

    def test_an_empty_claim_is_refused(self):
        self.assertFalse(release.failure_corroborated("", self.OUTPUT))
        self.assertFalse(release.failure_corroborated("==", self.OUTPUT))


class NegativeDispatchRef(unittest.TestCase):
    """Run 2026-11-02: the negative case dispatched at a SHA and got HTTP 422 'No ref found'."""

    def test_a_commit_sha_is_refused_as_a_dispatch_ref(self):
        # The guard is the assertion in negative_claim; assert its predicate directly so the
        # contract is testable without a live repository.
        import re
        sha = "b9f245366c7c6d94d52c8be985d41977a7c85187"
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", sha), "SHA must be recognised as a SHA")
        self.assertFalse(re.fullmatch(r"[0-9a-f]{40}", "main"), "a branch name is not a SHA")

    def test_the_guard_exists_in_the_phase(self):
        source = Path(live.__file__).read_text(encoding="utf-8")
        self.assertIn("Negative dispatch needs a branch name", source)
        self.assertIn("re.fullmatch(r'[0-9a-f]{40}', branch)", source)


class ScoutFailureReportsItsReason(unittest.TestCase):
    """Run 2026-11-02: the door died on a 429 and the report said only 'Real scout failed'."""

    def test_the_admit_phase_surfaces_the_scout_tail(self):
        source = Path(live.__file__).read_text(encoding="utf-8")
        self.assertIn("Real scout failed before writing a row", source)
        self.assertIn("scout-result.json", source)


class GitHubErrorsNameTheirEndpoint(unittest.TestCase):
    """Run 41488848364: publish failed with a bare 404 that named no endpoint."""

    def test_a_terminal_error_carries_the_endpoint(self):
        source = (Path(live.__file__).parent / "actions_github.py").read_text(encoding="utf-8")
        self.assertIn("[endpoint:", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
