"""Hydration must not spend its batch on a repository the runner cannot prepare.

Measured on run 40898443331 (2026-10-29), the cycle that closed the delivery proof:

    checked rows: 60, distinct repositories: 37
    Expensify/App: 8 slots against a declared HYDRATION_PER_REPO of 4
    qualified_fresh: 6, qualified_unique: 6, dispatched: []
    capacity_excluded_repositories: ["Expensify/App"]

Every qualified candidate was the same 3,384,503 KB repository, against a 750,000 KB
ceiling. Eight hydrations, eight comment fetches and six full admission passes were
spent on a task the dispatch gate would refuse anyway, and the cycle dispatched nothing.

Two contracts are pinned here:

  * the per-repository cap binds fresh priority hits as well as backlog rows, so a
    repository with a dedicated priority query cannot take an unbounded share;
  * a repository already measured as over capacity is excluded before its slots are
    spent, and an unmeasured repository is never excluded.

The dispatch-time capacity gate is unchanged and still the final backstop.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from actions_dispatch import (  # noqa: E402
    CAPACITY_MAX_REPOSITORY_KB, HYDRATION_BATCH, HYDRATION_PER_REPO,
    capacity_exclusions, pending_window)
from actions_github import GitHubError  # noqa: E402


def row(task_id, repository):
    return (task_id, json.dumps({"repository_url": "https://api.github.com/repos/" + repository,
                                 "number": 1}), "programs")


class FakeAPI:
    def __init__(self, sizes=None, error=None):
        self.sizes = sizes or {}
        self.error = error
        self.calls = []

    def api(self, path, method="GET", body=None):
        self.calls.append(path)
        if self.error:
            raise self.error
        repository = path.removeprefix("repos/")
        if repository in self.sizes:
            return {"size": self.sizes[repository]}
        return {"size": None}


class PerRepositoryCapTests(unittest.TestCase):
    def test_priority_hits_are_not_capped_below_the_fresh_band(self):
        """Fresh hits lead even when they concentrate: capping them starves current work.

        Pinned because the first draft of this fix capped the fresh band too, and
        ``test_measured_111_fresh_hits_lead_the_window_and_leftovers_stay_reachable``
        caught it: with 111 fresh hits in one repository, a cap of 4 pushed backlog rows
        ahead of current-cycle work. The capacity exclusion below is the narrow fix.
        """
        priority = [row("exp-%d" % index, "Expensify/App") for index in range(8)]
        spread = [row("%s-%d" % (name, index), name)
                  for name in ["r%02d/origin" % index for index in range(20)]
                  for index in range(4)]
        selected = pending_window(priority + spread, limit=60, per_repo=4,
                                  priority_ids=[item[0] for item in priority])
        taken = sum(1 for item in selected if "Expensify/App" in item[1])
        self.assertEqual(taken, 8)
        self.assertEqual(len(selected), 60)

    def test_priority_repository_still_leads_the_window(self):
        """Capping the share must not push a fresh hit behind the backlog."""
        priority = [row("exp-%d" % index, "Expensify/App") for index in range(3)]
        backlog = [row("old-%d" % index, "r%02d/origin" % index) for index in range(30)]
        selected = pending_window(backlog + priority, limit=10, per_repo=4,
                                  priority_ids=[item[0] for item in priority])
        self.assertEqual([item[0] for item in selected[:3]],
                         ["exp-0", "exp-1", "exp-2"])

    def test_a_single_origin_queue_still_drains_the_full_batch(self):
        """The cap is a share of a contested batch, never a truncation of a real one."""
        selected = pending_window([row("only-%d" % index, "owner/project") for index in range(101)])
        self.assertEqual(len(selected), HYDRATION_BATCH)


class CapacityExclusionTests(unittest.TestCase):
    def test_an_over_capacity_repository_is_excluded_before_hydration(self):
        rows = [row("exp-%d" % index, "Expensify/App") for index in range(8)]
        rows += [row("ok-%d" % index, "r%02d/origin" % index) for index in range(10)]
        api = FakeAPI({"Expensify/App": CAPACITY_MAX_REPOSITORY_KB + 1})
        cache = {}
        excluded = capacity_exclusions(api, rows, cache)
        self.assertEqual(excluded, {"expensify/app"})
        selected = pending_window(rows, limit=60, excluded_repositories=excluded)
        self.assertFalse([item for item in selected if "Expensify/App" in item[1]])
        self.assertEqual(len(selected), 10)

    def test_an_unmeasured_repository_is_never_excluded(self):
        """Unknown is not too large: a probe that returns nothing must not drop a target."""
        rows = [row("a", "unknown/one")]
        api = FakeAPI({})
        excluded = capacity_exclusions(api, rows, {})
        self.assertEqual(excluded, set())

    def test_a_probe_failure_is_not_evidence_of_size(self):
        """A transport error is caught by the probe and cached as unmeasured."""
        rows = [row("a", "broken/one")]
        api = FakeAPI(error=GitHubError("transport down"))
        cache = {}
        excluded = capacity_exclusions(api, rows, cache)
        self.assertEqual(excluded, set())
        self.assertIsNone(cache["broken/one"])

    def test_a_repository_at_the_limit_is_kept(self):
        rows = [row("a", "edge/one")]
        api = FakeAPI({"edge/one": CAPACITY_MAX_REPOSITORY_KB})
        self.assertEqual(capacity_exclusions(api, rows, {}), set())

    def test_probing_is_bounded_and_cached(self):
        rows = [row("r-%d" % index, "r%02d/origin" % index) for index in range(200)]
        api = FakeAPI({})
        cache = {}
        capacity_exclusions(api, rows, cache, limit=5)
        self.assertEqual(len(api.calls), 5)
        self.assertEqual(len(cache), 5)
        before = len(api.calls)
        capacity_exclusions(api, rows, cache, limit=5)
        # Five sizes are cached; the next five distinct repositories are probed, so the
        # call count grows by exactly the new breadth and never re-probes a known one.
        self.assertEqual(len(api.calls), before + 5)
        self.assertEqual(len(set(api.calls)), len(api.calls), "no repository may be probed twice")

    def test_an_empty_exclusion_set_changes_nothing(self):
        rows = [row("a", "x/one"), row("b", "x/one"), row("c", "y/two")]
        self.assertEqual(pending_window(rows, excluded_repositories=()),
                         pending_window(rows))


if __name__ == "__main__":
    unittest.main()
