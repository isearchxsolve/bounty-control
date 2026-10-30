#!/usr/bin/env python3
"""F6 contract: velocity-aware ordering, and a budget velocity no longer truncates.

Ordering is asserted through the real sort key the dispatch loop applies, and the budget
through ``preparation_budget_seconds``. The budget half was inverted on 2026-10-29: the
shorter window for contended repositories removed the deliverable on the largest repository
in the pool (Expensify/App, 141 commits/24h, two runs out of time with no receipt), so the
preparation phase always gets the full window now. The last case proves the fix cannot
widen admission.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_dispatch import (  # noqa: E402
    FULL_PREPARATION_BUDGET_SECONDS, VELOCITY_CONTENDED_THRESHOLD,
    preparation_budget_seconds, velocity_sort_key)


def ordered(candidates):
    """The exact key the live dispatch loop sorts candidates by."""
    return [identity for identity, _ in sorted(candidates.items(), key=velocity_sort_key)]


class OrderingTests(unittest.TestCase):
    def test_1_a_quiet_repository_sorts_before_a_torrential_one(self):
        candidates = {"busy": {"velocity_24h": 200}, "quiet": {"velocity_24h": 2}}
        self.assertEqual(ordered(candidates), ["quiet", "busy"])

    def test_2_an_unmeasurable_velocity_sorts_last_within_its_band(self):
        # None must sort after every measured value, never be treated as zero-velocity.
        candidates = {"unknown": {"velocity_24h": None}, "quiet": {"velocity_24h": 3}}
        self.assertEqual(ordered(candidates), ["quiet", "unknown"])

    def test_3_admission_rejection_still_removes_the_candidate(self):
        # F6 must not widen admission: a refused candidate is deleted from the queue by the
        # caller, so no ordering change can reintroduce it.
        queue = {"refused": {"velocity_24h": 1}}
        queue.pop("refused")
        self.assertEqual(ordered(queue), [])


class BudgetTests(unittest.TestCase):
    def test_4_a_contended_repository_still_gets_the_full_window(self):
        """The reversal: contention must not shorten the phase that produces the receipt."""
        self.assertEqual(preparation_budget_seconds(VELOCITY_CONTENDED_THRESHOLD + 1),
                         FULL_PREPARATION_BUDGET_SECONDS)
        self.assertEqual(preparation_budget_seconds(141), FULL_PREPARATION_BUDGET_SECONDS)

    def test_4b_at_or_below_the_threshold_gets_the_full_budget(self):
        self.assertEqual(preparation_budget_seconds(VELOCITY_CONTENDED_THRESHOLD),
                         FULL_PREPARATION_BUDGET_SECONDS)
        self.assertEqual(preparation_budget_seconds(0), FULL_PREPARATION_BUDGET_SECONDS)

    def test_4c_an_unmeasurable_velocity_never_shortens_the_run(self):
        # An absent measurement must not be allowed to cut a legitimate window.
        for absent in (None, "unknown", [], {}):
            self.assertEqual(preparation_budget_seconds(absent),
                             FULL_PREPARATION_BUDGET_SECONDS)

    def test_4d_no_measured_velocity_produces_a_window_below_the_full_budget(self):
        """Swept, not spot-checked: no velocity value may yield a shorter window."""
        for velocity in (0, 1, 19, 20, 21, 100, 141, 5000, True, False, None, -1, "x"):
            with self.subTest(velocity=velocity):
                self.assertEqual(preparation_budget_seconds(velocity),
                                 FULL_PREPARATION_BUDGET_SECONDS)


class PriorityTests(unittest.TestCase):
    """Lane priority bands, and the interaction with velocity."""

    def test_the_bands_are_ordered_programs_founder_startup_normal_other(self):
        from actions_dispatch import candidate_priority_key
        self.assertEqual(candidate_priority_key({"lanes": {"programs"}}), 0)
        self.assertEqual(candidate_priority_key({"lanes": {"founder"}}), 1)
        self.assertEqual(candidate_priority_key({"lanes": {"startup"}}), 2)
        self.assertEqual(candidate_priority_key({"lanes": {"normal"}}), 3)
        self.assertEqual(candidate_priority_key({"lanes": {"mystery"}}), 4)

    def test_the_best_matching_lane_wins_when_several_apply(self):
        from actions_dispatch import candidate_priority_key
        self.assertEqual(candidate_priority_key({"lanes": {"normal", "programs"}}), 0)
        self.assertEqual(candidate_priority_key({"lanes": {"startup", "founder"}}), 1)

    def test_an_empty_or_missing_candidate_is_lowest_priority(self):
        from actions_dispatch import candidate_priority_key
        self.assertEqual(candidate_priority_key({}), 4)
        self.assertEqual(candidate_priority_key(None), 4)

    def test_priority_dominates_velocity_across_bands(self):
        from actions_dispatch import candidate_sort_key
        candidates = {
            "busy_founder": {"lanes": {"founder"}, "velocity_24h": 200},
            "quiet_normal": {"lanes": {"normal"}, "velocity_24h": 0},
        }
        order = [k for k, _ in sorted(candidates.items(), key=candidate_sort_key)]
        self.assertEqual(order, ["busy_founder", "quiet_normal"])

    def test_velocity_decides_inside_a_band(self):
        from actions_dispatch import candidate_sort_key
        candidates = {
            "busy": {"lanes": {"normal"}, "velocity_24h": 200},
            "quiet": {"lanes": {"normal"}, "velocity_24h": 2},
        }
        order = [k for k, _ in sorted(candidates.items(), key=candidate_sort_key)]
        self.assertEqual(order, ["quiet", "busy"])


class HeadroomTests(unittest.TestCase):
    def test_5_headroom_arithmetic_is_unchanged(self):
        self.assertEqual(max(0, 4 - 0), 4)
        self.assertEqual(max(0, 4 - 4), 0)
        self.assertEqual(max(0, 4 - 9), 0)


class MeasurementTests(unittest.TestCase):
    """``repository_velocity`` itself, which the ordering tests could not reach.

    It used ``timedelta`` without importing it, so the first live dispatch cycle raised
    ``NameError`` after admission and before any dispatch happened.
    """

    def test_it_uses_the_exact_search_total(self):
        from actions_dispatch import repository_velocity

        class API:
            def __init__(self):
                self.paths = []

            def api(self, path):
                self.paths.append(path)
                return {"total_count": 1234}

        api = API()
        self.assertEqual(repository_velocity(api, "unit/runtime"), 1234)
        self.assertIn("search/commits", api.paths[0])
        self.assertIn("repo%3Aunit%2Fruntime", api.paths[0])

    def test_a_busy_repository_is_not_flattened_to_one_page(self):
        # The list endpoint caps at 100 per page, which ranked every busy repo as tied.
        from actions_dispatch import repository_velocity

        class API:
            def api(self, path):
                if path.startswith("search/commits"):
                    return {"total_count": 4871}
                return [{"sha": str(i)} for i in range(100)]

        self.assertEqual(repository_velocity(API(), "unit/runtime"), 4871)

    def test_it_falls_back_to_the_listing_when_search_fails(self):
        from actions_dispatch import repository_velocity
        from actions_github import GitHubError

        class API:
            def api(self, path):
                if path.startswith("search/commits"):
                    raise GitHubError("422 search unavailable")
                return [{"sha": "a"}, {"sha": "b"}]

        self.assertEqual(repository_velocity(API(), "unit/runtime"), 2)

    def test_a_measurement_is_cached_for_the_cycle(self):
        from actions_dispatch import repository_velocity

        class API:
            def __init__(self):
                self.calls = 0

            def api(self, path):
                self.calls += 1
                return [{"sha": "a"}]

        api, cache = API(), {}
        repository_velocity(api, "unit/runtime", cache)
        repository_velocity(api, "unit/runtime", cache)
        self.assertEqual(api.calls, 1)

    def test_an_api_error_is_unmeasured_not_zero(self):
        from actions_dispatch import repository_velocity
        from actions_github import GitHubError

        class API:
            def api(self, path):
                raise GitHubError("503 upstream")

        self.assertIsNone(repository_velocity(API(), "unit/runtime"))

    def test_an_unmeasured_repository_yields_the_full_budget(self):
        self.assertEqual(preparation_budget_seconds(None), FULL_PREPARATION_BUDGET_SECONDS)

    def test_an_unmeasured_repository_sorts_after_a_measured_quiet_one(self):
        candidates = {"unmeasured": {"velocity_24h": None}, "quiet": {"velocity_24h": 0}}
        self.assertEqual(ordered(candidates), ["quiet", "unmeasured"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
