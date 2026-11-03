#!/usr/bin/env python3
"""Unit tests for Email Inbox Watcher & Lead Ingester."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import email_inbox_watcher as watcher


class TestEmailInboxWatcher(unittest.TestCase):
    def test_decode_str(self):
        self.assertEqual(watcher.decode_str(None), "")
        self.assertEqual(watcher.decode_str("Simple Subject"), "Simple Subject")
        # RFC 2047 encoded-word
        encoded = "=?UTF-8?Q?=F0=9F=92=8E_Bounty;_$50?="
        decoded = watcher.decode_str(encoded)
        self.assertIn("50", decoded)

    def test_multiline_subject_and_crlf_unfolding(self):
        """Verify RFC 2822 multiline folding in email subjects parses correctly."""
        raw_msg = (
            b"From: notifications@github.com\r\n"
            b"Subject: Re: [claude-builders-bounty/claude-builders-bounty] [BOUNTY $50]\r\n"
            b" SKILL: Generate a structured CHANGELOG from git history (Issue #1)\r\n"
            b"List-ID: claude-builders-bounty/claude-builders-bounty <claude.github.com>\r\n"
            b"X-GitHub-IssueState: open\r\n"
            b"X-GitHub-Labels: bounty; skill\r\n\r\n"
            b"Body content here"
        )
        fake_fetched = [(b"1 (BODY[HEADER] {123}", raw_msg)]
        
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", fake_fetched)

        with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
            tf.write("dummy_pw")
            tf_path = Path(tf.name)

        try:
            with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
                leads = watcher.fetch_imap_leads(pw_file=tf_path)
            self.assertEqual(len(leads), 1)
            self.assertEqual(leads[0]["repo"], "claude-builders-bounty/claude-builders-bounty")
            self.assertEqual(leads[0]["issue"], 1)
            self.assertEqual(leads[0]["usd_value"], 50)
            self.assertEqual(leads[0]["state"], "open")
            self.assertIn("CHANGELOG", leads[0]["title"])
        finally:
            tf_path.unlink(missing_ok=True)

    def test_price_parsing_variations(self):
        """Verify USD price parsing for amounts with k suffix and usd suffix."""
        test_cases = [
            ("[Bounty $3k] Neural Network Research", 3000),
            ("[BOUNTY $100] Fix security vulnerability", 100),
            ("Bug bounty 250 usd for landing page", 250),
            ("No price mentioned", 0),
        ]
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])

        with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
            tf.write("dummy_pw")
            tf_path = Path(tf.name)

        try:
            for idx, (title, expected_price) in enumerate(test_cases, 1):
                raw_msg = (
                    f"From: notifications@github.com\r\n"
                    f"Subject: [test-owner/test-repo] {title} (Issue #{idx})\r\n"
                    f"List-ID: test-owner/test-repo\r\n\r\n"
                ).encode("utf-8")
                mock_imap.search.return_value = ("OK", [str(idx).encode("ascii")])
                mock_imap.fetch.return_value = ("OK", [(b"1", raw_msg)])
                with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
                    leads = watcher.fetch_imap_leads(pw_file=tf_path)
                self.assertEqual(len(leads), 1)
                self.assertEqual(leads[0]["usd_value"], expected_price)
        finally:
            tf_path.unlink(missing_ok=True)

    def test_filters_internal_bounty_control_ci_failures(self):
        """Ensure internal repository CI notifications are excluded."""
        raw_msg = (
            b"From: notifications@github.com\r\n"
            b"Subject: [isearchxsolve/bounty-control] Run failed: Bounty delivery - main (51f6b82)\r\n"
            b"List-ID: isearchxsolve/bounty-control\r\n\r\n"
        )
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1", raw_msg)])

        with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
            tf.write("dummy_pw")
            tf_path = Path(tf.name)

        try:
            with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
                leads = watcher.fetch_imap_leads(pw_file=tf_path)
            self.assertEqual(len(leads), 0)
        finally:
            tf_path.unlink(missing_ok=True)

    def test_missing_credentials_fails_gracefully(self):
        non_existent = Path("D:/non_existent_vault_pw.txt")
        leads = watcher.fetch_imap_leads(pw_file=non_existent)
        self.assertEqual(leads, [])


if __name__ == "__main__":
    unittest.main()
