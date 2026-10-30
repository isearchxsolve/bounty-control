"""Isolated checks for bounded index scouting."""
from contextlib import closing, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bounty_candidate_index as index
import bounty_index_scout as runner


class ScoutTests(unittest.TestCase):
    def test_stops_on_candidate_and_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            with closing(index.connect(Path(tmp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 1, int(runner.time.time()))
                with patch.object(index, "partition_step", return_value={"action": "ready"}), \
                     patch.object(index, "search_index", return_value=[{"repo": "example/project", "number": 7}]), \
                     patch.object(runner.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
                    status = runner.scout(db, 20, 30, 10, 5)
                self.assertEqual(status, "candidate_available")
                sleep.assert_not_called()

    def test_errors_and_incomplete_pages_do_not_end_bounded_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            with closing(index.connect(Path(tmp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 1, int(runner.time.time()))
                with patch.object(index, "partition_step", side_effect=[index.IncompleteEvidence("rate limited"), {"action": "page_complete_with_errors"}]), \
                     patch.object(index, "search_index", return_value=[]), \
                     patch.object(runner.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
                    status = runner.scout(db, 2, 30, 10, 5)
                self.assertEqual(status, "cycle_budget_exhausted_with_errors")
                sleep.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
