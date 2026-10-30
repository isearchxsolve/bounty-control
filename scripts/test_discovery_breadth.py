"""Deterministic unit fixtures for the hydration window; not live delivery receipts.

GitHub search returns whole repositories. Before this contract the per-cycle
hydration budget was pure first-in-first-out over queued search results, so the
first two repositories in the queue consumed the entire batch:

    run 40531780003, 3 cycles, 56 admission evaluations
    limitlessprojects/Go-Hybrid      27   (0 money strings in any sampled issue)
    SecureBananaLabs/bug-bounty      23   (offers authored only by claim posters)
    oll4com/spaceapp                  1   (six funded issues existed in the queue)

The window is therefore required to spend the batch across origins without ever
shrinking it, because the durable queue also has to drain when it truly holds a
single origin.
"""
import json
import unittest

from actions_dispatch import HYDRATION_BATCH, HYDRATION_PER_REPO, pending_window


def row(task_id, repository):
    return (task_id, json.dumps({"repository_url": "https://api.github.com/repos/" + repository,
                                 "number": 1}), "normal")


class BreadthTests(unittest.TestCase):
    def test_one_repository_cannot_consume_the_batch(self):
        """The production shape: one flood ahead of enough breadth to fill the batch."""
        flood = [row("flood-%d" % index, "spam/flood") for index in range(200)]
        spread = [row("%s-%d" % (name, index), name)
                  for name in ["r%02d/origin" % index for index in range(20)]
                  for index in range(4)]
        selected = pending_window(flood + spread, limit=60, per_repo=4)
        self.assertEqual(len(selected), 60)
        self.assertEqual(sum(1 for item in selected if "spam/flood" in item[1]), HYDRATION_PER_REPO)
        self.assertEqual(len({json.loads(item[1])["repository_url"] for item in selected}), 15)

    def test_limited_breadth_is_topped_up_rather_than_shrinking_the_batch(self):
        """When breadth cannot fill the batch, leftovers top it up; the flood still loses."""
        flood = [row("flood-%d" % index, "spam/flood") for index in range(200)]
        spread = [row("%s-%d" % (name, index), name)
                  for name in ["a/one", "b/two", "c/three", "d/four", "e/five",
                               "f/six", "g/seven", "h/eight", "i/nine", "j/ten"]
                  for index in range(4)]
        selected = pending_window(flood + spread, limit=60, per_repo=4)
        self.assertEqual(len(selected), 60)
        # 40 rows of real breadth exist, so the flood receives only the 20-slot remainder.
        self.assertEqual(sum(1 for item in selected if "spam/flood" in item[1]),
                         HYDRATION_BATCH - 40)
        self.assertEqual(len({json.loads(item[1])["repository_url"] for item in selected}), 11)

    def test_single_origin_queue_still_drains_the_full_batch(self):
        """The untouched master fixture: 101 results from one repository, 60 checked."""
        selected = pending_window([row("only-%d" % index, "owner/project") for index in range(101)])
        self.assertEqual(len(selected), 60)

    def test_short_queue_returns_everything_once(self):
        rows = [row("a", "x/one"), row("b", "x/one"), row("c", "y/two")]
        selected = pending_window(rows)
        self.assertEqual(selected, rows)

    def test_empty_queue_is_not_an_error(self):
        self.assertEqual(pending_window([]), [])

    def test_selection_preserves_durable_queue_order(self):
        rows = [row("first", "x/one"), row("second", "y/two"), row("third", "x/one")]
        self.assertEqual([item[0] for item in pending_window(rows)], ["first", "second", "third"])

    def test_overflow_fills_after_every_origin_has_had_a_turn(self):
        """Breadth first, then leftovers: the batch is filled, never truncated."""
        rows = [row("x-%d" % index, "x/one") for index in range(10)]
        rows += [row("y-%d" % index, "y/two") for index in range(10)]
        selected = pending_window(rows, limit=12, per_repo=4)
        self.assertEqual(len(selected), 12)
        self.assertEqual([item[0] for item in selected],
                         ["x-0", "x-1", "x-2", "x-3", "y-0", "y-1", "y-2", "y-3",
                          "x-4", "x-5", "x-6", "x-7"])

    def test_defaults_match_the_declared_contract(self):
        self.assertEqual(HYDRATION_BATCH, 60)
        self.assertEqual(HYDRATION_PER_REPO, 4)


if __name__ == "__main__":
    unittest.main()
