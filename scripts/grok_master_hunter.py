#!/usr/bin/env python3
"""
Grok Master Bounty Hunter 2026 - High Speed & High Influx
=========================================================
"""
import sys
import os
import re
import time
import json
import csv
import argparse
from datetime import datetime, timezone
from typing import Optional, List, Dict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

MIN_AMOUNT = 80
MAX_OPEN_PRS = 2
FRESH_HOURS = 72
ABANDONED_DAYS = 14
PER_PAGE = 30
OUTPUT_CSV = r"D:\anonym\scratch\bounty_candidates.csv"

console = Console(legacy_windows=False)

def get_gh_token():
    t = os.getenv("GITHUB_TOKEN") or os.getenv("GH_PAT") or os.getenv("GH_TOKEN")
    if t:
        return t
    try:
        import subprocess
        res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return None

GITHUB_TOKEN = get_gh_token()
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Optimized high-yield queries targeting real bounties
SEARCH_QUERIES = [
    # 1. Algora High-Ticket
    ('commenter:algora-pbc is:issue is:open "$"', "Algora"),
    ('commenter:algora-pbc is:issue is:open "bounty"', "Algora"),
    ('label:"💎 Bounty" is:issue is:open', "Algora/Label"),
    ('"/bounty $" is:issue is:open', "Algora/Command"),

    # 2. Opire
    ('opire.dev is:issue is:open', "Opire"),
    ('"/reward" is:issue is:open', "Opire"),

    # 3. BountyHub
    ('bountyhub is:issue is:open', "BountyHub"),
    ('bountyhub-bot is:issue is:open', "BountyHub"),

    # 4. IssueHunt
    ('issuehunt.io is:issue is:open', "IssueHunt"),
    ('issuehunt is:issue is:open', "IssueHunt"),

    # 5. Direct / Open Collective
    ('label:bounty "Open Collective" is:issue is:open', "OpenCollective"),
    ('label:bounty "$100" is:issue is:open', "DirectBounty"),
    ('label:bounty "$200" is:issue is:open', "DirectBounty"),
    ('label:bounty "$500" is:issue is:open', "DirectBounty"),
    ('"will pay" "$100" is:issue is:open', "DirectPay"),
    ('label:"💰 Bounty" is:issue is:open', "DirectBounty"),
]

def gh_get(url: str, params: dict = None) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
                sleep = max(5, reset - time.time())
                console.print(f"[yellow]Rate limit reached -> sleeping {sleep:.0f}s[/yellow]")
                time.sleep(sleep)
                continue
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    return {}

def extract_amount(text: str) -> Optional[int]:
    if not text:
        return None
    # Reject marketing ad-spend or non-bounty money mentions
    if re.search(r"\b(?:ad\s+spend|facebook\s+ad|interview\s+incentive|budget\s+estimate|willingness-to-pay)\b", text, re.I):
        return None
    matches = re.findall(r"(?:bounty|reward|funded|paying|award)?\s*[\$€]\s?(\d{2,5})", text, re.I)
    if not matches:
        matches = re.findall(r"\$\s?(\d{2,5})", text)
    if matches:
        return max(int(m) for m in matches)
    return None

def age_hours(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999.0

def count_open_prs(repo_full: str, issue_num: int) -> int:
    q = f"repo:{repo_full} is:pr is:open {issue_num} in:title,body"
    data = gh_get("https://api.github.com/search/issues", {"q": q, "per_page": 5})
    return data.get("total_count", 0)

def score(amount: int, open_prs: int, age_h: float, comments: int) -> float:
    s = 0.0
    if amount >= 500:
        s += 50
    elif amount >= 250:
        s += 40
    elif amount >= 100:
        s += 30
    elif amount >= MIN_AMOUNT:
        s += 20

    if open_prs == 0:
        s += 45
    elif open_prs == 1:
        s += 20
    elif open_prs == 2:
        s += 5
    else:
        s -= 50

    if age_h <= FRESH_HOURS:
        s += 25
    elif age_h >= ABANDONED_DAYS * 24:
        s += 15
    else:
        s += 5

    if comments >= 2:
        s += 5
    return s

def run_audit():
    console.print(Panel.fit(
        "[bold cyan]⚡ HIGH-INFLUX LIVE BOUNTY AUDIT & CANDIDATE INDEX (2026)[/bold cyan]\n"
        "Multi-Platform: Algora • Opire • BountyHub • IssueHunt • Direct/OpenCollective\n"
        f"Filters: Floor >= ${MIN_AMOUNT} USD | Open PRs <= {MAX_OPEN_PRS} | Anti-Phantom Moat Enforced",
        border_style="cyan"
    ))

    seen = set()
    candidates: List[Dict] = []
    total_scanned = 0

    for idx, (query, platform) in enumerate(SEARCH_QUERIES, 1):
        console.print(f"[bold][{idx}/{len(SEARCH_QUERIES)}] Query:[/bold] {query} ({platform})")
        data = gh_get(
            "https://api.github.com/search/issues",
            {"q": query, "sort": "created", "order": "desc", "per_page": PER_PAGE},
        )
        items = data.get("items", [])
        total_scanned += len(items)
        retained = 0

        for it in items:
            repo_url = it.get("repository_url", "")
            number = it.get("number")
            key = f"{repo_url}#{number}"
            if key in seen:
                continue
            seen.add(key)

            if it.get("pull_request") or it.get("state") != "open":
                continue

            repo_full = "/".join(repo_url.rstrip("/").split("/")[-2:])
            repo_lower = repo_full.lower()

            # Reject known spam farms, aggregators, or non-software repos
            if any(farm in repo_lower for farm in (
                "scibase-ai", "securebananalabs", "unitoneai", "bujiproject",
                "louis-os", "poyraz", "bounty-plaza", "devpool-directory", "mergeearn",
                "realworldproblems", "test-info"
            )):
                continue

            title = it.get("title", "")
            body = it.get("body", "") or ""
            full_text = f"{title}\n{body}"

            # Anti-phantom filter
            if re.search(r"\[(?:roadmap|rfc|proposal|design|spec|experiment)\]", title, re.I):
                continue
            if re.search(r"\b(?:ad\s+spend|facebook\s+ad|interview\s+incentive|willingness-to-pay|validation\s+plan)\b", full_text, re.I):
                continue

            # Amount check
            amount = extract_amount(full_text)
            if not amount or amount < MIN_AMOUNT:
                continue

            # Fast PR check
            open_prs = count_open_prs(repo_full, number)
            if open_prs > MAX_OPEN_PRS:
                continue

            age_h = age_hours(it.get("created_at", ""))
            sc = score(amount, open_prs, age_h, it.get("comments", 0))

            candidates.append({
                "score": round(sc, 1),
                "amount": amount,
                "open_prs": open_prs,
                "age_hours": round(age_h, 1),
                "repo": repo_full,
                "number": number,
                "title": title[:70],
                "platform": platform,
                "url": it.get("html_url", ""),
            })
            retained += 1
            time.sleep(0.3)

        console.print(f"  -> Raw: {len(items)} | Qualified: {retained}")
        time.sleep(1.0)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    table = Table(
        title=f"Verified High-Quality Bounty Influx ({len(candidates)} Passed All Gates)",
        box=box.SIMPLE_HEAVY,
    )
    table.add_column("Rank", justify="center", style="dim")
    table.add_column("Score", justify="right", style="bold cyan")
    table.add_column("Bounty ($)", justify="right", style="bold green")
    table.add_column("PRs", justify="center")
    table.add_column("Platform", style="magenta")
    table.add_column("Repository", style="yellow")
    table.add_column("Issue Title")
    table.add_column("Live Wire Link", style="blue")

    for rank, c in enumerate(candidates[:25], 1):
        table.add_row(
            str(rank),
            str(c["score"]),
            f"${c['amount']}",
            str(c["open_prs"]),
            c["platform"],
            c["repo"],
            c["title"],
            c["url"],
        )

    console.print()
    console.print(table)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        if candidates:
            writer = csv.DictWriter(f, fieldnames=candidates[0].keys())
            writer.writeheader()
            writer.writerows(candidates)
        else:
            f.write("repo,number,amount,open_prs,url\n")
    console.print(f"\n[bold green]✓ Live candidates ledger persisted to {OUTPUT_CSV}[/bold green]")
    return candidates

if __name__ == "__main__":
    run_audit()
