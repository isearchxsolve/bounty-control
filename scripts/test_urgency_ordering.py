"""Urgency decides who answers; solvency decides who pays.

Baba's note, 2026-10-30: the claimant waited since April for a maintainer reply on a funded
microG ticket because the target issuer had no urgency - no user-visible production bleeding
money. That makes reply latency the binding constraint, and the payer's own words the only
honest source for it.

These tests hold the ordering in place and keep the scorer honest: a calm payer cannot win,
a year-old dramatic complaint cannot stay at full value, and urgency must be scored from
measured fields before the dispatcher is allowed to consult solvency or difficulty.
"""

import ast
import pathlib
import unittest

import actions_dispatch
import urgency_score
from urgency_score import urgency_score as score

HERE = pathlib.Path(__file__).parent
NL = chr(10)


def candidate(title, body="", band="founder", age_days=None, created=None, labels=()):
    issue = {"title": title, "body": body, "labels": list(labels)}
    if created:
        issue["created_at"] = created
    return ({"context": {"issue": issue}, "repository": {"size": 1000},
             "lanes": [band]}, band)


class OrderingTest(unittest.TestCase):
    def _order(self, pairs):
        items = {}
        for index, (context, band) in enumerate(pairs):
            items["item-" + str(index)] = {"context": context["context"],
                                            "lanes": [band]}
        return [key for key, _ in sorted(items.items(),
                                         key=lambda item: actions_dispatch.candidate_sort_key(
                                             (item[0], item[1])))]

    def test_a_bleeding_payer_outranks_a_calm_rich_one_in_the_same_band(self):
        hot = candidate("Production is down, we are losing revenue every minute")
        calm = candidate("Add dark mode", "No rush, whenever you can")
        order = self._order([calm, hot])
        self.assertEqual(order[0], "item-1", "the bleeding payer must be attempted first")

    def test_the_conjunction_is_decided_before_solvency(self):
        source = (HERE / "actions_dispatch.py").read_text(encoding="utf-8")
        body = source.split("def candidate_sort_key", 1)[1].split(NL + "def ", 1)[0]
        self.assertIn("two_edged_score(", body)
        self.assertLess(body.index("two_edged_score("), body.index("liquidity_rank_key"),
                        "an unanswering or unwinnable ticket must not outrank a live one")
        self.assertLess(body.index("liquidity_rank_key"), body.index("hardness_score("))
        helper = source.split("def two_edged_score", 1)[1].split(NL + "def ", 1)[0]
        self.assertIn("hardness_score(", helper)
        self.assertIn("urgency_score(", helper)


    def test_the_dispatcher_imports_the_scorer(self):
        tree = ast.parse((HERE / "actions_dispatch.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {alias.name for alias in node.names}
        self.assertIn("urgency_score", imported)

    def test_the_band_still_dominates_urgency(self):
        hot_normal = candidate("Production is down, losing revenue", band="normal")
        calm_founder = candidate("Add dark mode", "No rush", band="founder")
        self.assertLess(actions_dispatch.candidate_priority_key(calm_founder[0]),
                        actions_dispatch.candidate_priority_key(hot_normal[0]),
                        "founder sorts before normal: lower is earlier")
        order = self._order([hot_normal, calm_founder])
        self.assertEqual(order[0], "item-1",
                         "a cold founder ticket still outranks a burning normal one")


    def test_a_calm_payer_is_never_urgent(self):
        self.assertLess(score({"title": "Add dark mode",
                               "body": "No rush at all, nice to have, take your time"})[0], 0)

    def test_dramatic_language_does_not_keep_its_value_forever(self):
        text = {"title": "Production is down, we are losing revenue"}
        fresh = score(dict(text, age_days=1))[0]
        stale = score(dict(text, age_days=900))[0]
        self.assertLess(stale, fresh)
        self.assertGreater(stale, 0, "discount must not invert a genuinely urgent ticket")

    def test_unknown_age_is_not_treated_as_stale(self):
        text = {"title": "Production is down, we are losing revenue"}
        self.assertEqual(score(dict(text))[0],
                         score(dict(text, age_days=0))[0])

    def test_a_volunteer_wish_scores_low(self):
        self.assertLess(score({"title": "Support Google Cast",
                               "body": "Is this planned? The wiki is stale."})[0], 20)

    def test_labels_and_body_are_both_read(self):
        self.assertGreaterEqual(score({"title": "Ticket", "body": "",
                                       "labels": ["urgent"]})[0], 20)

    def test_self_test_passes(self):
        self.assertEqual(urgency_score.self_test(), 0)

    def test_the_scorer_never_claims_to_prove_funding(self):
        source = (HERE / "urgency_score.py").read_text(encoding="utf-8")
        self.assertIn("a targeting signal, never a funding signal", source)


if __name__ == "__main__":
    unittest.main()


class TwoEdgedSwordTest(unittest.TestCase):
    """Baba, 2026-10-30: "its a two edged sword the issue is fundamentally hard and live in
    production burning millions each second from silo cofounders and startups pocket".

    Either edge alone is a losing ticket, and the tests below are the two failures that cost
    this month: a funded volunteer ticket nobody answered for six months, and trivial tickets
    that bystanders solve within hours.
    """

    def _score(self, title, body="", band="founder", created=None):
        item = ("id", {"context": {"issue": {"title": title, "body": body, "labels": [],
                                             **({"created_at": created} if created else {})}},
                       "lanes": [band]})
        return actions_dispatch.two_edged_score(item)

    def test_both_edges_beat_either_edge_alone(self):
        both = self._score("Deadlock in production, we are losing revenue every minute",
                           "Consensus raft reentrancy race condition, checkout is broken, urgent")
        hot_trivial = self._score("Typo in footer", "Production is down, losing revenue, urgent")
        hard_dead = self._score("Support Google Cast", "Deadlock and raft consensus work. Is this planned?")
        self.assertGreater(both, hot_trivial)
        self.assertGreater(both, hard_dead)

    def test_a_burning_trivial_ticket_beats_a_dead_hard_one(self):
        """Both are failures, but the hot one might still answer us."""
        hot_trivial = self._score("Typo in footer", "Production is down, losing revenue, urgent")
        hard_dead = self._score("Support Google Cast", "Deadlock and raft consensus. Is this planned?")
        self.assertGreater(hot_trivial, hard_dead)

    def test_a_missing_edge_cannot_be_compensated(self):
        hard_only = self._score("Deadlock race condition use-after-free in consensus",
                                "No rush at all, nice to have")
        self.assertLess(hard_only, 10, "difficulty must not carry a cold ticket")

    def test_the_cap_prevents_a_runaway_signal(self):
        loud = self._score("Production is down, losing revenue, data breach, urgent, sla, p0",
                           "outage exploited in the wild immediately")
        self.assertLessEqual(loud, actions_dispatch.EDGE_CAP * (1 + actions_dispatch.URGENCY_BONUS) + 1)
