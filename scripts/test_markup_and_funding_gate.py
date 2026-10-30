#!/usr/bin/env python3
"""Comprehensive regression and boundary tests for the markup and funding gate hardening."""
import unittest
from decimal import Decimal

from autonomous_icu_pipeline import (
    strip_markup_and_code,
    parse_and_normalize_bounty,
    verify_genuine_icu_patient,
    is_direct_payer,
)
from fleet_recovery_policy import non_engineering_dispatch_reason


class TestMarkupAndFundingGate(unittest.TestCase):
    def test_strip_markup_and_code_removes_code_and_html(self):
        text = (
            "Here is the issue description:\n"
            "```python\n"
            "price = 5000\n"
            "bounty = '$500'\n"
            "```\n"
            "And an inline `bounty = $200` here.\n"
            "<div class=\"bounty-reward\">Mock Card</div>\n"
            "<!-- Comment with $9999 -->\n"
            "<script>const reward = 300;</script>\n"
            "<style>.price { color: green; }</style>\n"
            "Actual prose: We need a fix for this bug."
        )
        cleaned = strip_markup_and_code(text)
        self.assertNotIn("price = 5000", cleaned)
        self.assertNotIn("$500", cleaned)
        self.assertNotIn("$200", cleaned)
        self.assertNotIn("<div", cleaned)
        self.assertNotIn("</div>", cleaned)
        self.assertNotIn("$9999", cleaned)
        self.assertNotIn("const reward", cleaned)
        self.assertNotIn(".price", cleaned)
        self.assertIn("Mock Card", cleaned)
        self.assertIn("Actual prose: We need a fix for this bug.", cleaned)

    def test_parse_and_normalize_bounty_ignores_embedded_code_mock_amounts(self):
        code_only_text = (
            "Check this prototype code:\n"
            "```html\n"
            "<td>Bounty: $1000</td>\n"
            "```\n"
            "Fix the CSS styling."
        )
        has_amt, in_bounds, raw, val, reason = parse_and_normalize_bounty(code_only_text)
        self.assertFalse(has_amt)
        self.assertEqual(val, Decimal("0.00"))

    def test_parse_and_normalize_bounty_extracts_authentic_prose_amounts(self):
        prose_text = "We are offering an official $250 reward for this fix."
        has_amt, in_bounds, raw, val, reason = parse_and_normalize_bounty(prose_text)
        self.assertTrue(has_amt)
        self.assertTrue(in_bounds)
        self.assertEqual(raw, "$250")
        self.assertEqual(val, Decimal("250.00"))

    def test_non_engineering_dispatch_excludes_raw_html_dumps(self):
        html_task = {
            "title": "fronted isue",
            "body": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<title>Mock</title>\n</head>\n<body><div>Mock UI</div></body></html>",
            "repo": "user/repo",
        }
        reason = non_engineering_dispatch_reason(html_task)
        self.assertIn("raw HTML source code dump", reason)

    def test_non_engineering_dispatch_allows_standard_engineering_issues(self):
        normal_task = {
            "title": "Fix memory leak in websocket server",
            "body": "When 1000 clients connect, memory increases monotonically. Need fix.",
            "repo": "org/gateway",
        }
        reason = non_engineering_dispatch_reason(normal_task)
        self.assertEqual(reason, "")

    def test_raw_html_false_positive_rejected_by_icu_gate(self):
        # Simulated Anmol Kumar false positive
        mock_body = (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head><title>PatchBounty</title></head>\n"
            "<body><div class=\"reward\">₹5,000</div></body></html>"
        )
        res, reason = verify_genuine_icu_patient(
            title="fronted isue",
            body=mock_body,
            author_comments=[],
            labels=[],
            repo="author/repo",
            author_assoc="OWNER",
            author="author",
            live_delivery_mode=True,
        )
        self.assertFalse(res)
        self.assertIn("raw HTML source code dump", reason)

    def test_maintainer_explicit_offer_accepted(self):
        res, reason = verify_genuine_icu_patient(
            title="Repair concurrent executor deadlock",
            body="We will pay $150 for the executor fix.",
            author_comments=[],
            labels=[],
            repo="unit/runtime",
            author_assoc="MEMBER",
            author="maintainer",
            live_delivery_mode=True,
        )
        self.assertTrue(res)
        self.assertIn("Verified ICU client", reason)
        self.assertIn("$150", reason)

    def test_tier_bounty_title_accepted(self):
        res, reason = verify_genuine_icu_patient(
            title="[BOUNTY] Medium: Non-atomic state transitions in ComputeStorage",
            body="Bug in state sync across column families.",
            author_comments=[],
            labels=[{"name": "bounty"}],
            repo="paraloom-labs/paraloom-core",
            author_assoc="OWNER",
            author="paraloom-labs",
            live_delivery_mode=True,
        )
        self.assertTrue(res)
        self.assertIn("Verified ICU client", reason)
        self.assertIn("Tier Medium", reason)

    def test_platform_attested_bounty_accepted(self):
        res, reason = verify_genuine_icu_patient(
            title="Fix async event dispatch",
            body="Bounty funded via https://algora.io/bounties/abc ($200 reward).",
            author_comments=[],
            labels=[],
            repo="org/event-hub",
            author_assoc="NONE",
            author="user1",
            live_delivery_mode=True,
        )
        self.assertTrue(res)
        self.assertIn("Platform-attested bounty", reason)

    def test_bare_maintainer_issue_without_offer_rejected(self):
        # Maintainer discusses pricing feature/number but makes no offer
        res, reason = verify_genuine_icu_patient(
            title="Fix checkout calculation",
            body="When user adds $50 item to cart, tax calculates incorrectly.",
            author_comments=[],
            labels=[],
            repo="org/shop",
            author_assoc="OWNER",
            author="org",
            live_delivery_mode=True,
        )
        self.assertFalse(res)
        self.assertIn("no qualifying payer authority or bounty attestation", reason)


if __name__ == "__main__":
    unittest.main()
