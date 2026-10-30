"""The timeline branch and the open-PR loop must judge a claimant the same way.

Before this test existed, `competition()` considered a linked pull request fatal if it was open,
while a pull request matching the issue in its title or body was weighed by
`competition_evidence()`. The same PR could therefore be nominal in one loop and blocking in the
other, and a funded ticket that passed every other gate died in the timeline loop alone.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).parent


class TimelineUsesEvidence(unittest.TestCase):
    def test_linked_open_pr_is_weighed_not_refused(self):
        source = (HERE / "bounty_admission.py").read_text(encoding="utf-8")
        timeline = source.split('for event in api.pages(f"repos/{repo}/issues/{number}/timeline")', 1)[1]
        body = timeline.split('if pull.get("merged_at")', 1)[0]
        self.assertIn('competition_evidence(api, repo, pull)', body,
                      "a linked open PR must be judged by evidence")
        self.assertIn('nominal.append(evidence)', body,
                      "a nominal claimant must be recorded, not silently dropped")
        self.assertNotIn('raise ValueError("Linked open PR: " + pull["html_url"])\n        if pull',
                         body,
                         "the unconditional refusal is what blocked four funded tickets")

    def test_both_loops_share_one_evidence_function(self):
        source = (HERE / "bounty_admission.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("competition_evidence(api, repo, pull)"), 2)


if __name__ == "__main__":
    unittest.main()
