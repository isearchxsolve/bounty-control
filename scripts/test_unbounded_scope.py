"""A funded wish is still a wish, and must be refused before it costs a claim.

Measured 2026-10-30: microg/GmsCore#1272, USD 300 from bountyhub-app, passed admission, took a
claim and a real repository checkout, and was then refused by the engineer as unbounded R&D. The
money made a one-sentence 2020 feature wish look like work. This gate refuses it at the door.

The second half of the rule matters as much as the first: a polite request that carries a
traceback, a reproduction, expected-versus-actual, or a located source file is an ordinary bug
report and must never be refused by this gate.
"""

import unittest

import bounty_admission


def context(title, body, *, funded=True, labels=()):
    comments = []
    if funded:
        comments.append({"user": {"login": "bountyhub-app[bot]"},
                         "author_association": "NONE",
                         "body": "$300.00 bounty for this issue.",
                         "html_url": "https://github.com/acme/widget/issues/7#issuecomment-1"})
    return {"issue": {"title": title, "body": body, "state": "open",
                      "user": {"login": "owner-user"}, "labels": list(labels),
                      "comments": len(comments),
                      "html_url": "https://github.com/acme/widget/issues/7"},
            "repository": {"full_name": "acme/widget",
                           "owner": {"login": "owner-user"},
                           "archived": False, "disabled": False,
                           "name": "widget"},
            "complete_comments": True, "comments": comments, "repo": "acme/widget",
            "html_url": "https://github.com/acme/widget/issues/7",
            "fetched_at": "2026-10-30T00:00:00+00:00"}


class WishIsRefusedAtTheDoor(unittest.TestCase):
    def test_the_measured_microg_wish_is_refused(self):
        ctx = context("Implementation of Nearby Share",
                      "Is it possible to add Nearby Share to MicroG and also make it work with "
                      "the normal Play Services?")
        proof, reason = bounty_admission.admit(ctx)
        self.assertIsNone(proof)
        self.assertEqual(reason, "UNBOUNDED_SCOPE")

    def test_the_wish_gate_does_not_need_the_money_to_exist(self):
        ctx = context("Add support for Foo", "Please add support for Foo.", funded=False)
        proof, reason = bounty_admission.admit(ctx)
        self.assertIsNone(proof)


class AnchoredWorkIsNotRefused(unittest.TestCase):
    def test_wish_phrasing_with_a_traceback_passes(self):
        ctx = context("Is it possible to fix the sync crash?",
                      "Is it possible to fix this? Traceback (most recent call last):\n"
                      "  File \"sync.py\", line 42, in run\nKeyError: 'cursor'")
        reason = bounty_admission.unbounded_scope(ctx, bounty_admission.engineering_evidence(
            ctx["issue"]["title"], ctx["issue"]["body"], "acme/widget", issue_context=ctx))
        self.assertIsNone(reason)

    def test_expected_actual_report_is_not_a_wish(self):
        ctx = context("Upload returns 500",
                      "Steps to reproduce: upload a 2 MB png. Expected 200, actual 500.")
        reason = bounty_admission.unbounded_scope(ctx, bounty_admission.engineering_evidence(
            ctx["issue"]["title"], ctx["issue"]["body"], "acme/widget", issue_context=ctx))
        self.assertIsNone(reason)

    def test_a_plain_defect_issue_is_untouched(self):
        ctx = context("Race condition in the scheduler",
                      "Two workers pick the same job. Deadlock in queue.py when concurrent.")
        proof, reason = bounty_admission.admit(ctx)
        self.assertNotEqual(reason, "UNBOUNDED_SCOPE")


if __name__ == "__main__":
    unittest.main()
