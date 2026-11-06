"""A maintainer's review must reach the next engineering turn, not just our own errors.

Measured 2026-11-06: the resume loop feeds the next turn only what our event log recorded --
syntax errors, compiler failures, linter output, network timeouts. A maintainer's verdict
never entered it. On ``fyne-io/fyne#6637`` the reviewer posted a precise, reproducible
regression and the path to the fix, and the re-run started from a clean slate with none of
it. On ``stride3d/stride#3816`` the reviewer wrote "the OP seems like a bot... I'd be very
cautious with this PR" and that sentence was never seen by anything but me.

So Cline was resuming from its own failure checkpoint and structurally blind to the
maintainer's, which is the same defect as the clipped issue thread: a constraint that
withholds, wearing a checkpoint's clothes.
"""
import os
import unittest
from unittest import mock

import actions_delivery as delivery


def review(login, state, body, bot=False):
    user = {"login": login}
    if bot:
        user["type"] = "Bot"
    return {"user": user, "state": state, "body": body}


REVIEWS = [
    review("ub3dqy", "COMMENTED",
           "The native upload-queue check fails in three of four cases; the base passes "
           "all four. A local version that retains separate upload bytes passes all four too."),
    review("isomorphisms", "CHANGES_REQUESTED",
           "fedtax(103350) returns a positive tax, but fedtax(103351) returns zero."),
    review("isearchxsolve", "COMMENTED", "Thanks, I will look at it."),
    review("github-actions", "COMMENTED", "All checks passed.", bot=True),
]

COMMENTS = [
    {"user": {"login": "MsEpsilon"}, "body": "the source looks entirely LLM-generated, I'd be very cautious"},
    {"user": {"login": "isearchxsolve"}, "body": "Pushed a fix."},
    {"user": {"login": "coveralls", "type": "Bot"}, "body": "coverage 61.568%"},
    {"user": {"login": "vercel"}, "body": "deploy preview ready"},
]


class FakeApi:
    def __init__(self):
        self.calls = []

    def api(self, path, *args, **kwargs):
        self.calls.append(path)
        if path.endswith("/reviews?per_page=50"):
            return REVIEWS
        if path.endswith("/comments?per_page=50"):
            return COMMENTS
        return []


class MaintainerReviewFeedbackTests(unittest.TestCase):

    def test_a_reviewers_verdict_reaches_the_resume(self):
        api = FakeApi()
        feedback = delivery.maintainer_review_feedback(api, "fyne-io/fyne", 6637, "isearchxsolve")
        self.assertIn("upload-queue check fails in three of four cases", feedback)
        self.assertIn("fedtax(103350)", feedback)
        self.assertIn("msepsilon", feedback.lower())

    def test_our_own_words_and_machines_are_excluded(self):
        api = FakeApi()
        feedback = delivery.maintainer_review_feedback(api, "fyne-io/fyne", 6637, "isearchxsolve")
        self.assertNotIn("Thanks, I will look at it", feedback)
        self.assertNotIn("Pushed a fix", feedback)
        self.assertNotIn("coverage 61.568", feedback)
        self.assertNotIn("deploy preview ready", feedback)
        self.assertNotIn("All checks passed", feedback)

    def test_a_pr_url_is_understood_as_well_as_a_number(self):
        api = FakeApi()
        feedback = delivery.maintainer_review_feedback(
            api, "fyne-io/fyne", "https://github.com/fyne-io/fyne/pull/6637", "isearchxsolve")
        self.assertIn("upload-queue check fails", feedback)

    def test_an_unreachable_or_malformed_pr_is_empty_not_fatal(self):
        class Boom:
            def api(self, path, *a, **k):
                raise delivery.GitHubError("404")
        self.assertEqual(delivery.maintainer_review_feedback(Boom(), "a/b", None, "x"), "")
        self.assertEqual(delivery.maintainer_review_feedback(FakeApi(), "a/b", "not-a-number", "x"), "")

    def test_a_review_with_no_body_is_skipped_not_rendered_as_empty(self):
        api = FakeApi()
        api.api = lambda path, *a, **k: \
            [review("someone", "COMMENTED", "")] if path.endswith("/reviews") else []
        self.assertEqual(delivery.maintainer_review_feedback(api, "a/b", 1, "isearchxsolve"), "")

    def test_the_number_of_returned_parts_is_bounded(self):
        api = FakeApi()
        feedback = delivery.maintainer_review_feedback(api, "a/b", 1, "isearchxsolve", limit=2)
        self.assertLessEqual(feedback.count("\n---\n"), 1)


class TheResumeCarriesTheReviewer(unittest.TestCase):
    """The wiring, not just the helper: the resume body and feedback must carry it."""

    def test_the_engineer_path_mentions_review_feedback(self):
        with open(delivery.__file__, encoding="utf-8") as handle:
            body_src = handle.read()
        self.assertIn("maintainer_review_feedback(", body_src)
        self.assertIn("feedback = review_feedback", body_src,
                      "the reviewer must reach the next turn's feedback, not only the prompt")

    def test_the_resume_text_tells_the_agent_this_is_the_state_to_resume_from(self):
        with open(delivery.__file__, encoding="utf-8") as handle:
            body_src = handle.read()
        self.assertIn("the state to resume from", body_src)


if __name__ == "__main__":
    unittest.main()
