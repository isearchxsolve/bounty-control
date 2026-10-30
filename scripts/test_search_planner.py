"""The planner must be safe with no key, safe with hallucinated proposals, and must explore.

Network is never touched here: propose() is exercised through its no-key and parse paths, and
the live Nemotron call is verified separately against the real endpoint.
"""

import random
import unittest

import search_planner as sp


STATIC = ['"bounty" is:issue is:open', 'label:bounty is:issue is:open', 'algora bounty is:issue is:open']


class ExpressionValidation(unittest.TestCase):
    def test_a_normal_issue_search_is_valid(self):
        self.assertEqual(sp.validate_expression('label:bounty is:issue is:open')[0], True)

    def test_an_unknown_qualifier_is_refused(self):
        ok, reason = sp.validate_expression('bountyamount:500 is:issue is:open')
        self.assertFalse(ok)
        self.assertIn("unknown_qualifier", reason)

    def test_a_pull_request_only_search_is_not_a_discovery_search(self):
        ok, reason = sp.validate_expression('label:bounty')
        self.assertFalse(ok)
        self.assertEqual(reason, "no_issue_type_gate")

    def test_empty_oversized_and_non_ascii_are_refused(self):
        self.assertFalse(sp.validate_expression("   ")[0])
        self.assertFalse(sp.validate_expression("is:issue " * 40)[0])
        self.assertFalse(sp.validate_expression("is:issue \u00e9clair")[0])

    def test_unbalanced_quotes_are_refused(self):
        self.assertFalse(sp.validate_expression('"bounty is:issue')[0])


class ProposalParsing(unittest.TestCase):
    def test_hallucinated_entries_are_dropped_and_duplicates_collapse(self):
        reply = 'Here you go: ["label:bounty is:issue is:open", "bogus:x is:issue", ' \
                '"label:bounty is:issue is:open", 42, ""]'
        self.assertEqual(sp._parse_array(reply), ["label:bounty is:issue is:open"])

    def test_a_reply_without_an_array_yields_nothing(self):
        self.assertEqual(sp._parse_array("no json here"), [])

    def test_a_malformed_array_yields_nothing_rather_than_raising(self):
        self.assertEqual(sp._parse_array("[unclosed"), [])


class FailClosed(unittest.TestCase):
    def test_no_key_returns_no_proposals_without_calling_out(self):
        proposals, path = sp.propose("startup", "purpose", [], [], api_key="")
        self.assertEqual(proposals, [])
        self.assertEqual(path, "no_key")

    def test_planning_with_no_key_still_returns_the_full_slot_count(self):
        chosen, audit = sp.plan("startup", STATIC, {}, slots=2, purpose="p",
                                refusal_reasons=[], api_key="", rng=random.Random(1))
        self.assertEqual(len(chosen), 2)
        self.assertEqual(audit["proposer"], "no_key")
        self.assertTrue(set(chosen) <= set(STATIC))


class Selection(unittest.TestCase):
    def test_a_proven_expression_is_exploited_first(self):
        ledger = {}
        sp.set_outcomes(ledger, "startup", STATIC[1], tasks=20, dispatched=8, refused=0)
        chosen, audit = sp.plan("startup", STATIC, ledger, slots=3, purpose="p",
                                refusal_reasons=[], api_key="", rng=random.Random(2))
        self.assertEqual(chosen[0], STATIC[1])
        self.assertIn(STATIC[1], audit["exploit"])

    def test_an_expression_that_only_returned_issues_is_not_exploited(self):
        """Volume is not outcome: 200 issues found, zero dispatched, must not count as proven."""
        ledger = {}
        sp.record_yield(ledger, "startup", STATIC[0], returned=200, saturated=True)
        sp.set_outcomes(ledger, "startup", STATIC[0], tasks=200, dispatched=0, refused=0)
        _, audit = sp.plan("startup", STATIC, ledger, slots=2, purpose="p",
                           refusal_reasons=[], api_key="", rng=random.Random(4))
        self.assertNotIn(STATIC[0], audit["exploit"])

    def test_exploration_is_never_zero_when_untried_exists(self):
        ledger = {}
        sp.set_outcomes(ledger, "startup", STATIC[0], tasks=3, dispatched=1, refused=0)
        _, audit = sp.plan("startup", STATIC, ledger, slots=3, purpose="p",
                           refusal_reasons=[], api_key="", rng=random.Random(3))
        self.assertTrue(audit["explore"], "the planner must try something new")

    def test_refused_outcomes_lower_an_expressions_score(self):
        clean = {"tasks": 10, "dispatched": 4, "refused": 0}
        bad = {"tasks": 10, "dispatched": 4, "refused": 6}
        self.assertGreater(sp.score(clean), sp.score(bad))

    def test_a_single_lucky_dispatch_does_not_outrank_a_long_record(self):
        """Measured with the shipped prior: a proven 8-of-30 must beat a lucky 1-of-1."""
        lucky = {"tasks": 1, "dispatched": 1, "refused": 0}
        proven = {"tasks": 30, "dispatched": 8, "refused": 0}
        self.assertGreater(sp.score(proven), sp.score(lucky))

    def test_a_stronger_record_beats_a_weaker_one(self):
        self.assertGreater(sp.score({"tasks": 30, "dispatched": 12, "refused": 0}),
                           sp.score({"tasks": 30, "dispatched": 8, "refused": 0}))

    def test_zero_yield_scores_below_an_untried_expression(self):
        """A long record of nothing must rank below a fresh expression, or exploration starves."""
        self.assertLess(sp.score({"tasks": 50, "dispatched": 0, "refused": 0}), sp.score({}))


class LedgerRoundTrip(unittest.TestCase):
    def test_outcomes_are_set_not_incremented(self):
        """Recomputing the same history must not double-credit an expression."""
        ledger = {}
        sp.set_outcomes(ledger, "normal", "label:bounty is:issue", tasks=5, dispatched=2, refused=1)
        sp.set_outcomes(ledger, "normal", "label:bounty is:issue", tasks=5, dispatched=2, refused=1)
        entry = ledger["normal|label:bounty is:issue"]
        self.assertEqual((entry["tasks"], entry["dispatched"], entry["refused"]), (5, 2, 1))

    def test_volume_recording_accumulates_and_persists(self):
        import tempfile
        from pathlib import Path
        ledger = {}
        sp.record_yield(ledger, "normal", "label:bounty is:issue", returned=4, saturated=True)
        sp.record_yield(ledger, "normal", "label:bounty is:issue", returned=1, saturated=False)
        entry = ledger["normal|label:bounty is:issue"]
        self.assertEqual((entry["runs"], entry["returned"], entry["saturated_runs"]), (2, 5, 1))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.json"
            sp.save_ledger(path, ledger)
            self.assertEqual(sp.load_ledger(path), ledger)


if __name__ == "__main__":
    unittest.main()
