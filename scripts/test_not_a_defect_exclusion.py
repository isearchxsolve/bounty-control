"""Unit tests for the not-a-defect supply-side exclusion gate.

Covers:
  * has_not_a_defect_label() -- live label check on the issue payload
  * query_exclusion_status() -- durable queue status mapping
  * retire_query_excluded_pending() -- cache retirement on policy change
  * refreshed_query_exclusion() -- pre-dispatch live re-check
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import os

from actions_dispatch import (
    has_not_a_defect_label,
    query_exclusion_status,
    retire_query_excluded_pending,
    refreshed_query_exclusion,
    QUERY_EXCLUDED_NOT_A_DEFECT,
    QUERY_EXCLUDED_ASSIGNED,
    NOT_A_DEFECT_LABELS,
)


def issue(labels=None, repository="owner/repo", number=1):
    return {
        "repository_url": f"https://api.github.com/repos/{repository}",
        "number": number,
        "labels": [{"name": name} for name in (labels or [])],
        "updated_at": "2026-01-01T00:00:00Z",
    }


def context(issue=None, repo="owner/repo", number=1):
    return {
        "repo": repo,
        "issue_number": number,
        "repository": {"owner": {"login": "owner"}, "full_name": repo, "archived": False, "disabled": False},
        "issue": issue if issue is not None else issue(),
        "comments": [],
        "complete_comments": True,
        "fetched_at": "unit fixture",
    }


class HasNotADefectLabelTests(unittest.TestCase):
    def test_not_a_defect_label_is_detected(self):
        self.assertTrue(has_not_a_defect_label(issue(["not-a-defect"])))

    def test_all_not_a_defect_label_variants(self):
        for label in NOT_A_DEFECT_LABELS:
            with self.subTest(label=label):
                self.assertTrue(has_not_a_defect_label(issue([label])))

    def test_bug_label_is_not_a_defect(self):
        self.assertFalse(has_not_a_defect_label(issue(["bug"])))

    def test_engineering_label_is_not_a_defect(self):
        self.assertFalse(has_not_a_defect_label(issue(["type/engineering"])))

    def test_empty_labels(self):
        self.assertFalse(has_not_a_defect_label(issue([])))

    def test_missing_labels_key(self):
        item = {"repository_url": "https://api.github.com/repos/owner/repo", "number": 1}
        self.assertFalse(has_not_a_defect_label(item))

    def test_labels_as_plain_strings(self):
        self.assertTrue(has_not_a_defect_label({"labels": ["invalid", "wontfix"]}))
        self.assertFalse(has_not_a_defect_label({"labels": ["bug", "enhancement"]}))


class QueryExclusionStatusTests(unittest.TestCase):
    def test_not_a_defect_maps_to_query_excluded_not_a_defect(self):
        self.assertEqual(
            query_exclusion_status(issue(["not-a-defect"])), QUERY_EXCLUDED_NOT_A_DEFECT
        )

    def test_assigned_maps_to_query_excluded_assigned(self):
        item = issue([])
        item["assignees"] = [{"login": "someone"}]
        self.assertEqual(
            query_exclusion_status(item), QUERY_EXCLUDED_ASSIGNED
        )

    def test_assigned_with_help_wanted_is_not_excluded(self):
        item = issue([])
        item["assignees"] = [{"login": "someone"}]
        item["labels"] = [{"name": "Help Wanted"}]
        self.assertEqual(query_exclusion_status(item), "")

    def test_clean_issue_returns_empty(self):
        self.assertEqual(query_exclusion_status(issue(["bug"])), "")


class RefreshedQueryExclusionTests(unittest.TestCase):
    def test_pre_dispatch_catches_not_a_defect(self):
        ctx = context(issue(["wontfix"]))
        self.assertEqual(refreshed_query_exclusion(ctx), QUERY_EXCLUDED_NOT_A_DEFECT)

    def test_pre_dispatch_passes_clean_issue(self):
        ctx = context(issue(["bug"]))
        self.assertEqual(refreshed_query_exclusion(ctx), "")

    def test_missing_issue_in_context_returns_empty(self):
        self.assertEqual(refreshed_query_exclusion({}), "")


class RetireQueryExcludedPendingTests(unittest.TestCase):
    def _make_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        tmp.close()
        con = sqlite3.connect(tmp.name)
        con.execute(
            "CREATE TABLE IF NOT EXISTS pending("
            "task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
            "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending')"
        )
        return con, tmp.name

    def test_retires_not_a_defect_rows(self):
        con, path = self._make_db()
        try:
            con.execute(
                "INSERT INTO pending VALUES(?,?,?,?,?,?)",
                ("repo#1", json.dumps(issue(["not-a-defect"])), "[]", "x", 0, "pending"),
            )
            con.execute(
                "INSERT INTO pending VALUES(?,?,?,?,?,?)",
                ("repo#2", json.dumps(issue(["bug"])), "[]", "x", 0, "pending"),
            )
            con.commit()
            retired = retire_query_excluded_pending(con)
            con.commit()
            self.assertEqual(retired.get(QUERY_EXCLUDED_NOT_A_DEFECT), 1)
            row = con.execute("SELECT status FROM pending WHERE task_id='repo#2'").fetchone()
            self.assertEqual(row[0], "pending")
        finally:
            con.close()
            os.unlink(path)

    def test_retires_assigned_rows(self):
        con, path = self._make_db()
        try:
            item = issue([])
            item["assignees"] = [{"login": "someone"}]
            con.execute(
                "INSERT INTO pending VALUES(?,?,?,?,?,?)",
                ("repo#1", json.dumps(item), "[]", "x", 0, "pending"),
            )
            con.commit()
            retired = retire_query_excluded_pending(con)
            con.commit()
            self.assertEqual(retired.get(QUERY_EXCLUDED_ASSIGNED), 1)
        finally:
            con.close()
            os.unlink(path)

    def test_retirement_changes_status_to_exclusion(self):
        con, path = self._make_db()
        try:
            con.execute(
                "INSERT INTO pending VALUES(?,?,?,?,?,?)",
                ("repo#1", json.dumps(issue(["invalid"])), "[]", "x", 0, "pending"),
            )
            con.commit()
            retire_query_excluded_pending(con)
            con.commit()
            row = con.execute("SELECT status FROM pending WHERE task_id='repo#1'").fetchone()
            self.assertEqual(row[0], QUERY_EXCLUDED_NOT_A_DEFECT)
        finally:
            con.close()
            os.unlink(path)
