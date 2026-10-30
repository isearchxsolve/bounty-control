#!/usr/bin/env python3
"""F11 contract: a census, not a judgement.

The census tabs what the queue already recorded. It must never change a gate: these tests
only ever read, and they assert the counts the pipeline can be steered by.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from f11_refusal_census import (  # noqa: E402
    census_labels, census_refusals, extract_sample, write_labeling_csv, write_labeling_json)

SCHEMA = ("CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
          "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending')")


def payload(number, title, body, labels, status="pending"):
    return json.dumps({"number": number, "title": title, "body": body,
                       "labels": [{"name": name} for name in labels],
                       "state": "open",
                       "repository_url": "https://api.github.com/repos/unit/runtime",
                       "url": "https://api.github.com/repos/unit/runtime/issues/" + str(number),
                       "status": status}, ), status


def queue():
    con = sqlite3.connect(":memory:")
    con.execute(SCHEMA)
    rows = [payload(1, "Fix crash in parser", "Panic in src/config/parse.go", ["bug"]),
            payload(2, "Bounty escrow", "payment guaranteed, ver enlace", ["escrow"]),
            payload(3, "Triage board", "meta checklist", []),
            payload(4, "Add feature", "please implement in lib/app.ts", ["enhancement"])]
    for index, (body, status) in enumerate(rows, start=1):
        con.execute("INSERT INTO pending(task_id, payload, status) VALUES (?,?,?)",
                    (str(index), body, status))
    return con


class CensusTests(unittest.TestCase):
    def test_refusals_are_counted_by_recorded_status(self):
        con = queue()
        con.execute("UPDATE pending SET status='rejected_repository_intent' WHERE task_id='2'")
        self.assertEqual(census_refusals(con),
                         {"pending": 3, "rejected_repository_intent": 1})

    def test_a_missing_queue_is_an_empty_census_not_a_crash(self):
        self.assertEqual(census_refusals(None), {})

    def test_labels_are_counted_across_the_queue(self):
        counts = census_labels(queue())
        self.assertEqual(counts["bug"], 1)
        self.assertEqual(counts["escrow"], 1)
        self.assertEqual(counts["enhancement"], 1)

    def test_an_unparseable_payload_is_skipped_not_counted(self):
        con = queue()
        con.execute("INSERT INTO pending(task_id, payload) VALUES ('9', 'not json')")
        self.assertEqual(sum(census_labels(con).values()), 3)
        self.assertEqual(census_refusals(con)["pending"], 5)


class SampleTests(unittest.TestCase):
    def test_the_sample_honours_its_size(self):
        con = queue()
        for index in range(10, 30):
            con.execute("INSERT INTO pending(task_id, payload, status) VALUES (?,?,?)",
                        (str(index), payload(index, "Filler " + str(index), "body", ["bug"])[0],
                         "pending"))
        self.assertLessEqual(len(extract_sample(con, 3)), 3)

    def test_every_row_carries_the_labels_the_census_reports(self):
        sample = extract_sample(queue(), 10)
        self.assertTrue(sample)
        for row in sample:
            self.assertIn("task_id", row)
            self.assertIn("repo", row)
            self.assertIn("labels", row)
            self.assertIsInstance(row["labels"], list)
            self.assertIsInstance(row["has_code_reference"], bool)

    def test_a_missing_queue_produces_no_sample(self):
        self.assertEqual(extract_sample(None), [])

    def test_the_labeling_artifacts_are_written(self):
        sample = extract_sample(queue(), 10)
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory, "sample.csv")
            json_path = Path(directory, "sample.json")
            write_labeling_csv(sample, csv_path)
            write_labeling_json(sample, json_path)
            self.assertTrue(csv_path.is_file())
            self.assertTrue(json_path.is_file())
            lines = [line for line in csv_path.read_text(encoding="utf-8").splitlines() if line]
            self.assertIn("task_id", lines[0])
            self.assertEqual(len(lines) - 1, len(sample))
            self.assertEqual(len(json.loads(json_path.read_text(encoding="utf-8"))), len(sample))


if __name__ == "__main__":
    unittest.main(verbosity=2)
