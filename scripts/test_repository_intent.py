"""Merge history as the evidence that a repository pays at all.

A bounty is paid on merge. So a repository that carries many pull requests and has
merged none cannot be a payer, however confidently its issues advertise an amount.
Measured 2026-10-27 with ``gh api search/issues`` (read-only, no dispatch):

    repo                               merged   total PRs
    UnsafeLabs/Bounty-Hunters               0        4458
    ClankerNation/OpenAgents                0        1624
    UnsafeLabs/RFC-5322                     0          26
    oll4com/spaceapp                       18         322
    outerbase/starbasedb                   58         298
    fastapi/fastapi                      3716        6500

The first three are farms: one of them took 4,458 pull requests, merged none, and
declared in its own CONTRIBUTING.md that its bounties are symbolic and will not be
merged. The four real projects all merge. These fixtures pin that separation and
pin the boundary that protects new projects: silence is never rejection.
"""
import unittest

from bounty_admission import MERGE_EVIDENCE_MIN, repository_intent


class RepositoryIntentTests(unittest.TestCase):

    def assertRejected(self, evidence):
        ok, reason = repository_intent(evidence)
        self.assertFalse(ok, "expected rejection for %r" % (evidence,))
        self.assertEqual(reason, "REPOSITORY_DOES_NOT_MERGE")
        return reason

    def assertAllowed(self, evidence):
        ok, reason = repository_intent(evidence)
        self.assertTrue(ok, "unexpected rejection for %r: %s" % (evidence, reason))
        self.assertEqual(reason, "")

    def test_farm_with_thousands_of_unmerged_pulls_is_rejected(self):
        """4,458 pull requests accepted, zero merged -- measured farm shape."""
        self.assertRejected({"merged": 0, "total": 4458})

    def test_second_measured_farm_is_rejected(self):
        self.assertRejected({"merged": 0, "total": 1624})

    def test_small_farm_above_evidence_floor_is_rejected(self):
        """26 pulls, 0 merged: above the floor, so the zero is meaningful."""
        self.assertRejected({"merged": 0, "total": 26})

    def test_measured_payer_is_allowed(self):
        """oll4com/spaceapp: 18 merged of 322, a real payer."""
        self.assertAllowed({"merged": 18, "total": 322})

    def test_healthy_project_is_allowed(self):
        self.assertAllowed({"merged": 58, "total": 298})
        self.assertAllowed({"merged": 3716, "total": 6500})

    def test_single_merge_is_enough(self):
        """One merge proves the repository does merge outside work."""
        self.assertAllowed({"merged": 1, "total": 900})

    def test_new_repository_without_merge_history_is_not_rejected(self):
        """A project that has not merged yet must not be refused on silence."""
        self.assertAllowed({"merged": 0, "total": 0})
        self.assertAllowed({"merged": 0, "total": 3})

    def test_evidence_floor_boundary(self):
        self.assertRejected({"merged": 0, "total": MERGE_EVIDENCE_MIN})
        self.assertAllowed({"merged": 0, "total": MERGE_EVIDENCE_MIN - 1})

    def test_unreachable_probe_never_rejects(self):
        """A throttled or failed search is not evidence against the repository."""
        self.assertAllowed({"unavailable": "search rate limit exceeded"})
        self.assertAllowed({})
        self.assertAllowed(None)

    def test_missing_half_of_the_evidence_never_rejects(self):
        self.assertAllowed({"merged": 0})
        self.assertAllowed({"total": 4458})

    def test_text_counts_are_coerced_not_crashed(self):
        """Search counts arrive as JSON numbers but must not explode on strings."""
        self.assertRejected({"merged": "0", "total": "4458"})
        self.assertAllowed({"merged": "18", "total": "322"})


if __name__ == "__main__":
    unittest.main()
