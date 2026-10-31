"""A bounty is released by a claim, not by a merge - and this house never claimed.

Measured 2026-10-30 from the live API: 66 published PRs, 64 of them external, 47 closed unmerged,
**0 reviewed and 0 merged**; the single merge on the account is our own `bounty-proof#6`. `/claim`
appeared nowhere in this codebase. Both platforms require it and neither pays on merge - Opire:
"Claiming a bounty never creates an automatic payment"; Algora: the maintainer must "visit your org
dashboard to reward". Without the claim the payer is never notified at all.

The token is emitted only when a trusted bounty bot has actually spoken on the issue, because a bare
`/claim` on a non-platform issue is precisely the "vibe code bounty tracker" signal fyne#1062
pushed back on in public.
"""
import unittest
from unittest import mock

import actions_delivery as delivery


def context_with(*logins, body=""):
    return {"title": "page_bounds drops the last item of every full page",
            "body": body,
            "comments": [{"user": {"login": login}, "body": "bot text"} for login in logins]}


class ClaimLineTests(unittest.TestCase):

    def test_algora_bot_produces_a_claim(self):
        self.assertEqual(delivery.claim_line(context_with("algora-pbc"), 42), "/claim #42")

    def test_opire_bot_produces_a_claim(self):
        self.assertEqual(delivery.claim_line(context_with("opire[bot]"), 7), "/claim #7")

    def test_polar_bot_produces_a_claim(self):
        self.assertEqual(delivery.claim_line(context_with("polar-sh[bot]"), 9), "/claim #9")

    def test_human_chatter_produces_no_claim(self):
        ctx = context_with("andydotxyz", body="Thanks to the sponsorship the bounty is now $1000")
        self.assertEqual(delivery.claim_line(ctx, 1062), "")

    def test_prose_mentioning_a_platform_is_not_a_platform(self):
        """A maintainer writing "this is not an algora bounty" must not make us claim."""
        ctx = context_with("someone", body="This is not an algora bounty, please stop.")
        self.assertEqual(delivery.claim_line(ctx, 5), "")

    def test_no_comments_produces_no_claim(self):
        self.assertEqual(delivery.claim_line({"title": "t", "comments": []}, 1), "")

    def test_missing_comments_key_is_safe(self):
        self.assertEqual(delivery.claim_line({"title": "t"}, 1), "")


class PrBodyTests(unittest.TestCase):

    receipt = {"base_sha": "9fee2527", "run_url": "https://example/run/1"}
    rows = [{"argv": ["pytest", "-q"], "exit_code": 0, "duration_s": 1.5}]

    def test_claim_is_present_when_a_platform_spoke(self):
        body = delivery.pr_body(context_with("algora-pbc"), 42, self.receipt, "abc123",
                                self.rows, "/claim #42")
        self.assertTrue(body.startswith("Resolves #42"))
        self.assertIn("/claim #42", body)
        self.assertIn("Verified base: 9fee2527", body)
        self.assertIn("Execution receipt: https://example/run/1", body)

    def test_claim_is_absent_without_a_platform(self):
        body = delivery.pr_body(context_with("maintainer"), 42, self.receipt, "abc123", self.rows, "")
        self.assertNotIn("/claim", body)
        self.assertIn("Regression: the companion test fails", body)

    def test_claim_sits_before_the_evidence_not_after(self):
        body = delivery.pr_body(context_with("opire[bot]"), 7, self.receipt, "abc", self.rows,
                                "/claim #7")
        self.assertLess(body.index("/claim #7"), body.index("Verified base:"))

    def test_sponsor_rail_is_present_in_footer(self):
        body = delivery.pr_body(context_with("maintainer"), 42, self.receipt, "abc123", self.rows, "")
        self.assertIn("https://github.com/sponsors/isearchxsolve", body)
        self.assertIn("Sponsorship & Direct Payout Rail:", body)


class PostClaimTests(unittest.TestCase):

    def test_claiming_an_open_pr_posts_a_pr_comment(self):
        api = mock.Mock()
        self.assertTrue(delivery.post_claim(api, "o/r", 88, "/claim #7"))
        api.api.assert_called_once_with("repos/o/r/issues/88/comments", "POST",
                                        {"body": "/claim #7"})

    def test_a_failed_claim_is_reported_and_never_raised(self):
        api = mock.Mock()
        api.api.side_effect = delivery.GitHubError("403")
        self.assertFalse(delivery.post_claim(api, "o/r", 88, "/claim #7"))


if __name__ == "__main__":
    unittest.main()
