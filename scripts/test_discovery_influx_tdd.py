"""
Test-Driven Development (TDD) Suite for Real Fleet Discovery Influx.
Strictly verifies that the autonomous discovery pipeline:
1. Unrolls aggregator/scraper mirrors to real upstream repository issues.
2. Reliably fetches platform bounty comments (Algora, Polar, Opire) regardless of title text.
3. Formulates high-yield platform and syntax-valid GitHub queries.
4. Produces a measurable influx of real, qualified, uncontested engineering bounties.
"""
from __future__ import annotations

import unittest
import sys
import os
import json
import re
from decimal import Decimal

# Ensure project root is in import path
sys.path.insert(0, r"D:\anonym")
sys.path.insert(0, r"D:\anonym\scripts")

from scripts.autonomous_icu_pipeline import (
    get_issue_fast,
    verify_genuine_icu_patient,
    parse_and_normalize_bounty,
    search_issues,
    has_existing_open_pr,
)


class TestDiscoveryInfluxTDD(unittest.TestCase):

    def test_01_aggregator_source_unrolling(self):
        """Test extraction of real upstream issue URLs from aggregator bodies."""
        from scripts.autonomous_icu_pipeline import extract_upstream_issue_from_aggregator

        # Sample from WholeTroutMedia / open-source-bounties
        wtm_body = """
        ## Sealed Bounty Verification Summary (`starlette-649`)
        - **Upstream Issue**: Kludex/starlette#649 ([View Thread](https://github.com/Kludex/starlette/issues/649))
        - **Difficulty Tier**: `Hard`
        - **Funding / Platform**: Polar.sh / OSS Funded
        """
        ref = extract_upstream_issue_from_aggregator(wtm_body)
        self.assertEqual(ref, ("Kludex/starlette", 649))

        # Sample from bounty-plaza / bounty-bot
        plaza_body = """
        ### 赏金平台 / Platform
        GitHub
        ### 原始链接 / Source URL
        https://github.com/astral-sh/uv/issues/9999
        ### 真实赏金（USD）/ Real Reward
        $150
        """
        ref2 = extract_upstream_issue_from_aggregator(plaza_body)
        self.assertEqual(ref2, ("astral-sh/uv", 9999))

        # Negative test: circular link pointing to another aggregator should be rejected
        circular_body = """
        Source URL: https://github.com/alfrexo95/bounty-bot/issues/28
        """
        ref3 = extract_upstream_issue_from_aggregator(circular_body)
        self.assertIsNone(ref3)

    def test_02_get_issue_fast_fetches_platform_comments_unconditionally(self):
        """Test that get_issue_fast fetches comments when commenter:algora-pbc or platform bot is involved."""
        # Test on an issue known to have algora-pbc bounty comment
        # seveibar/pgstrap#2 has an active $30 bounty comment from algora-pbc
        data = get_issue_fast("seveibar/pgstrap", 2)
        self.assertIsNotNone(data, "pgstrap#2 must be reachable")
        comments = data.get("author_comments", [])
        self.assertGreater(len(comments), 0, "Must fetch algora-pbc comments even if title/body lacks bounty tokens")
        has_algora_bounty = any("algora" in c.lower() or "$30" in c for c in comments)
        self.assertTrue(has_algora_bounty, "Should contain algora-pbc bounty offer comment")

    def test_03_query_battery_syntax_integrity(self):
        """Test that all dynamic discovery queries are syntax-valid for GitHub Search API."""
        from scripts.autonomous_icu_pipeline import DYNAMIC_DISCOVERY_QUERIES

        self.assertGreater(len(DYNAMIC_DISCOVERY_QUERIES), 10)
        # Ensure direct platform queries exist
        self.assertTrue(any("algora-pbc" in q for q in DYNAMIC_DISCOVERY_QUERIES), "Must include commenter:algora-pbc")
        self.assertTrue(any("console.algora.io" in q for q in DYNAMIC_DISCOVERY_QUERIES), "Must include console.algora.io")
        # Ensure no invalid unescaped '$' searches that fail GitHub API
        for q in DYNAMIC_DISCOVERY_QUERIES:
            self.assertNotEqual(q, 'bounty "$"', "Bare '$' query causes 0 results on GitHub")

    def test_04_measure_live_influx_rate(self):
        """Live Influx Test: Run top high-yield discovery queries and measure qualified candidates."""
        from scripts.autonomous_icu_pipeline import search_issues

        # Test against the top 3 high-yield platform queries
        platform_queries = [
            'commenter:algora-pbc',
            '"console.algora.io"',
            'bounty in:title',
        ]
        
        discovered_tasks = []
        for q in platform_queries:
            items = search_issues(q, limit=15)
            self.assertIsInstance(items, list)
            for it in items:
                repo = it.get("repository", {}).get("nameWithOwner")
                num = it.get("number")
                if repo and num:
                    discovered_tasks.append((repo, num, it.get("title", "")))

        print(f"\n[TDD INFLUX METRIC] Discovered {len(discovered_tasks)} candidate items across platform queries.")
        self.assertGreater(len(discovered_tasks), 0, "Platform discovery must produce non-zero candidates")


if __name__ == "__main__":
    unittest.main()
