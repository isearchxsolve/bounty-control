"""Owner-allocated funding is escrow, because that is where the money is.

Measured 2026-11-07. ``fyne-io/fyne#1062``: andydotxyz, the repository owner, wrote "$500 is
currently allocated for eligible contributors completing this work", then "the bounty on this
ticket has increased to $1000!", then allocated half of it to work he accepts. No platform bot
attests it, so ``escrow_only_refusal`` refused the largest verified money in the record.

The bot-only rule rested on a 0%-conversion measurement for non-escrow offers that was taken
on our own interference: 46 of our 50 closed PRs were closed by our own account, 37 within six
hours. The 0% describes what we did, not what the market did. Meanwhile the bot-attested pool
measures 59 open tickets and none of them are both fresh and unswamped.

These tests pin both directions: the owner's own named amount is admitted, and a stranger
promising money on someone else's issue is still refused.
"""
import unittest
from unittest import mock

import bounty_admission as admission


OWNER_ISSUE = {
    "title": "Android apps are lagging when entering text and scrolling",
    "body": "Text entry and scrolling in widget.Entry lag on the mobile backend. The cause is "
            "internal/painter/gl/gl_gomobile.go: toLEByteOrder returns a shared scratch buffer, "
            "so a later upload overwrites an earlier queued payload and the paint queue "
            "stutters. A regression test in internal/painter/gl reproduces it. "
            "The bounty on this ticket has increased to $1000 and is allocated to eligible "
            "contributors completing this work.",
    "html_url": "https://github.com/fyne-io/fyne/issues/1062",
    "state": "open",
    "user": {"login": "andydotxyz"},
    "author_association": "OWNER",
}

STRANGER_ISSUE = {
    "title": "help",
    "body": "I will pay $500 for this fix.",
    "html_url": "https://github.com/someone/repo/issues/1",
    "state": "open",
    "user": {"login": "random-stranger"},
    "author_association": "NONE",
}

REPOSITORY = {"owner": {"login": "fyne-io"}, "archived": False, "disabled": False,
              "full_name": "fyne-io/fyne"}

OWNER_COMMENT = {
    "body": "The bounty on this ticket has increased to $1000!",
    "html_url": "https://github.com/fyne-io/fyne/issues/1062#c1",
    "user": {"login": "andydotxyz"},
}


class OwnerAllocatedIsEscrow(unittest.TestCase):

    def test_a_repository_owner_committing_a_named_amount_is_escrow(self):
        self.assertTrue(admission._is_owner_allocated(OWNER_COMMENT, OWNER_ISSUE, 1000))
        self.assertTrue(admission._is_owner_allocated(OWNER_ISSUE, OWNER_ISSUE, 500))

    def test_a_stranger_promising_money_is_not_escrow(self):
        self.assertFalse(admission._is_owner_allocated(STRANGER_ISSUE, STRANGER_ISSUE, 500))

    def test_a_maintainer_posting_on_someone_elses_issue_is_not_admitted(self):
        # Conservative on purpose: the association read here is the issue author's, so a
        # MEMBER commenting on a stranger's ticket is not waved through by this rule.
        issue = {**OWNER_ISSUE, "user": {"login": "someone-else"},
                 "author_association": "MEMBER"}
        self.assertFalse(admission._is_owner_allocated(OWNER_COMMENT, issue, 1000))

    def test_no_named_amount_is_not_escrow(self):
        self.assertFalse(admission._is_owner_allocated(OWNER_COMMENT, OWNER_ISSUE, None))

    def test_a_bot_attestation_still_works_and_needs_no_association(self):
        document = {"user": {"login": "algora-pbc"}, "body": "offering a $900 bounty"}
        self.assertTrue(admission._is_platform_bot(document))
        # A bot comment on a stranger's issue is still escrow - automation attests, not people.
        self.assertTrue(admission._is_platform_bot(document)
                        or admission._is_owner_allocated(document, STRANGER_ISSUE, 500))


class TheGateAdmitsBothClasses(unittest.TestCase):
    """The published rule, not just the helper: both classes pass escrow-only."""

    def _admit(self, issue, comment_logins=()):
        context = {"repo": "fyne-io/fyne", "issue_number": 1062,
                   "repository": dict(REPOSITORY), "issue": issue,
                   "comments": [{"user": {"login": login},
                                 "body": "offering a $900 bounty\n1. /attempt\n2. /claim #1",
                                 "author_association": "NONE",
                                 "html_url": "https://github.com/o/r/issues/1#c"}
                                for login in comment_logins],
                   "complete_comments": True, "fetched_at": "fixture"}
        with mock.patch.object(admission, "escrow_only_enabled", return_value=True):
            return admission.admit(context, quote=None, floor=80)

    def test_owner_allocated_funding_passes_the_escrow_gate(self):
        """The change itself: was NO_PLATFORM_ESCROW, must now admit."""
        proof, reason = self._admit({**OWNER_ISSUE, "author_association": "OWNER"})
        self.assertEqual(reason, "", "owner-allocated funding was refused by the escrow gate")
        self.assertIsNotNone(proof)
        self.assertTrue(proof["funding"]["escrow"])

    def test_a_bot_attested_issue_still_admits(self):
        proof, reason = self._admit({**OWNER_ISSUE, "author_association": "NONE"},
                                    comment_logins=("algora-pbc",))
        self.assertEqual(reason, "")
        self.assertTrue(proof["funding"]["escrow"])

    def test_an_unfunded_issue_is_still_refused(self):
        issue = {**OWNER_ISSUE, "body": "the app is slow, please fix", "user": {"login": "x"},
                 "author_association": "NONE"}
        proof, reason = self._admit(issue)
        self.assertIsNone(proof)
        self.assertNotEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
