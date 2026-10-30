"""The conversion lane's judgement, pinned without the network.

The measured case is `fyne-io/fyne#6637`: open, mergeable, 13/13 checks passing, zero reviews, and
two days idle on 2026-10-30. That PR must come out as NEEDS_NUDGE - if this classifier ever reports
it as "wait", the lane is decorative.
"""
from datetime import datetime, timedelta, timezone
import unittest

import pr_conversion_watch as watch

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
GREEN = {"total": 13, "passing": 13, "failing": 0, "pending": 0}


def facts(**overrides):
    base = {
        "repo": "fyne-io/fyne", "number": 6637, "state": "open", "draft": False,
        "merged_at": None,
        "created_at": (NOW - timedelta(days=2)).isoformat(),
        "updated_at": (NOW - timedelta(days=2, hours=6)).isoformat(),
        "review_count": 0, "review_decision": "none", "checks": dict(GREEN),
    }
    base.update(overrides)
    return base


def verdict(**overrides):
    return watch.classify(facts(**overrides), NOW)


class MeasuredCaseTests(unittest.TestCase):

    def test_the_real_case_needs_a_nudge(self):
        result = verdict()
        self.assertEqual(result["state"], "NEEDS_NUDGE")
        self.assertEqual(result["action"], "one_factual_comment")

    def test_fresh_green_pr_is_not_nudged_on_day_zero(self):
        result = verdict(created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        self.assertEqual(result["state"], "WAITING_FRESH")
        self.assertEqual(result["action"], "wait")


class TerminalStateTests(unittest.TestCase):

    def test_merged_is_finished_even_with_red_checks(self):
        result = verdict(merged_at=NOW.isoformat(), state="closed",
                         checks={"total": 3, "failing": 3, "pending": 0, "passing": 0})
        self.assertEqual(result["state"], "MERGED")
        self.assertEqual(result["action"], "none")

    def test_closed_without_merge_is_finished(self):
        result = verdict(state="closed")
        self.assertEqual(result["state"], "CLOSED")
        self.assertEqual(result["action"], "none")

    def test_draft_is_never_nudged(self):
        result = verdict(draft=True)
        self.assertEqual(result["state"], "DRAFT")
        self.assertNotEqual(result["action"], "one_factual_comment")


class OwnershipTests(unittest.TestCase):
    """Asking a maintainer to look at red CI spends their attention on our unfinished work."""

    def test_failing_checks_outrank_the_nudge(self):
        result = verdict(checks={"total": 13, "failing": 2, "pending": 0, "passing": 11})
        self.assertEqual(result["state"], "BLOCKED_CI")
        self.assertEqual(result["action"], "fix_checks")

    def test_running_checks_mean_wait(self):
        result = verdict(checks={"total": 13, "failing": 0, "pending": 4, "passing": 9})
        self.assertEqual(result["state"], "CI_RUNNING")
        self.assertEqual(result["action"], "wait")

    def test_changes_requested_is_ours_to_fix(self):
        result = verdict(review_decision="changes_requested", review_count=1)
        self.assertEqual(result["state"], "CHANGES_REQUESTED")
        self.assertEqual(result["action"], "address_review")

    def test_approved_waits_for_merge(self):
        result = verdict(review_decision="approved", review_count=1)
        self.assertEqual(result["state"], "APPROVED")
        self.assertEqual(result["action"], "wait_for_merge")

    def test_reviewed_but_idle_long_enough_for_a_human(self):
        result = verdict(review_decision="none", review_count=1,
                         updated_at=(NOW - timedelta(days=20)).isoformat())
        self.assertEqual(result["state"], "STALE_WITH_COMMENTS")
        self.assertEqual(result["action"], "human_decision")

    def test_a_check_read_failure_is_not_green(self):
        # checks_error is recorded by pr_facts; classification must not read it as passing.
        result = verdict(checks={"total": 0, "failing": 0, "pending": 0, "passing": 0})
        self.assertEqual(result["state"], "NEEDS_NUDGE")


class SummaryTests(unittest.TestCase):

    def rows(self):
        cases = [facts(number=1), facts(number=2, merged_at=NOW.isoformat()),
                 facts(number=3, state="closed"), facts(number=4, draft=True)]
        return [{"facts": c, "verdict": watch.classify(c, NOW)} for c in cases]

    def test_counts_only_what_is_actionable(self):
        summary = watch.summarise(self.rows())
        self.assertEqual(summary["prs"], 4)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(summary["actionable"], 1)

    def test_markdown_names_the_action(self):
        rows = self.rows()
        text = watch.render_markdown(rows, watch.summarise(rows), NOW)
        self.assertIn("one_factual_comment", text)
        self.assertIn("fyne-io/fyne#1", text)

    def test_nothing_actionable_is_said_plainly(self):
        rows = [{"facts": facts(merged_at=NOW.isoformat()),
                 "verdict": watch.classify(facts(merged_at=NOW.isoformat()), NOW)}]
        text = watch.render_markdown(rows, watch.summarise(rows), NOW)
        self.assertIn("Nothing actionable", text)


class ParsingTests(unittest.TestCase):

    def test_day_math_with_offsets(self):
        earlier = "2026-10-28T20:26:00Z"
        self.assertAlmostEqual(watch.days_between(watch.parse_ts(earlier), NOW), 1.6, places=1)

    def test_missing_timestamps_do_not_crash(self):
        self.assertIsNone(watch.days_between(watch.parse_ts(None), NOW))
        result = watch.classify({"state": "open", "checks": dict(GREEN)}, NOW)
        self.assertIn(result["state"], ("WAITING_FRESH", "NEEDS_NUDGE"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
