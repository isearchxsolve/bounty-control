"""Regression tests for per-account lane partitioning (ACTIVE_LANES).

Three defects this locks down, all observed in production on 2026-10-29:

  * ``--lane "startup normal"`` died with ``unrecognized arguments: normal``
    (run 40855864063) because the flag was an argparse ``choices`` value;
  * the lane list only chose which searches ran, while dispatch drew from the
    accumulated pending queue, so a worker scoped to ``startup normal`` claimed a
    task recorded as ``lanes=['programs']``;
  * ``PRIORITY_DISCOVERY_QUERIES`` was labelled ``programs`` unconditionally, so
    every cycle injected programs-lane rows into every worker.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from actions_dispatch import QUERIES, parse_lanes  # noqa: E402


class LaneParsingTests(unittest.TestCase):
    def test_space_separated_list_is_accepted(self):
        self.assertEqual(parse_lanes("startup normal"), ["startup", "normal"])

    def test_comma_and_space_separated_list_is_accepted(self):
        self.assertEqual(parse_lanes(" startup ,normal "), ["startup", "normal"])

    def test_single_lane_stays_a_single_lane(self):
        self.assertEqual(parse_lanes("startup"), ["startup"])

    def test_all_expands_to_every_lane(self):
        self.assertEqual(parse_lanes("all"), list(QUERIES))

    def test_empty_value_means_every_lane(self):
        for value in ("", None, "   "):
            self.assertEqual(parse_lanes(value), list(QUERIES))

    def test_duplicates_are_collapsed_preserving_order(self):
        self.assertEqual(parse_lanes("founder startup founder"), ["founder", "startup"])

    def test_unknown_lane_is_refused(self):
        with self.assertRaises(ValueError):
            parse_lanes("startup progams")

    def test_all_together_with_a_named_lane_is_still_all(self):
        # "all" is a union, never an intersection: naming it must not silently narrow.
        self.assertEqual(parse_lanes("all startup"), list(QUERIES))


class PartitionEnforcementTests(unittest.TestCase):
    """The lane filter must reach the queue and the dispatch loop, not only the queries."""

    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parent / "actions_dispatch.py").read_text(
            encoding="utf-8-sig")

    def test_priority_programme_queries_are_gated_by_the_active_lane(self):
        self.assertIn('if "programs" in active_lanes:', self.source)
        gated = self.source.index('if "programs" in active_lanes:')
        unconditional = self.source.index("for expression in PRIORITY_DISCOVERY_QUERIES:")
        self.assertLess(gated, unconditional)

    def test_the_pending_queue_is_filtered_by_lane(self):
        self.assertIn("if not whole_queues:", self.source)
        self.assertIn("if set(json.loads(row[2])) & active_lanes", self.source)

    def test_dispatch_rechecks_the_candidate_lane_set(self):
        self.assertIn("counts[\"out_of_lane_candidate\"] += 1", self.source)

    def test_whole_queue_detection_uses_superset_not_equality(self):
        # A worker configured with every lane explicitly is still a whole-queue worker.
        self.assertIn("whole_queues = active_lanes >= set(QUERIES)", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
