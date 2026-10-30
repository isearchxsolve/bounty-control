#!/usr/bin/env python3
"""F12 contract: the digest tabulates, it never judges.

It reads the durable receipts and census and reports the funnel. ``refusal_reasons`` used to
reference an undefined name and raised ``NameError`` on any receipt carrying a refusal, so the
digest could not have produced a refusal table at all.
"""
import json
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from failure_digest import (  # noqa: E402
    funnel_by_status, load_census, load_receipts, refusal_reasons)

RECEIPTS = [
    {"at": "2026-10-27T10:00:00Z", "dispatched": 2,
     "counts": {"admission_changed.external": 3, "admission_changed.process": 1}},

    {"at": "2026-10-27T11:00:00Z", "dispatched": 1,
     "counts": {"CURRENT_ALREADY_OWNED": 2, "admission_changed.external": 1}},
    {"at": "2026-10-27T12:00:00Z", "dispatched": 0, "counts": {}},
]


class DigestTests(unittest.TestCase):
    def _directory(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "receipts.jsonl").write_text(
            "\n".join(json.dumps(row) for row in RECEIPTS) + "\n", encoding="utf-8")
        (directory / "census.jsonl").write_text(
            json.dumps({"qualified": 3}) + "\n" + "not json\n", encoding="utf-8")
        return directory

    def test_receipts_are_loaded_and_malformed_lines_are_skipped(self):
        directory = self._directory()
        with (directory / "receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{{{ broken\n")
        self.assertEqual(len(load_receipts(directory)), len(RECEIPTS))

    def test_a_missing_ledger_is_an_empty_digest_not_a_crash(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(load_receipts(Path(empty)), [])
            self.assertEqual(load_census(Path(empty)), [])
            self.assertEqual(funnel_by_status([]), {})  # an empty ledger tabulates to nothing
            self.assertEqual(refusal_reasons([]), {})

    def test_the_census_skips_unparseable_lines(self):
        self.assertEqual(load_census(self._directory()), [{"qualified": 3}])

    def test_the_funnel_totals_dispatches_and_refusals(self):
        funnel = funnel_by_status(RECEIPTS)
        self.assertEqual(funnel["dispatched"], 3)
        self.assertEqual(funnel["refused"], 7)

    def test_refusal_reasons_are_tabulated_by_key(self):
        # Regression: this raised NameError ('k' is not defined) for any refusal receipt.
        reasons = refusal_reasons(RECEIPTS)
        self.assertEqual(reasons["admission_changed.external"], 4)
        self.assertEqual(reasons["CURRENT_ALREADY_OWNED"], 2)
        self.assertNotIn("dispatched", reasons)


if __name__ == "__main__":
    unittest.main(verbosity=2)
