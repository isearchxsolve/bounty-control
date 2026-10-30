#!/usr/bin/env python3
"""
Master Bounty Hunter 2026 (Enhanced)
====================================
Covers: Algora • Opire • BountyHub • IssueHunt • Direct funded issues

Features:
- Full platform coverage
- Realistic scoring (amount + competition + freshness/abandoned)
- Sniper mode (--sniper) – only last 36–48 hours
- Claim-comment helper for top results
- CSV export
- Rate-limit friendly

Usage:
  export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
  python master_bounty_hunter.py
  python master_bounty_hunter.py --sniper
  python master_bounty_hunter.py --sniper --show-claims
"""

import os
import sys
import re
import time
import csv
import argparse
from datetime import datetime, timezone
from typing import Optional, List, Dict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# ============================================================
# CONFIG
# ============================================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    try:
        import subprocess
        GITHUB_TOKEN = subprocess.check_output(["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        GITHUB_TOKEN = None

MIN_AMOUNT = 80
MAX_OPEN_PRS = 2
FRESH_HOURS = 48
ABANDONED_DAYS = 12
PER_PAGE = 35
OUTPUT_CSV = "bounty_candidates.csv"
MAX_DISPLAY = 30
# ============================================================

console = Console(legacy_windows=False)

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# All recommended platforms & signals
SEARCH_QUERIES = [
    # Algora
    'label:"💎 Bounty" is:issue is:open',
    '"/bounty $" is:issue is:open',
    'label:bounty "/bounty" is:issue is:open',

    # Opire
    '"opire.dev" is:issue is:open',
    '/reward is:issue is:open',

    # BountyHub
    '"bountyhub" is:issue is:open',
    '"bountyhub-bot" is:issue is:open',

    # IssueHunt
    '"issuehunt" is:issue is:open',
    '"issuehunt.io" is:issue is:open',

    # Direct / generic
    'label:bounty is:issue is:open "$"',
    'label:"💰 Bounty" is:issue is:open',
    '"funded" label:bounty is:issue is:open',
]


def gh_get(url: str, params: dict = None) -> dict:
    for _ in range(4):
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            sleep = max(5, reset - time.time())
            console.print(f"[yellow]Rate limited → sleeping {sleep:.0f}s[/yellow]")
            time.sleep(sleep)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GitHub API failed after retries")


def extract_amount(text: str) -> Optional[int]:
    if not text:
        return None
    matches = re.findall(r"(?:bounty|reward|funded)?\s*[\$€]\s?(\d{2,5})", text, re.I)
    if not matches:
        matches = re.findall(r"\$\s?(\d{2,5})", text)
    return max(int(m) for m in matches) if matches else None


def age_hours(iso: str) -> float:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def count_open_prs(repo_full: str, issue_num: int) -> int:
    q = f"repo:{repo_full} is:pr is:open {issue_num} in:title,body"
    try:
        data = gh_get("https://api.github.com/search/issues", {"q": q, "per_page": 5})
        return data.get("total_count", 0)
    except Exception:
        return 99


def score(item: dict, amount: Optional[int], open_prs: int, age_h: float) -> float:
    s = 0.0
    if amount is None:
        s += 8
    elif amount >= 400:
        s += 45
    elif amount >= 200:
        s += 35
    elif amount >= 100:
        s += 25
    elif amount >= MIN_AMOUNT:
        s += 15
    else:
        s -= 10

    if open_prs == 0:
        s += 40
    elif open_prs == 1:
        s += 22
    elif open_prs == 2:
        s += 8
    else:
        s -= 40

    if age_h <= FRESH_HOURS:
        s += 35
    elif age_h >= ABANDONED_DAYS * 24:
        s += 18
    else:
        s += 5

    if item.get("comments", 0) >= 2:
        s += 5
    return s


def make_claim_comment(platform_hint: str, issue_number: int) -> str:
    """Generate a polite, ready-to-paste claim comment."""
    platform_hint = (platform_hint or "").lower()
    if "opire" in platform_hint or "/reward" in platform_hint:
        return f"/try #{issue_number}\n\nI am starting work on this issue now. Will open a PR shortly."
    if "algora" in platform_hint or "💎" in platform_hint or "/bounty" in platform_hint:
        return f"I'm working on this bounty. Will submit a PR soon."
    if "bountyhub" in platform_hint:
        return f"Claiming this bounty. Starting work now."
    return f"Taking this issue. Will open a PR shortly. (Ref #{issue_number})"


def main():
    parser = argparse.ArgumentParser(description="Master Bounty Hunter 2026")
    parser.add_argument("--sniper", action="store_true",
                        help="Only show issues created in the last 36–48 hours")
    parser.add_argument("--show-claims", action="store_true",
                        help="Print ready-to-paste claim comments for top results")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]Master Bounty Hunter 2026 (Enhanced)[/bold cyan]\n"
        "Algora • Opire • BountyHub • IssueHunt • Direct\n"
        + ("[yellow]SNIPER MODE – last 48 hours only[/yellow]" if args.sniper else ""),
        border_style="cyan"
    ))

    if not GITHUB_TOKEN:
        console.print("[yellow]Warning: No GITHUB_TOKEN set. Rate limits will be very low.[/yellow]\n")

    seen = set()
    candidates: List[Dict] = []

    for i, query in enumerate(SEARCH_QUERIES, 1):
        console.print(f"[{i}/{len(SEARCH_QUERIES)}] {query}")
        try:
            data = gh_get(
                "https://api.github.com/search/issues",
                {"q": query, "sort": "created", "order": "desc", "per_page": PER_PAGE},
            )
        except Exception as e:
            console.print(f"[red]Query failed: {e}[/red]")
            continue

        for item in data.get("items", []):
            key = (item["repository_url"], item["number"])
            if key in seen:
                continue
            seen.add(key)

            if item.get("pull_request") or item["state"] != "open":
                continue

            full_text = f"{item['title']}\n{item.get('body') or ''}"
            amount = extract_amount(full_text)
            if amount is not None and amount < MIN_AMOUNT:
                continue

            age_h = age_hours(item["created_at"])
            if args.sniper and age_h > FRESH_HOURS:
                continue

            repo_full = "/".join(item["repository_url"].rstrip("/").split("/")[-2:])
            open_prs = count_open_prs(repo_full, item["number"])
            if open_prs > MAX_OPEN_PRS:
                continue

            sc = score(item, amount, open_prs, age_h)
            candidates.append({
                "score": round(sc, 1),
                "amount": amount or 0,
                "open_prs": open_prs,
                "age_hours": round(age_h, 1),
                "repo": repo_full,
                "number": item["number"],
                "title": item["title"][:75],
                "url": item["html_url"],
                "comments": item["comments"],
                "raw_title": item["title"],
                "platform_hint": query,
            })

        time.sleep(1.1)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Table
    table = Table(
        title=f"Top Bounty Candidates ({len(candidates)} passed filters)",
        box=box.SIMPLE_HEAVY,
    )
    table.add_column("Score", justify="right", style="bold cyan")
    table.add_column("$", justify="right")
    table.add_column("PRs", justify="right")
    table.add_column("Age(h)", justify="right")
    table.add_column("Repo", style="green")
    table.add_column("Title")
    table.add_column("Link", style="dim")

    for c in candidates[:MAX_DISPLAY]:
        table.add_row(
            str(c["score"]),
            str(c["amount"]) if c["amount"] else "?",
            str(c["open_prs"]),
            str(c["age_hours"]),
            c["repo"],
            c["title"],
            c["url"],
        )

    console.print()
    console.print(table)

    # Claim helper
    if args.show_claims and candidates:
        console.print("\n[bold]Ready-to-paste claim comments (top 8):[/bold]\n")
        for c in candidates[:8]:
            comment = make_claim_comment(c["platform_hint"], c["number"])
            console.print(Panel(
                f"[green]{c['repo']}#{c['number']}[/green]  (${c['amount'] or '?'})\n"
                f"{c['url']}\n\n"
                f"[white]{comment}[/white]",
                title=c["title"][:60],
                border_style="blue"
            ))

    # CSV
    if candidates:
        # remove helper fields before writing
        clean = [{k: v for k, v in c.items() if k not in ("raw_title", "platform_hint")} for c in candidates]
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=clean[0].keys())
            writer.writeheader()
            writer.writerows(clean)
        console.print(f"\n[green]✓ Saved full list → {OUTPUT_CSV}[/green]")

    console.print(Panel(
        f"[bold]Total after filters: {len(candidates)}[/bold]\n"
        "Start from the top. Only claim when you can work on it today.\n"
        "Prefer Score ≥ 70 + 0–1 open PRs.\n\n"
        "Examples:\n"
        "  python master_bounty_hunter.py --sniper\n"
        "  python master_bounty_hunter.py --sniper --show-claims",
        title="Next Action",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
