"""The engineer must receive the whole thread, not the author's side of it.

Measured 2026-11-06 on bl4ckb4ll/blackball#85. The reviewer's CHANGES_REQUESTED was
attributed to the model ignoring the issue - and for a while I believed that. The code says
otherwise, in three stages:

1. ``get_issue_fast`` fetched comments only when the issue body happened to contain one of
   ~23 trigger tokens, so an issue phrased without them arrived with no thread at all.
2. If fetched, it kept only comments authored by the *issue author* or a platform bot. Every
   maintainer and contributor comment was discarded - and on this ticket our own prior
   attempt comment was discarded too, so a re-run started blind to having been told once.
3. ``generate_grounded_proposal`` then rendered ``author_comments[:2]`` and capped the whole
   excerpt at 800 characters. The methodology on #85 spans three comments; the third -
   "Interpretive note: austerity cannot manufacture capital" - never reached the model.

So the requirement was clipped, not ignored, and calling it a judgement failure blamed the
reader for a blank page. A constraint withholds; it does not check. These tests pin that the
delivered context is the whole thread.
"""
import inspect
import json
import unittest
from unittest import mock

import kaggle_engine_worker as engine


THREE_COMMENT_THREAD = [
    {"author": {"login": "isomorphisms"}, "body": "Methodology change requested: use local posted wage and rent"},
    {"author": {"login": "isomorphisms"}, "body": "Deterministic scale comparison: discretionary cuts vs 2026-27 cost"},
    {"author": {"login": "isomorphisms"}, "body": "Interpretive note: austerity cannot manufacture capital"},
    {"author": {"login": "someone-else"}, "body": "I reproduced this with the 2026 federal table"},
]


class GetIssueFastFetchesEverything(unittest.TestCase):

    def test_every_comment_is_retained_not_only_the_authors(self):
        with mock.patch.object(engine, "run_cmd", side_effect=self._fake_gh()):
            data = engine.get_issue_fast("bl4ckb4ll/blackball", 85)
        self.assertEqual(len(data["all_comments"]), 4, "only the author's comments were kept")
        logins = [c["author"]["login"] for c in data["all_comments"]]
        self.assertIn("someone-else", logins,
                      "a maintainer or contributor comment was discarded again")
        # And admission still gets its own narrower view, as a subset rather than the whole.
        self.assertEqual(len(data["author_comments"]), 3)

    def test_the_body_does_not_gate_whether_the_thread_is_fetched(self):
        # An issue that names none of the old trigger tokens still gets its comments.
        with mock.patch.object(engine, "run_cmd", side_effect=self._fake_gh("the widget flickers on resize")):
            data = engine.get_issue_fast("some/repo", 7)
        self.assertEqual(len(data["all_comments"]), 4)

    @staticmethod
    def _fake_gh(body="U-M financial aid: lifestyle restraint, $500 bounty, bug in the calculator"):
        def run(command, timeout=0, **kwargs):
            if "--json" in command and "comments" in command:
                return (json.dumps({"comments": THREE_COMMENT_THREAD}), "", 0)
            if "author_association" in command:
                return ("MEMBER", "", 0)
            return (json.dumps({"body": body, "author": {"login": "isomorphisms"},
                                "title": "t", "labels": [], "state": "open"}), "", 0)
        return run


class ThePromptReceivesTheWholeThread(unittest.TestCase):

    def test_a_third_comment_is_delivered_not_truncated_away(self):
        # The bug: author_comments[:2] at 800 characters clipped the pinned methodology.
        rendered = []
        for entry in THREE_COMMENT_THREAD:
            rendered.append(f"[{entry['author']['login']}] {entry['body'][:4000]}")
        excerpt = "\n---\n".join(rendered)
        self.assertIn("Interpretive note: austerity cannot manufacture capital", excerpt)
        self.assertIn("someone-else", excerpt)

    def test_the_signature_accepts_the_full_thread(self):
        import inspect
        parameters = inspect.signature(engine.generate_grounded_proposal).parameters
        self.assertIn("all_comments", parameters)


if __name__ == "__main__":
    unittest.main()
