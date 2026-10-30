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
        for _ in range(4):
            sp.record_yield(ledger, "startup", STATIC[1], returned=5, saturated=False,
                            dispatch_ready=2, refused=0)
        chosen, audit = sp.plan("startup", STATIC, ledger, slots=3, purpose="p",
                                refusal_reasons=[], api_key="", rng=random.Random(2))
        self.assertEqual(chosen[0], STATIC[1])
        self.assertIn(STATIC[1], audit["exploit"])

    def test_exploration_is_never_zero_when_untried_exists(self):
        ledger = {}
        sp.record_yield(ledger, "startup", STATIC[0], returned=3, saturated=False,
                        dispatch_ready=1, refused=0)
        _, audit = sp.plan("startup", STATIC, ledger, slots=3, purpose="p",
                           refusal_reasons=[], api_key="", rng=random.Random(3))
        self.assertTrue(audit["explore"], "the planner must try something new")

    def test_refused_yield_lowers_an_expressions_score(self):
        clean = {"runs": 4, "dispatch_ready": 2, "refused": 0}
        bad = {"runs": 4, "dispatch_ready": 2, "refused": 4}
        self.assertGreater(sp.score(clean), sp.score(bad))

    def test_a_single_lucky_run_does_not_outrank_a_long_record(self):
        lucky = {"runs": 1, "dispatch_ready": 1, "refused": 0}
        proven = {"runs": 20, "dispatch_ready": 8, "refused": 0}
        self.assertGreater(sp.score(proven), sp.score(lucky))


class LedgerRoundTrip(unittest.TestCase):
    def test_recording_accumulates_and_persists(self):
        import tempfile
        from pathlib import Path
        ledger = {}
        sp.record_yield(ledger, "normal", 'label:bounty is:issue', returned=4, saturated=True,
                        dispatch_ready=1, refused=2)
        sp.record_yield(ledger, "normal", 'label:bounty is:issue', returned=1, saturated=False,
                        dispatch_ready=0, refused=0)
        entry = ledger["normal|label:bounty is:issue"]
        self.assertEqual((entry["runs"], entry["returned"], entry["refused"]), (2, 5, 2))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.json"
            sp.save_ledger(path, ledger)
            self.assertEqual(sp.load_ledger(path), ledger)


if __name__ == "__main__":
    unittest.main()
