#!/usr/bin/env python3
"""Email IMAP Watcher & Lead Ingester.

Connects to Gmail via IMAP (using local vault credentials) and supplements with
GitHub Notifications API to extract genuine external bounty program announcements
and maintainer outreach, formatting them as unverified leads for the Entry Door
Cline Searcher to evaluate and decide.

Local credential path: D:\\anonym\\vault\\gmail_apppw.txt [NEVER EXPOSED OR COMMITTED].
"""
import email
from email.header import decode_header, make_header
import imaplib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT_PW_FILE = Path(r"D:\anonym\vault\gmail_apppw.txt")
DEFAULT_USER = "isearch.xsolve@gmail.com"
DEFAULT_HOST = "imap.gmail.com"
DEFAULT_PORT = 993
INBOX_LEADS_FILE = Path("scratch/inbox-leads.json")


def decode_str(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def fetch_imap_leads(
    user: str = DEFAULT_USER,
    pw_file: Path = VAULT_PW_FILE,
    window: int = 400
) -> List[dict]:
    """Fetch recent external repo/bounty notifications from Gmail via IMAP."""
    if not pw_file.exists():
        return []
    try:
        pw = pw_file.read_text(encoding="utf-8").strip().replace(" ", "")
    except Exception:
        return []
    if not pw:
        return []

    try:
        M = imaplib.IMAP4_SSL(DEFAULT_HOST, DEFAULT_PORT, timeout=30)
        M.login(user, pw)
        typ, _ = M.select('"INBOX"', readonly=True)
        if typ != "OK":
            return []
        
        # Search for messages mentioning bounty or dollars or github notifications
        typ, data = M.search(None, '(OR SUBJECT "bounty" SUBJECT "$")')
        if typ != "OK" or not data[0]:
            M.logout()
            return []
        
        ids = data[0].split()
        recent_ids = ids[-window:]
        if not recent_ids:
            M.logout()
            return []

        id_str = b",".join(recent_ids).decode("ascii")
        typ, fetched = M.fetch(id_str, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
        M.logout()
    except Exception as exc:
        print(f"[IMAP] Notice: IMAP fetch encountered {type(exc).__name__}: {exc}", file=sys.stderr)
        return []

    leads: List[dict] = []
    seen = set()
    # Match "[owner/repo] Issue Title (Issue #123)" or "[owner/repo] PR Title (PR #123)"
    gh_pattern = re.compile(r'\[([^\]]+/[^\]]+)\]\s*(.*?)(?:\s*\((?:Issue|PR)\s*#(\d+)\))?$', re.I)

    for item in fetched or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        try:
            msg = email.message_from_bytes(item[1])
            subj = decode_str(msg.get("Subject"))
            frm = decode_str(msg.get("From"))
            date = decode_str(msg.get("Date"))
        except Exception:
            continue

        # Filter out internal CI run failure noise
        if "isearchxsolve/bounty-control" in subj and "Run failed" in subj:
            continue

        m = gh_pattern.search(subj)
        if m:
            repo = m.group(1).strip()
            title = m.group(2).strip()
            num_str = m.group(3)
            if not num_str:
                # Look for #123 inside title
                num_match = re.search(r'#(\d+)', title)
                num = int(num_match.group(1)) if num_match else None
            else:
                num = int(num_str)

            if repo and num:
                key = (repo.lower(), num)
                if key in seen:
                    continue
                seen.add(key)
                leads.append({
                    "repo": repo,
                    "issue": num,
                    "title": title,
                    "email_subject": subj,
                    "email_from": frm,
                    "email_date": date,
                    "source": "gmail_imap",
                    "reason": "EMAIL_IMAP_NOTIFICATION_LEAD",
                    "url": f"https://github.com/{repo}/issues/{num}",
                })
    return leads


def fetch_gh_notification_leads() -> List[dict]:
    """Fetch issue leads from GitHub Notifications API as dual/fallback stream."""
    try:
        cmd = ["gh", "api", "notifications", "--cache", "30s"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
    except Exception:
        return []

    leads: List[dict] = []
    seen = set()
    for item in data or []:
        if not isinstance(item, dict):
            continue
        subj = item.get("subject", {})
        repo = item.get("repository", {}).get("full_name", "")
        url = subj.get("url", "")
        title = subj.get("title", "")
        if "issues" in url and repo:
            try:
                num = int(url.split("/")[-1])
            except ValueError:
                continue
            key = (repo.lower(), num)
            if key in seen:
                continue
            seen.add(key)
            leads.append({
                "repo": repo,
                "issue": num,
                "title": title,
                "source": "github_notifications_api",
                "reason": "GH_NOTIFICATION_API_LEAD",
                "url": f"https://github.com/{repo}/issues/{num}",
            })
    return leads


def collect_inbox_leads(output_path: Optional[Path] = None) -> List[dict]:
    """Collect unique leads from IMAP and GitHub Notifications feed."""
    imap_leads = fetch_imap_leads()
    gh_leads = fetch_gh_notification_leads()
    
    combined: List[dict] = []
    seen = set()
    for lead in imap_leads + gh_leads:
        key = (lead["repo"].lower(), lead["issue"])
        if key in seen:
            continue
        seen.add(key)
        combined.append(lead)

    out = output_path or INBOX_LEADS_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    return combined


if __name__ == "__main__":
    leads = collect_inbox_leads()
    print(f"Collected {len(leads)} genuine program/issue leads from email & notification streams:")
    for l in leads:
        print(f"  {l['repo']}#{l['issue']} -> {l['title'][:80]} [source={l['source']}]")
