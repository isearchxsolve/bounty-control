"""The second publish path must claim too, and its claim must be a new comment.

Measured 2026-11-06: this engine publishes its own pull requests - ``commit_and_open_pr``
and its recovery path ``resume_verified_publication`` both call ``gh pr create`` - and
neither posted a claim. ``actions_delivery`` had the same defect in a different shape: the
claim was written into the PR body and marked SUBMITTED_UNCONFIRMED without ever being
posted. Both platforms pay on a claim and neither pays on a merge, so a delivered PR with
no claim is unpaid work with a green test suite.

The rule itself is not rewritten here. ``gh issue view --json comments`` names the author
``author`` where the REST API names it ``user``; a second, incompatible shape would make
``claim_line`` return "" forever, which is exactly the silent failure this file guards.
"""
import unittest
from pathlib import Path
from unittest import mock

import kaggle_engine_worker as engine


def gh_comments(*logins):
    return {"comments": [{"author": {"login": login}, "body": "bounty text"} for login in logins]}


class PostBountyClaimTests(unittest.TestCase):

    def setUp(self):
        self.calls = []

    def fake_run(self, command, timeout=0):
        self.calls.append(command)
        if command[:2] == ["gh", "issue"]:
            return (__import__("json").dumps(self.comments), "", 0)
        if command[:2] == ["gh", "pr"] and command[2] == "comment":
            return ("", "", 0)
        return ("", "", 1)

    def test_a_platform_bot_makes_the_engine_post_a_claim_comment(self):
        self.comments = gh_comments("algora-pbc")
        with mock.patch.object(engine, "run_cmd", side_effect=self.fake_run):
            claim = engine.post_bounty_claim("owner/repo", 42, "https://github.com/owner/repo/pull/99")
        self.assertEqual(claim, "/claim #42")
        posted = [c for c in self.calls if c[:2] == ["gh", "pr"]]
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][3], "https://github.com/owner/repo/pull/99")
        self.assertIn("/claim #42", posted[0])

    def test_the_gh_author_field_is_translated_for_the_shared_rule(self):
        # gh names it `author`, the REST API names it `user`. Without the translation the
        # claim silently never happens and every test above would still pass.
        self.comments = gh_comments("polar-sh[bot]")
        with mock.patch.object(engine, "run_cmd", side_effect=self.fake_run):
            claim = engine.post_bounty_claim("owner/repo", 7, "https://github.com/owner/repo/pull/1")
        self.assertEqual(claim, "/claim #7")

    def test_human_chatter_is_never_a_claim(self):
        self.comments = gh_comments("maintainer", "random-user")
        with mock.patch.object(engine, "run_cmd", side_effect=self.fake_run):
            claim = engine.post_bounty_claim("owner/repo", 42, "https://github.com/owner/repo/pull/99")
        self.assertIsNone(claim)
        self.assertEqual([c for c in self.calls if c[:2] == ["gh", "pr"]], [])

    def test_a_failed_claim_never_breaks_a_delivered_pr(self):
        self.comments = gh_comments("algora-pbc")

        def failing(command, timeout=0):
            self.calls.append(command)
            if command[:2] == ["gh", "pr"] and command[2] == "comment":
                return ("", "forbidden", 1)
            return (__import__("json").dumps(self.comments), "", 0)

        with mock.patch.object(engine, "run_cmd", side_effect=failing):
            claim = engine.post_bounty_claim("owner/repo", 42, "https://github.com/owner/repo/pull/99")
        self.assertIsNone(claim)

    def test_both_publish_paths_claim(self):
        source = Path(engine.__file__).read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("post_bounty_claim("), 3,
                                "the helper, the primary publish path and the recovery path "
                                "must all mention the claim; the recovery path is the one "
                                "that ran for every PR in the record")


if __name__ == "__main__":
    unittest.main()
