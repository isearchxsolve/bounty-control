"""Isolated tests for index handoff; these do not contact the fleet."""
import unittest
import tempfile
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import indexed_fleet_dispatcher as handoff


class IndexHandoffTests(unittest.TestCase):
    def test_preview_opens_existing_index_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.sqlite3"
            with closing(handoff.index.connect(path)):
                pass
            with closing(handoff.open_index(path, live=False)) as db:
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("INSERT INTO candidates VALUES ('x',1,'u','t','deferred','r','{}',0)")

    def test_preview_does_not_recheck_or_dispatch(self):
        rows = [{"repo": "example/project", "number": 7}]
        with patch.object(handoff.index, "search_index", return_value=rows), \
             patch.object(handoff.index, "refresh_candidate") as refresh, \
             patch.object(handoff.policy, "post_grounded_proposal") as post:
            result = handoff.dispatch_index(None, 900, 10)
        self.assertEqual(result["mode"], "preview")
        refresh.assert_not_called()
        post.assert_not_called()

    def test_live_holds_changed_candidate_before_dispatch(self):
        rows = [{"repo": "example/project", "number": 7}]
        with patch.object(handoff.index, "search_index", return_value=rows), \
             patch.object(handoff.policy, "REMOTE_FLEET_MODE", True), \
             patch.object(handoff.policy, "verify_delivery_database_integrity", return_value={"integrity": "ok"}), \
             patch.object(handoff.index, "refresh_candidate", return_value={"status": "deferred", "reason": "new competing PR"}), \
             patch.object(handoff.policy, "post_grounded_proposal") as post:
            result = handoff.dispatch_index(None, 900, 10, live=True)
        self.assertEqual(result["outcomes"][0]["status"], "held")
        post.assert_not_called()

    def test_live_handoff_uses_existing_dispatch_gate(self):
        rows = [{"repo": "example/project", "number": 7}]
        fresh = {"status": "qualified", "reason": "current offer", "evidence": {"corridor": "global", "funding": {"payer_association": "MEMBER"}}}
        issue = {"state": "OPEN", "title": "Fix", "body": "details", "author": {"login": "owner"},
                 "authorAssociation": "OWNER", "author_comments": [], "labels": []}
        with patch.object(handoff.index, "search_index", return_value=rows), \
             patch.object(handoff.policy, "REMOTE_FLEET_MODE", True), \
             patch.object(handoff.policy, "verify_delivery_database_integrity", return_value={"integrity": "ok"}), \
             patch.object(handoff.index, "refresh_candidate", return_value=fresh), \
             patch.object(handoff.policy, "get_issue_fast", return_value=issue), \
             patch.object(handoff.policy, "post_grounded_proposal", return_value=True) as post:
            result = handoff.dispatch_index(None, 900, 10, live=True)
        self.assertEqual(result["outcomes"][0]["status"], "queued")
        self.assertTrue(post.call_args.kwargs["live_mode"])
        self.assertEqual(post.call_args.kwargs["payer_assoc"], "MEMBER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
