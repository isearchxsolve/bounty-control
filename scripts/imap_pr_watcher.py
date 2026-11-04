#!/usr/bin/env python3
"""IMAP Email Wire Watcher for GitHub PRs, Reviews, and CI Runs.

Monitors real-time incoming push notifications from notifications@github.com
via Gmail IMAP using local vault credentials (D:\\anonym\\vault\\gmail_apppw.txt).
Captures failed PR runs, maintainer review comments, approvals, and issue closures.
"""

import email
import email.message
from email.header import decode_header, make_header
import imaplib
import json
import os
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT_PW_FILE = Path(r"D:\anonym\vault\gmail_apppw.txt")
DEFAULT_USER = "isearch.xsolve@gmail.com"
DEFAULT_HOST = "imap.gmail.com"
DEFAULT_PORT = 993


def decode_str(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def extract_text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""


def fetch_recent_pr_events(limit: int = 15) -> List[Dict]:
    """Fetch and parse recent PR reviews, comments, and CI failure emails."""
    if not VAULT_PW_FILE.exists():
        return []
    try:
        pw = VAULT_PW_FILE.read_text(encoding="utf-8").strip().replace(" ", "")
    except Exception:
        return []
    if not pw:
        return []

    events = []
    try:
        M = imaplib.IMAP4_SSL(DEFAULT_HOST, DEFAULT_PORT, timeout=20)
        M.login(DEFAULT_USER, pw)
        typ, _ = M.select("INBOX", readonly=True)
        if typ != "OK":
            return []

        # Search for github notification emails
        typ, data = M.search(None, '(FROM "notifications@github.com")')
        if typ != "OK" or not data[0]:
            M.logout()
            return []

        msg_ids = data[0].split()
        recent_ids = msg_ids[-limit:]

        for mid in reversed(recent_ids):
            typ, fetched = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not fetched:
                continue
            for item in fetched:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                msg = email.message_from_bytes(item[1])
                subj = re.sub(r"\s+", " ", decode_str(msg.get("Subject"))).strip()
                date_str = decode_str(msg.get("Date"))
                from_str = decode_str(msg.get("From"))
                body = extract_text_body(msg).strip()

                # Determine event category
                category = "NOTIFICATION"
                if "PR run failed" in subj or "Run failed" in subj:
                    category = "CI_FAILURE"
                elif "approved these changes" in body or "Approved" in subj:
                    category = "APPROVED"
                elif "requested changes" in body or "Changes requested" in subj:
                    category = "CHANGES_REQUESTED"
                elif "left a comment" in body or "commented" in body:
                    category = "COMMENT"
                elif "Closed #" in body or "closed this" in body:
                    category = "CLOSED"
                elif "Merged #" in body or "merged this" in body:
                    category = "MERGED"

                # Extract repository and PR/Issue number
                repo_match = re.search(r"\[([^\]]+/[^\]]+)\]", subj)
                repo = repo_match.group(1) if repo_match else None

                pr_match = re.search(r"(?:PR|fix:)\s*#(\d+)", subj, re.I) or re.search(r"#(\d+)", subj)
                number = pr_match.group(1) if pr_match else None

                events.append({
                    "category": category,
                    "repo": repo,
                    "number": number,
                    "subject": subj,
                    "from": from_str,
                    "date": date_str,
                    "body_snippet": body[:500] if body else ""
                })

        M.logout()
    except Exception as exc:
        print(f"[IMAP] Notice: {type(exc).__name__}: {exc}", file=sys.stderr)

    return events


if __name__ == "__main__":
    events = fetch_recent_pr_events(limit=8)
    print(json.dumps(events, indent=2))
