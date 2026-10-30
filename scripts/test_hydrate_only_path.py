"""The hydrate-only lane must survive a candidate it never measured.

Two defects masked each other for the whole life of the pipeline, and fixing the first exposed
the second. That is the reason this file exists.

1. The queue was split into two cache silos (discovery-* and hydration-*), so the drainer always
   saw zero pending rows. Run 41015801660: queued_total_pending 0 while discovery held 890.
2. The drain loop indexed candidate["velocity_24h"] directly, but hydrate-only runs never
   measure velocity - they run on the REST/GraphQL core budget rather than the search API, and
   the comment right above the call says so.

While the queue was empty, the loop body never executed, so defect 2 could not fire. Once the
silos were joined (b3eed93), run 41016832562 saw 33 rows, entered the loop, and died:

    KeyError: 'velocity_24h'

Neither bug looked like a bug from outside: the drain reported success and did nothing.
"""

import pathlib
import unittest

import actions_dispatch
from actions_dispatch import preparation_budget_seconds

HERE = pathlib.Path(__file__).parent


class HydrateOnlySurvivesUnmeasuredVelocity(unittest.TestCase):
    def test_budget_accepts_an_unmeasured_velocity(self):
        self.assertIsInstance(preparation_budget_seconds(None), int)

    def test_budget_is_the_full_window_either_way(self):
        self.assertEqual(preparation_budget_seconds(None),
                         preparation_budget_seconds(12))

    def test_the_drain_never_indexes_velocity_directly(self):
        source = (HERE / "actions_dispatch.py").read_text(encoding="utf-8")
        body = source.split("candidate[\"size_kb\"]", 1)[1].split("candidates = dict(", 1)[0]
        self.assertIn('candidate.get("velocity_24h")', body)
        self.assertNotIn('candidate["velocity_24h"])', body,
                         "direct indexing reintroduces the KeyError the empty queue was hiding")

    def test_an_unmeasured_velocity_still_sorts_last(self):
        measured = ("a", {"velocity_24h": 3})
        unmeasured = ("b", {})
        self.assertGreater(actions_dispatch.velocity_sort_key(unmeasured),
                           actions_dispatch.velocity_sort_key(measured))


if __name__ == "__main__":
    unittest.main()
