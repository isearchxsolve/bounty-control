"""Non-code deliverables must be refused at dispatch, not refused by the engineer after a claim.

Measured 2026-10-30: better-feedback/better-commons#3 ("Content bounty: ...") and
ProjectWyvern/frontends#1 ("Concept design: ...") both passed the dispatch-time classifier through
its fail-open tail, reached engine2.yml, and were refused there as content and design work. Each
spent a claim and a checkout to learn what the title already said.
"""

import unittest

import actions_dispatch as ad


class NonCodeDeliverablesAreRefusedEarly(unittest.TestCase):
    def test_measured_content_bounty_is_refused(self):
        ok, reason = ad.is_code_change_request("Content bounty: Convictio", "", [])
        self.assertFalse(ok)
        self.assertIn("non_code_deliverable", reason)

    def test_measured_concept_design_is_refused(self):
        ok, reason = ad.is_code_change_request(
            "Concept design: smart contract marketplace",
            "Design a set of desktop web pages for the marketplace.", [])
        self.assertFalse(ok)
        self.assertIn("non_code_deliverable", reason)


class CodeWorkIsNotRefusedByThisClass(unittest.TestCase):
    def test_a_real_bug_with_a_traceback_is_admitted(self):
        ok, _ = ad.is_code_change_request(
            "Fix crash when saving empty file",
            "Steps to reproduce: save empty file. Traceback: KeyError 'cursor'", ["bug"])
        self.assertTrue(ok)

    def test_documentation_work_is_not_swept_up(self):
        ok, reason = ad.is_code_change_request(
            "Add documentation for the retry API", "Document parse_config in docs/api.md", [])
        self.assertTrue(ok, reason)

    def test_a_design_bug_with_a_code_label_is_admitted(self):
        ok, _ = ad.is_code_change_request(
            "Design mockup export crashes", "Exporting the mockup raises KeyError in render.py",
            ["bug"])
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
