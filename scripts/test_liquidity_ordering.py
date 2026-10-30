"""Pins liquidity into the dispatch ordering, and the founder lane's auth coverage.

``liquidity_score.py`` was written against the layer 3-4 targeting spec and then never
imported by anything: the dispatcher ranked by lane band and repository velocity only, so
a farm repository that shipped this morning outranked a funded founder whose production
was on fire. These tests are the regression guard for the wiring.

Two properties matter and both are asserted here:

* a solvent payer outranks an insolvent one *inside the same band*, and
* the lane band still dominates liquidity, so a busy founder issue is never displaced by
  a quiet normal-lane one.

The founder lane is also pinned: the targeting spec names authorization and access-control
defects as the highest-leverage class for this layer, and the lane could not see them.
"""
import json
import pathlib
import unittest

QUERIES = pathlib.Path(__file__).with_name("bounty_queries.json")


def candidate(lanes, **overrides):
    """A dispatch candidate shaped like the ones ``discover`` builds."""
    context = {
        "repo": overrides.pop("repo", "acme/checkout-api"),
        "title": overrides.pop("title", "Production checkout is down"),
        "body": overrides.pop("body", ""),
        "issue": {"assignee": overrides.pop("assignee", None),
                  "author_association": overrides.pop("author_assoc", "NONE")},
        "repository": {"owner": {"type": overrides.pop("owner_type", "Organization")},
                       "stargazers_count": overrides.pop("stars", 400),
                       "pushed_at": overrides.pop("pushed_at", "2026-10-30T00:00:00Z")},
    }
    row = {"lanes": set(lanes), "context": context}
    if "velocity_24h" in overrides:
        row["velocity_24h"] = overrides.pop("velocity_24h")
    if "merge_evidence" in overrides:
        row["merge_evidence"] = overrides.pop("merge_evidence")
    assert not overrides, overrides
    return row


class LiquidityViewTests(unittest.TestCase):
    def test_it_reads_only_what_the_pipeline_measured(self):
        from actions_dispatch import liquidity_view
        view = liquidity_view(candidate(["founder"]))
        self.assertEqual(view["owner_type"], "Organization")
        self.assertEqual(view["stars"], 400)
        self.assertIsInstance(view["repo_pushed_days"], int)
        # Nothing here has read a balance sheet or a SECURITY.md, so those stay absent
        # rather than being reported as a measured zero.
        for unmeasured in ("company_scale_usd", "security_contact", "merges_recent"):
            self.assertNotIn(unmeasured, view)

    def test_merge_evidence_reaches_the_payer_score(self):
        from actions_dispatch import liquidity_view
        view = liquidity_view(candidate(
            ["founder"], merge_evidence={"merged": 0, "total": 4458}))
        self.assertEqual(view["merges_ever"], 0)
        self.assertEqual(view["prs_total"], 4458)

    def test_an_unmeasured_merge_probe_is_not_a_zero(self):
        from actions_dispatch import liquidity_view
        view = liquidity_view(candidate(["founder"], merge_evidence={"unavailable": "throttled"}))
        self.assertNotIn("merges_ever", view)

    def test_a_missing_context_does_not_raise(self):
        from actions_dispatch import liquidity_view
        self.assertEqual(liquidity_view({})["repo"], None)


class OrderingTests(unittest.TestCase):
    def test_a_solvent_payer_outranks_an_insolvent_one_in_the_same_band(self):
        from actions_dispatch import candidate_sort_key
        candidates = {
            "funded_founder": candidate(
                ["founder"], repo="acme/checkout-api", owner_type="Organization",
                author_assoc="OWNER", stars=400, velocity_24h=50),
            "farm": candidate(
                ["founder"], repo="awesome-agent-bounties", owner_type="User",
                author_assoc="NONE", stars=3, velocity_24h=0,
                merge_evidence={"merged": 0, "total": 4458}),
        }
        order = [k for k, _ in sorted(candidates.items(), key=candidate_sort_key)]
        self.assertEqual(order, ["funded_founder", "farm"])

    def test_the_lane_band_still_dominates_liquidity(self):
        from actions_dispatch import candidate_sort_key
        candidates = {
            "busy_founder": candidate(
                ["founder"], owner_type="User", author_assoc="NONE", stars=3,
                velocity_24h=200),
            "quiet_normal": candidate(
                ["normal"], owner_type="Organization", author_assoc="OWNER",
                stars=400, velocity_24h=0),
        }
        order = [k for k, _ in sorted(candidates.items(), key=candidate_sort_key)]
        self.assertEqual(order, ["busy_founder", "quiet_normal"])

    def test_velocity_still_breaks_a_liquidity_tie(self):
        from actions_dispatch import candidate_sort_key
        candidates = {
            "busy": candidate(["normal"], velocity_24h=200),
            "quiet": candidate(["normal"], velocity_24h=2),
        }
        order = [k for k, _ in sorted(candidates.items(), key=candidate_sort_key)]
        self.assertEqual(order, ["quiet", "busy"])

    def test_an_unsorted_candidate_keeps_its_old_position(self):
        """No context means no liquidity signal, so ordering must be unchanged."""
        from actions_dispatch import candidate_sort_key
        self.assertEqual(candidate_sort_key(("x", {})),
                         candidate_sort_key(("y", {})))


class FounderLaneCoverageTests(unittest.TestCase):
    """The targeting spec's highest-leverage class must be reachable from this lane."""

    def setUp(self):
        self.lanes = json.loads(QUERIES.read_text(encoding="utf-8"))

    def test_the_founder_lane_searches_authorization_defects(self):
        joined = " ".join(self.lanes["founder"]).lower()
        for term in ("auth", "permission", "unauthorized", "access control", "idor"):
            with self.subTest(term=term):
                self.assertIn(term, joined)

    def test_every_new_query_is_a_github_search_expression(self):
        for query in self.lanes["founder"]:
            with self.subTest(query=query[:50]):
                self.assertIn("is:issue", query)
                self.assertIn("is:open", query)

    def test_no_lane_lost_its_queries(self):
        for lane in ("priority_discovery", "normal", "startup", "founder", "programs"):
            with self.subTest(lane=lane):
                self.assertTrue(self.lanes.get(lane), lane)


if __name__ == "__main__":
    unittest.main()
