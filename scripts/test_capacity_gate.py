"""Capacity gate: do not claim a task this runner cannot prepare.

Measured 2026-10-29. Expensify/App is 3,380,974 KB on disk, and its own ``npm run lint``
reached ~14 GB RSS on a runner with ~7 GiB of RAM plus 8 GiB of swap. Two deliveries
(40862366271 and 40862319897) were killed at exit 143 with no preparation report, then filed
as a missing receipt. The preparation window was never the problem: the machine was.

So selection has to carry capacity, and a refusal has to be visible. This suite pins both
halves, plus the prompt clause that stops the agent from launching the 14 GB command in the
first place.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_dispatch  # noqa: E402
from actions_dispatch import (  # noqa: E402
    CAPACITY_MAX_REPOSITORY_KB, repository_over_capacity, repository_size_kb)


class FakeAPI:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def api(self, path, method="GET", body=None):
        self.calls.append(path)
        if self.error:
            raise self.error
        return self.payload


class CapacityDecisionTests(unittest.TestCase):
    def test_a_repository_above_the_limit_is_excluded(self):
        self.assertTrue(repository_over_capacity(CAPACITY_MAX_REPOSITORY_KB + 1))

    def test_a_repository_at_the_limit_is_allowed(self):
        # The limit is a ceiling that is inclusive: only strictly larger is refused.
        self.assertFalse(repository_over_capacity(CAPACITY_MAX_REPOSITORY_KB))

    def test_a_small_repository_is_allowed(self):
        self.assertFalse(repository_over_capacity(12_000))

    def test_an_unmeasured_size_is_never_excluded(self):
        # Unknown is not too large: a failed probe must not silently drop a valid target.
        for unknown in (None, "unknown", [], {}, True, False):
            with self.subTest(value=unknown):
                self.assertFalse(repository_over_capacity(unknown))

    def test_the_expensify_measurement_is_excluded_at_the_shipped_default(self):
        # The literal measured size, so the gate cannot regress into allowing it.
        self.assertTrue(repository_over_capacity(3_380_974))

    def test_an_explicit_limit_overrides_the_default(self):
        self.assertTrue(repository_over_capacity(5_000, limit_kb=4_000))
        self.assertFalse(repository_over_capacity(5_000, limit_kb=6_000))


class SizeProbeTests(unittest.TestCase):
    def test_the_size_is_read_from_repository_metadata(self):
        api = FakeAPI({"size": 1234, "full_name": "o/r"})
        self.assertEqual(repository_size_kb(api, "o/r"), 1234)
        self.assertEqual(api.calls, ["repos/o/r"])

    def test_the_probe_is_cached_per_cycle(self):
        api = FakeAPI({"size": 99})
        cache = {}
        self.assertEqual(repository_size_kb(api, "o/r", cache), 99)
        self.assertEqual(repository_size_kb(api, "o/r", cache), 99)
        self.assertEqual(len(api.calls), 1, "one probe per repository per cycle")

    def test_a_failed_probe_is_unknown_not_zero(self):
        api = FakeAPI(error=ValueError("boom"))
        self.assertIsNone(repository_size_kb(api, "o/r"))

    def test_a_malformed_payload_is_unknown(self):
        for payload in ({"size": "big"}, {"size": None}, [], "nope", {"size": True}):
            with self.subTest(payload=payload):
                self.assertIsNone(repository_size_kb(FakeAPI(payload), "o/r"))


class GateWiringTests(unittest.TestCase):
    """The gate has to run on the dispatch path, and the refusal has to be countable."""

    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "actions_dispatch.py").read_text(encoding="utf-8-sig")

    def test_the_gate_runs_before_any_task_is_claimed(self):
        headroom = self.source.index("headroom = max(0, 4 - active)")
        gate = self.source.index('if repository_over_capacity(candidate.get("size_kb")):')
        claim = self.source.index("state, _ = store.read(identity)")
        self.assertGreater(gate, headroom, "the gate must run inside the dispatch loop")
        self.assertLess(gate, claim, "capacity is decided before ownership is taken")

    def test_a_capacity_refusal_is_counted_and_named(self):
        self.assertIn('counts["CAPACITY_EXCLUDED"] += 1', self.source)
        self.assertIn('"phase": "CAPACITY_EXCLUDED"', self.source)

    def test_the_summary_carries_the_exclusion_evidence(self):
        self.assertIn('"capacity_excluded_repositories": capacity_excluded', self.source)
        self.assertIn('"candidate_size_kb"', self.source)


class PreparationPromptTests(unittest.TestCase):
    """The instruction that reaches the agent must forbid the command that killed the runs."""

    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "kaggle_engine_worker.py").read_text(encoding="utf-8-sig")

    def test_the_prompt_forbids_repository_wide_verification_in_preparation(self):
        self.assertIn("HOW THE MEASURING WORKS", self.source)
        self.assertIn("you verify with ONE targeted command", self.source)
        self.assertIn(
            "Repo-wide or workspace-wide lint, typecheck, build or test consumes more than this runner has",
            self.source)

    def test_the_old_loophole_is_gone(self):
        # This sentence permitted exactly the failure: "listing its native component checks as
        # separate serial commands in the plan" invited running them during preparation.
        self.assertNotIn("listing its native component checks as separate serial commands in the plan",
                         self.source)

    def test_the_baseline_rule_is_taught_not_decreed(self):
        """Measured 2026-11-01: six retries died writing regression tests into the customer's tree
        during preparation, because the directive asked for a reproduction command without ever
        saying the test behind it is authored in the engineering turn. The constraint has to arrive
        as knowledge of the world -- why the base is a yardstick, where scratch lives, what the two
        turns each are -- not as a prohibition, or the agent solves the measured problem a different
        way and breaks the same gate.
        """
        self.assertIn("HOW THIS DELIVERY IS SHAPED", self.source)
        self.assertIn("surveyor", self.source)
        self.assertIn("yardstick", self.source)
        # The missing fact: the reproduction test is authored in the engineering turn, so naming a
        # test that does not exist yet is correct and expected.
        self.assertIn("the test is authored in the engineering turn", self.source)
        self.assertIn("The command may name a test that does not exist yet", self.source)
        # Where scratch work lives, so an experiment never lands in the repository tree.
        self.assertIn("never the repository tree", self.source)
        self.assertIn("the packet directory", self.source)
        # The old handcuff phrasing is gone from the directive.
        self.assertNotIn("without changing product source in this phase", self.source)

    def test_the_prompt_names_the_measured_consequence(self):
        self.assertIn("7 GiB", self.source)
        self.assertIn("14 GiB", self.source)
        self.assertIn("exit 143", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
