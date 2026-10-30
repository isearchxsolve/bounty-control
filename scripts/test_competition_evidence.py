"""A dropped file is not a competitor.

Baba's question, 2026-10-30: "if an issue is damn hard how can competition arise". It was
the right question - if a ticket is genuinely hard, the crowd cannot already have solved
it. Measured on the four funded microG/GmsCore tickets: PRs 3943, 3944, 3945, 3949 were
opened within 36 hours, by three authors who between them had authored five pull requests
in that repository and landed none, with no maintainer review, no maintainer comment and no
successful check run. The old gate refused all four on their mere existence, which inverted
the hardness moat: it refused the hardest, most valuable tickets first, because producing an
unmergeable attempt is now free.

These tests hold the line in both directions: real competition still blocks, and unevaluable
competition still blocks (fail closed). Only a proven-nominal attempt stops blocking.
"""

import unittest

from bounty_admission import competition, competition_evidence


class FakeApi:
    def __init__(self, pull, merged=0, checks=None, reviews=None, comments=None,
                 history_raises=False, pages_raise=False):
        self.pull = pull
        self.merged = merged
        self.checks = checks or []
        self.reviews = reviews or []
        self.comments = comments or []
        self.history_raises = history_raises
        self.pages_raise = pages_raise
        self.search_calls = []

    def api(self, endpoint):
        if endpoint.startswith("search/issues?"):
            self.search_calls.append(endpoint)
            if self.history_raises:
                raise RuntimeError("secondary rate limit")
            return {"total_count": self.merged}
        if "/check-runs" in endpoint:
            if self.history_raises:
                raise RuntimeError("checks unavailable")
            return {"check_runs": self.checks}
        raise AssertionError("unexpected endpoint " + endpoint)

    def pages(self, endpoint, **kwargs):
        if self.pages_raise and (endpoint.endswith("/reviews")
                                 or endpoint.endswith("/comments")):
            raise RuntimeError("maintainer attention unavailable")
        if endpoint.endswith("/reviews"):
            return self.reviews
        if endpoint.endswith("/comments"):
            return self.comments
        if endpoint.endswith("/pulls"):
            return [self.pull]
        if endpoint.endswith("/timeline"):
            return []
        raise AssertionError("unexpected pages " + endpoint)


def drive_by(number=3944, login="MilindChatrabhuji"):
    return {"number": number, "user": {"login": login}, "title": "fix #1272",
            "body": "", "head": {"ref": "feat/x", "sha": "abc", "repo": None},
            "html_url": "https://github.com/microg/GmsCore/pull/3944"}


class RealCompetitionStillBlocks(unittest.TestCase):
    def test_author_who_has_landed_work_here_blocks(self):
        api = FakeApi(drive_by(), merged=2)
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_green_checks_block(self):
        api = FakeApi(drive_by(), merged=0, checks=[{"conclusion": "success"}])
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_maintainer_review_blocks(self):
        api = FakeApi(drive_by(), merged=0,
                      reviews=[{"author_association": "MEMBER"}])
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_maintainer_comment_blocks(self):
        api = FakeApi(drive_by(), merged=0,
                      comments=[{"author_association": "OWNER"}])
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_unavailable_author_history_blocks(self):
        api = FakeApi(drive_by(), history_raises=True)
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_unavailable_maintainer_attention_blocks(self):
        api = FakeApi(drive_by(), merged=0, pages_raise=True)
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)

    def test_a_pr_that_does_not_mention_the_issue_never_blocks(self):
        pull = dict(drive_by(), title="unrelated cleanup", body="")
        api = FakeApi(pull, merged=9)
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertEqual(verdict["nominal"], [])


class NominalAttemptsNoLongerBlock(unittest.TestCase):
    def test_drive_by_by_a_stranger_is_named_and_ignored(self):
        api = FakeApi(drive_by(), merged=0, checks=[], reviews=[], comments=[])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"])
        self.assertEqual(len(verdict["nominal"]), 1)
        self.assertEqual(verdict["nominal"][0]["reason"], "nominal_attempt_only")
        self.assertEqual(verdict["nominal"][0]["author"], "milindchatrabhuji")
        self.assertEqual(verdict["nominal"][0]["author_merged_in_repo"], 0)

    def test_a_failing_check_run_is_not_authority_to_block(self):
        api = FakeApi(drive_by(), merged=0, checks=[{"conclusion": "failure"}])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"])

    def test_a_stranger_comment_is_not_maintainer_attention(self):
        api = FakeApi(drive_by(), merged=0, comments=[{"author_association": "NONE"}])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"])

    def test_the_evidence_is_measured_not_assumed(self):
        api = FakeApi(drive_by(), merged=0)
        competition_evidence(api, "microg/GmsCore", drive_by())
        self.assertTrue(api.search_calls, "author history must be asked for")
        self.assertIn("is%3Amerged", api.search_calls[0])


if __name__ == "__main__":
    unittest.main()
