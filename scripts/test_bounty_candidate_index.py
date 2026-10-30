"""Regression tests for the candidate index; no live receipts are mocked here."""
import tempfile
import time
import unittest
from contextlib import closing
import json
from pathlib import Path
from unittest.mock import patch

import bounty_candidate_index as index


class CandidateIndexTests(unittest.TestCase):
    def issue(self, body=""):
        return {"title": "Repair a storage race", "body": body,
                "html_url": "https://github.com/example/project/issues/7",
                "author_association": "OWNER", "user": {"login": "example"},
                "state": "open", "comments": 0, "labels": []}

    def test_html_dashboard_amount_is_not_a_funding_offer(self):
        issue = self.issue('<!DOCTYPE html><html><p>Bounty marketplace</p><p>Total spent $5000</p></html>')
        self.assertIsNone(index.funding_evidence(issue, [])[0])
        self.assertIsNone(index.funding_evidence(self.issue("> A prior bounty was $500\nPlease fix the bug."), [])[0])
        self.assertIsNone(index.funding_evidence(self.issue("Log sample: `bounty $500`"), [])[0])

    def test_legacy_search_handles_unquoted_crypto_without_inventing_a_rate(self):
        candidate = {"number": 7, "title": "Bounty 0.1 ETH: fix storage race",
                     "body": "Reproduce the concurrency failure in the storage writer.",
                     "repository": {"nameWithOwner": "example/project"}, "labels": [],
                     "author": {"login": "author"}, "authorAssociation": "NONE",
                     "commentsCount": 0, "createdAt": "2026-10-25T00:00:00Z"}
        with patch.object(index.policy, "run_cmd", return_value=(json.dumps([candidate]), "", 0)):
            results = index.policy.search_issues("bounty", limit=10)
        self.assertEqual([x["number"] for x in results], [7])
        self.assertIsNone(index.policy.parse_and_normalize_bounty(candidate["title"])[3])

    def test_funding_can_come_from_authoritative_comments(self):
        comment = {"user": {"login": "algora-pbc"}, "author_association": "NONE",
                   "html_url": "https://github.com/example/project/issues/7#issuecomment-1",
                   "body": "A $150 bounty was created for this issue."}
        evidence, _ = index.funding_evidence(self.issue(), [comment])
        self.assertEqual(evidence["amount"], "150")
        self.assertEqual(evidence["actor"], "algora-pbc")
        comment["user"]["login"] = "random-user"
        self.assertIsNone(index.funding_evidence(self.issue(), [comment])[0])

    def test_issue_author_can_offer_direct_payment_without_maintainer_role(self):
        issue = self.issue("I will pay $150 via PayPal for a fix to this issue.")
        issue["author_association"] = "NONE"
        issue["user"]["login"] = "outside-sponsor"
        evidence, _ = index.funding_evidence(issue, [])
        self.assertEqual(evidence["actor"], "outside-sponsor")
        issue["body"] = "Please pay me $150 via PayPal for my fix."
        self.assertIsNone(index.funding_evidence(issue, [])[0])

    def test_retracted_and_below_floor_offers_cannot_qualify(self):
        for text in ("Bounty: $49", "~~Bounty: $500~~", "Bounty: $500. The bounty is cancelled."):
            with self.subTest(text=text):
                self.assertIsNone(index.funding_evidence(self.issue(text), [])[0])

    def test_currency_suffix_is_not_misread_as_a_small_amount(self):
        evidence, _ = index.funding_evidence(self.issue("Offering a $1.5k bounty for this fix."), [])
        self.assertEqual(evidence["amount"], "1500.0")

    def test_complete_eligible_evidence_can_be_indexed(self):
        issue = self.issue("We offer a $150 bounty for this bug fix.")
        with patch.object(index, "gh_api", return_value=issue), \
             patch.object(index, "pages", return_value=[]), \
             patch.object(index.policy, "verify_genuine_icu_patient", return_value=(True, "eligible")), \
             patch.object(index.policy, "detect_author_corridor", return_value=("Global", True, "worldwide")):
            status, _, evidence = index.check_candidate("example/project", 7)
        self.assertEqual(status, "qualified")
        self.assertEqual(evidence["funding"]["amount"], "150")

    def test_maintainer_comment_can_fund_an_external_authors_issue(self):
        issue = self.issue("The storage race drops pending work.")
        issue["author_association"] = "CONTRIBUTOR"
        issue["user"]["login"] = "reporter"
        issue["comments"] = 1
        comment = {"user": {"login": "maintainer"}, "author_association": "MEMBER",
                   "body": "/bounty $50", "html_url": "https://github.com/example/project/issues/7#issuecomment-1"}
        with patch.object(index, "gh_api", return_value=issue), \
             patch.object(index, "pages", side_effect=[[comment], [], []]), \
             patch.object(index.policy, "detect_author_corridor", return_value=("Global", True, "worldwide")):
            status, _, evidence = index.check_candidate("example/project", 7)
        self.assertEqual(status, "qualified")
        self.assertEqual(evidence["funding"]["payer_association"], "MEMBER")
        comment["author_association"] = "NONE"
        self.assertIsNone(index.funding_evidence(issue, [comment])[0])

    def test_pagination_failure_does_not_mean_no_competition(self):
        first_page = [{"number": i, "head": {}, "title": "other", "body": ""} for i in range(100)]
        with patch.object(index, "gh_api", return_value=first_page):
            with self.assertRaises(index.IncompleteEvidence):
                index.competing_prs("example/project", 7, max_pages=1)
        with patch.object(index, "pages", return_value=[{"number": 9, "head": {"ref": "fix/7"}, "title": "Repair", "body": ""}]):
            self.assertIn("#9", index.competing_prs("example/project", 7))

    def test_open_cross_repository_timeline_pr_blocks_eligibility(self):
        event = {"source": {"issue": {"pull_request": {}, "state": "open", "html_url": "https://github.com/other/project/pull/4"}}}
        # GitHub's pull_request field is a nonempty metadata object in real responses.
        event["source"]["issue"]["pull_request"] = {"url": "https://api.github.com/repos/other/project/pulls/4"}
        with patch.object(index, "pages", return_value=[event]):
            self.assertEqual(index.linked_prs("example/project", 7), "https://github.com/other/project/pull/4")

    def test_search_excludes_unchecked_errors_and_expired_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                now = time.time()
                for number, status, age in [(1, "qualified", 1), (2, "qualified", 1000),
                                             (3, "error", 1), (4, "checking", 1), (5, "deferred", 1)]:
                    index.store(db, "example/project", number, "https://example.invalid", "Issue", status, "reason", {"rules_signature": index.rules_signature()}, now - age)
                self.assertEqual([x["number"] for x in index.search_index(db, 100, now)], [1])
                with patch.object(index, "rules_signature", return_value="changed"):
                    with self.assertRaises(index.IncompleteEvidence):
                        index.search_index(db, 100, now)
                index.store(db, "example/project", 1, "https://example.invalid", "Issue", "checking", "checking", {}, now)
                self.assertEqual(index.search_index(db, 100, now), [])

    def test_incomplete_search_is_error_not_empty_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db, patch.object(index, "gh_api", return_value={"incomplete_results": True}):
                with self.assertRaises(index.IncompleteEvidence):
                    index.scan(db, "", 10, 1)
                self.assertEqual(db.execute("SELECT status FROM scans").fetchone()[0], "error")

    def test_overlapping_check_cannot_overwrite_newer_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.store(db, "example/project", 7, "url", "title", "checking", "old", {}, 10)
                index.store(db, "example/project", 7, "url", "title", "checking", "new", {}, 11)
                self.assertTrue(index.finish_check(db, "example/project", 7, 11, "deferred", "new result", {}))
                self.assertFalse(index.finish_check(db, "example/project", 7, 10, "qualified", "stale result", {}))
                self.assertEqual(db.execute("SELECT status,reason FROM candidates").fetchone(), ("deferred", "new result"))

    def test_time_partitions_split_without_gaps_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 100, 199)
                with patch.object(index, "gh_api", return_value={"total_count": 1001, "incomplete_results": False}):
                    self.assertEqual(index.partition_step(db, 10, 2, True)["action"], "split")
                children = db.execute("SELECT start_epoch,end_epoch FROM partitions WHERE status='pending' ORDER BY start_epoch").fetchall()
                self.assertEqual(children, [(100, 149), (150, 199)])
                with patch.object(index, "gh_api", return_value={"total_count": 20, "incomplete_results": False}):
                    self.assertEqual(index.partition_step(db, 10, 2, True)["action"], "ready")
                    self.assertEqual(index.partition_step(db, 10, 2, True)["action"], "ready")
                partial = {"status": "partial_error", "examined": 10, "total_count": 20, "github_result_cap_reached": False, "untracked_errors": 1}
                with patch.object(index, "scan", return_value=partial):
                    self.assertEqual(index.partition_step(db, 10, 2)["action"], "retry_page")
                self.assertIn((1, 10), db.execute("SELECT next_page,page_size FROM partitions WHERE status='ready'").fetchall())
                db.execute("UPDATE partitions SET page_size=10 WHERE status='ready'")
                db.commit()
                with self.assertRaises(index.IncompleteEvidence):
                    index.partition_step(db, 20, 2)

    def test_recorded_issue_errors_do_not_stall_partition(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 100, 199)
                with patch.object(index, "gh_api", return_value={"total_count": 20, "incomplete_results": False}):
                    index.partition_step(db, 10, 2, True)
                partial = {"status": "partial_error", "examined": 10, "total_count": 20,
                           "github_result_cap_reached": False, "untracked_errors": 0}
                with patch.object(index, "scan", return_value=partial):
                    self.assertEqual(index.partition_step(db, 10, 2)["action"], "page_complete_with_errors")
                self.assertEqual(db.execute("SELECT next_page FROM partitions").fetchone()[0], 2)

    def test_failed_issue_is_persisted_and_can_be_retried(self):
        result = {"total_count": 1, "incomplete_results": False, "items": [{
            "number": 7, "repository_url": "https://api.github.com/repos/example/project",
            "html_url": "https://github.com/example/project/issues/7", "title": "Fix"}]}
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                with patch.object(index, "gh_api", return_value=result), \
                     patch.object(index, "check_candidate", side_effect=index.IncompleteEvidence("incomplete comments")):
                    receipt = index.scan(db, "", 10, 1)
                self.assertEqual(receipt["untracked_errors"], 0)
                self.assertEqual(db.execute("SELECT status FROM candidates").fetchone()[0], "error")
                self.assertEqual(index.search_index(db, 900), [])
                with patch.object(index, "gh_api", return_value=self.issue()), \
                     patch.object(index, "check_candidate", return_value=("deferred", "no funding", {})):
                    retried = index.refresh_candidate(db, "example/project", 7, 1)
                self.assertEqual(retried["status"], "deferred")

    def test_global_and_priority_lanes_are_both_served(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 100, 199)
                index.seed_partition(db, "bounty", 100, 199)
                with patch.object(index, "gh_api", return_value={"total_count": 1001, "incomplete_results": False}):
                    first = index.partition_step(db, 10, 2, True)
                    second = index.partition_step(db, 10, 2, True)
                terms = [db.execute("SELECT term FROM partitions WHERE id=?", (item["id"],)).fetchone()[0] for item in (first, second)]
                self.assertEqual(terms, ["", "bounty"])

    def test_newest_and_oldest_ranges_both_make_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 100, 199)
                index.seed_partition(db, "", 900, 999)
                db.execute("UPDATE partitions SET status='ready'")
                db.commit()
                page = {"status": "complete_sample", "examined": 10, "total_count": 20,
                        "github_result_cap_reached": False}
                with patch.object(index, "scan", return_value=page):
                    first = index.partition_step(db, 10, 2)
                    second = index.partition_step(db, 10, 2)
                starts = [db.execute("SELECT start_epoch FROM partitions WHERE id=?", (item["id"],)).fetchone()[0] for item in (first, second)]
                self.assertEqual(starts, [900, 100])

    def test_new_issues_extend_a_lane_without_overlap_or_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(index.connect(Path(temp) / "index.sqlite3")) as db:
                index.seed_partition(db, "", 100, 199)
                self.assertEqual(index.extend_partition(db, "", 250), 200)
                self.assertIsNone(index.extend_partition(db, "", 249))
                self.assertEqual(db.execute("SELECT start_epoch,end_epoch FROM partitions ORDER BY start_epoch").fetchall(), [(100, 199), (200, 250)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
