"""Read-only regression against the actual Lux nonpayment allegation.

No fabricated public comments, payment, engineering or publication. These probes
verify collection and factual gates; they do not certify an agent's risk judgment.
"""
import unittest

from actions_github import GitHub, GitHubError
from commercial_context import collect, review_refusal, review_revision, sources
from cline_entry_door import model_admission_refusal

REPO, NUMBER = 'Spectral-Finance/lux', 54
WARNING = 'https://github.com/Spectral-Finance/lux/pull/1059#issuecomment-6584678943'


class CommercialLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            api = GitHub()
            cls.context = collect(api, api.issue_context(REPO, NUMBER))
        except (GitHubError, ValueError, OSError) as exc:
            raise unittest.SkipTest('Live commercial sources unavailable: ' + str(exc))
        if not cls.context['commercial_context_complete']:
            raise unittest.SkipTest('Live collection incomplete: ' + str(cls.context['commercial_context_errors']))
        cls.control = review_revision(cls.context)
        cls.target = WARNING

    def test_actual_linked_pr_warning_is_collected_from_the_issue_entry(self):
        actual = next((d for d in sources(self.context) if d.get('html_url') == WARNING), None)
        self.assertIsNotNone(actual, 'Historical warning changed/deleted or the issue-to-PR evidence seam is broken')
        self.assertIn("didn't pay me", actual['body'])

    def test_real_model_entry_path_cannot_bypass_missing_review(self):
        reason, _, proof = model_admission_refusal({'repo': REPO, 'issue': NUMBER}, lambda *a: self.context)
        self.assertEqual(reason, 'COMMERCIAL_REVIEW_REQUIRED')
        self.assertIsNone(proof)

    def test_citing_only_the_offer_cannot_acknowledge_the_real_warning(self):
        issue = self.context['issue']
        decision = {'decision': 'proceed', 'reason': 'Deliberately incomplete fault input, not a real admission',
                    'source_revision': review_revision(self.context), 'evidence': [
                        {'source_url': issue['html_url'], 'quote': issue['body']}]}
        self.assertEqual(review_refusal(self.context, decision)[0], 'COMMERCIAL_REVIEW_EVIDENCE_MISSING')

    def test_forged_source_revision_is_refused_against_live_bytes(self):
        self.assertEqual(review_refusal(self.context, {'source_revision': 'forged'})[0], 'COMMERCIAL_REVIEW_STALE')


if __name__ == '__main__':
    unittest.main(verbosity=2)
