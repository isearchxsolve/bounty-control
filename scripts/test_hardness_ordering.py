"""Pins Baba's Hardness Moat into the dispatch ordering, and founders above programmes.

``hardness_score``-style scoring was first written inside ``autonomous_icu_pipeline.py``
and then imported by nothing in the CI chain, so the moat never influenced a dispatch -
the same defect ``liquidity_score.py`` had before it was wired (see
``test_liquidity_ordering.py``). These tests fail if that ever happens again, and they
also pin the band order, which was measured wrong: the paid-programs lane ranked first
while its flagship target (``Expensify/App``, 3,384,503 KB) is refused by the capacity
gate, so the queue filled with candidates the pipeline then discarded.

Two properties matter:

* the lane band still dominates everything, so a founder issue is never displaced by a
  normal-lane one;
* within a band, solvency decides before hardness, and hardness decides before
  repository quietness - a quiet repository is only a proxy for competition, while the
  ticket's own vocabulary is evidence of it.
"""
import ast
import pathlib
import unittest

import actions_dispatch
import hardness_score

HERE = pathlib.Path(__file__).parent


def candidate(lanes, **overrides):
    """A dispatch candidate shaped like the ones ``discover`` builds."""
    context = {
        "repo": overrides.pop("repo", "acme/checkout-api"),
        "title": overrides.pop("title", "Production checkout is down"),
        "body": overrides.pop("body", ""),
        "issue": {"assignee": overrides.pop("assignee", None),
                  "author_association": overrides.pop("author_assoc", "NONE"),
                  "comments": overrides.pop("comments", 0),
                  "labels": overrides.pop("labels", [])},
        "repository": {"owner": {"type": overrides.pop("owner_type", "Organization")},
                       "stargazers_count": overrides.pop("stars", 400),
                       "pushed_at": overrides.pop("pushed_at", "2026-10-30T00:00:00Z")},
    }
    row = {"lanes": set(lanes), "context": context}
    if "velocity_24h" in overrides:
        row["velocity_24h"] = overrides.pop("velocity_24h")
    if "merge_evidence" in overrides:
        row["merge_evidence"] = overrides.pop("merge_evidence")
    return row


def ordered(*items):
    """Apply the real sort key, so the test exercises production ordering."""
    pairs = [(index, item) for index, item in enumerate(items)]
    pairs.sort(key=actions_dispatch.candidate_sort_key)
    return [item for _, item in pairs]


class BandOrderTest(unittest.TestCase):
    def test_founder_outranks_programs(self):
        founder = candidate({"founder"})
        programs = candidate({"programs"})
        self.assertEqual(ordered(founder, programs), [founder, programs])

    def test_band_order_is_explicit(self):
        for lane, expected in (("founder", 0), ("programs", 1), ("startup", 2), ("normal", 3)):
            self.assertEqual(actions_dispatch.candidate_priority_key({"lanes": {lane}}), expected,
                             f"{lane} band changed")

    def test_unknown_lane_sorts_last(self):
        self.assertEqual(actions_dispatch.candidate_priority_key({"lanes": {"weird"}}), 4)

    def test_band_dominates_hardness(self):
        """A trivial founder issue must still beat a terrifying normal-lane one."""
        founder = candidate({"founder"}, title="Typo in the docs")
        normal = candidate({"normal"}, title="Deadlock and race condition in kqueue io_uring path")
        self.assertEqual(ordered(normal, founder), [founder, normal])


class HardnessOrderTest(unittest.TestCase):
    def test_hard_ticket_beats_trivial_one_in_same_band(self):
        hard = candidate({"startup"}, title="Deadlock under load in io_uring write path", comments=1)
        trivial = candidate({"startup"}, title="Typo in the docs", comments=0)
        self.assertEqual(ordered(trivial, hard), [hard, trivial])

    def test_hardness_breaks_velocity_tie(self):
        """A hard ticket in a busy repository still beats a trivial one in a quiet repository."""
        hard_busy = candidate({"startup"}, title="Race condition in the parser", velocity_24h=40)
        trivial_quiet = candidate({"startup"}, title="Update the README", velocity_24h=0)
        self.assertEqual(ordered(trivial_quiet, hard_busy), [hard_busy, trivial_quiet])

    def test_solvency_still_beats_hardness(self):
        """A hard ticket from a payer with no money must not outrank a funded trivial one.

        Measured via the liquidity dimension the ordering already had: an org repository
        that shipped this week and merges pull requests is liquid; a personal repository
        with no merges is not.
        """
        liquid = candidate({"startup"}, title="Typo in the docs", owner_type="Organization",
                           merge_evidence={"merged": 12, "total": 14})
        insolvent = candidate({"startup"}, title="Deadlock and use-after-free in the kernel driver",
                              owner_type="User", merge_evidence={"merged": 0, "total": 9})
        self.assertEqual(ordered(insolvent, liquid), [liquid, insolvent])

    def test_hardness_view_reads_measured_fields_only(self):
        row = candidate({"startup"}, title="Deadlock", comments=3,
                        labels=[{"name": "concurrency"}])
        view = actions_dispatch.hardness_view(row)
        self.assertEqual(view["comments_count"], 3)
        self.assertEqual(view["title"], "Deadlock")
        hits = hardness_score.hardness_hits(view)
        self.assertEqual(len(hits), 2, "labels and title both feed the moat")
        self.assertTrue(any("deadlock" in h for h in hits))
        self.assertTrue(any("concurrency" in h for h in hits))


class WiringTest(unittest.TestCase):
    def test_dispatcher_actually_imports_the_moat(self):
        """The never-imported defect, pinned as a source-level assertion."""
        tree = ast.parse((HERE / "actions_dispatch.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
        self.assertIn("hardness_score", imported,
                      "hardness_score must be imported by the dispatcher, not merely present")

    def test_sort_key_contains_hardness(self):
        source = (HERE / "actions_dispatch.py").read_text(encoding="utf-8")
        body = source.split("def candidate_sort_key", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("hardness_score(", body)
        self.assertLess(body.index("liquidity_rank_key"), body.index("hardness_score"),
                        "solvency must be decided before hardness")
        self.assertLess(body.index("hardness_score"), body.index("velocity_sort_key"),
                        "hardness must be decided before repository quietness")

    def test_moat_keeps_its_weights(self):
        """A quiet, well-paid, terrifying ticket must score above a crowded trivial one."""
        hard = {"title": "Reentrancy in the smart contract bridge",
                "body": "bounty $750", "comments_count": 0}
        trivial = {"title": "Typo", "body": "", "comments_count": 40}
        self.assertGreater(hardness_score.hardness_score(hard)[0],
                           hardness_score.hardness_score(trivial)[0])

    def test_self_test_passes(self):
        self.assertEqual(hardness_score.self_test(), 0)


if __name__ == "__main__":
    unittest.main()
