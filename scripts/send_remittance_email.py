#!/usr/bin/env python3
"""Universal Automated Remittance Dispatcher for Merged Open Source Bounties.

Dispatches polite, standardized dual-rail remittance coordinates via Gmail SMTP
using local vault credentials (D:\\anonym\\vault\\gmail_apppw.txt) when
maintainer merge is detected.

Standing Architecture:
- Dual-Rail Standard:
    Rail 1: Instant Wise / IMPS Direct Bank Deposit (~15-30 min settlement)
    Rail 2: Native GitHub Sponsors Profile (0% fees, platform org balance)
- Guardrails:
    Fail-closed: Never dispatches unless PR is merged (or --force-send).
    Idempotent: Stores a per-(repo, PR) persistent receipt to prevent duplicate sends.
    Privacy: Bank details are only shared via private direct email, NEVER in public GitHub comments.
"""

import argparse
import json
from pathlib import Path
import smtplib
import ssl
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

VAULT_PW_FILE = Path(r"D:\anonym\vault\gmail_apppw.txt")
RECEIPTS_DIR = Path(r"D:\bc\.remittance_receipts")
DEFAULT_USER = "isearch.xsolve@gmail.com"
SENDER_NAME = "Kunal Das"

# Standing default recipient for Fyne PR #6637
DEFAULT_REPO = "fyne-io/fyne"
DEFAULT_PR = 6637
DEFAULT_RECIPIENT_EMAIL = "andy@fyne.io"
DEFAULT_RECIPIENT_NAME = "Andy Williams"

# Standard standing template across all open source bounties
def render_email_subject(repo: str, pr_number: int) -> str:
    return f"{repo} PR #{pr_number} Bounty Remittance Coordinates (Kunal Das / isearchxsolve)"


def render_email_body(maintainer_name: str, repo: str, pr_number: int) -> str:
    first_name = maintainer_name.split()[0] if maintainer_name else "there"
    return f"""Hi {first_name},

Thank you for merging PR #{pr_number} on {repo}!

If you prefer settling the bounty via Wise / direct transfer (which settles via domestic IMPS in ~15-30 mins), here are my coordinates:

Wise Registered Email: isearch.xsolve@gmail.com

Direct Bank Details:
Beneficiary Name: KUNAL DAS
Bank: UCO Bank
Account Number: 17700110071793
Account Type: Savings (SBA)
IFSC Code: UCBA0001770
Branch: Santoshpur - Kolkata (163 Santoshpur Avenue, Kolkata, WB 700075)

Alternatively, if you prefer the GitHub Sponsors rail, my profile is active at:
https://github.com/sponsors/isearchxsolve

Thank you again for maintaining such a fantastic project and for the thoughtful guidance throughout the review process!

Best regards,
Kunal Das (@isearchxsolve)
"""


def load_password() -> str:
    if not VAULT_PW_FILE.exists():
        raise FileNotFoundError(f"Vault password file not found: {VAULT_PW_FILE}")
    pw = VAULT_PW_FILE.read_text(encoding="utf-8").strip()
    if not pw:
        raise ValueError(f"Vault password file {VAULT_PW_FILE} is empty")
    return pw


def check_pr_merged(repo: str, pr_number: int) -> bool:
    try:
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", repo,
            "--json", "state,mergedAt,mergedBy"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        return bool(data.get("mergedAt"))
    except Exception as exc:
        print(f"Warning: Failed to query PR status for {repo}#{pr_number} via gh: {exc}", file=sys.stderr)
        return False


def get_receipt_path(repo: str, pr_number: int) -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = repo.replace("/", "__")
    return RECEIPTS_DIR / f"{slug}_pr_{pr_number}_sent.json"


def send_remittance(
    repo: str,
    pr_number: int,
    recipient_email: str,
    recipient_name: str,
    dry_run: bool = False
) -> bool:
    receipt_file = get_receipt_path(repo, pr_number)
    if receipt_file.exists():
        print(f"INFO: Remittance receipt already exists at {receipt_file}. Skipping duplicate send.")
        return True

    subject = render_email_subject(repo, pr_number)
    body = render_email_body(recipient_name, repo, pr_number)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, DEFAULT_USER))
    msg["To"] = formataddr((recipient_name, recipient_email))
    msg["Reply-To"] = DEFAULT_USER
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if dry_run:
        print("=== DRY RUN: UNIVERSAL EMAIL PREVIEW ===")
        print(f"From: {msg['From']}")
        print(f"To: {msg['To']}")
        print(f"Subject: {msg['Subject']}")
        print(f"Body:\n{body}")
        print("=== END DRY RUN ===")
        return True

    pw = load_password()
    context = ssl.create_default_context()
    print(f"Connecting to smtp.gmail.com:465 as {DEFAULT_USER}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(DEFAULT_USER, pw)
        server.send_message(msg)
    print(f"SUCCESS: Remittance email dispatched to {recipient_email} for {repo}#{pr_number}!")

    receipt = {
        "repo": repo,
        "pr_number": pr_number,
        "recipient": recipient_email,
        "sender": DEFAULT_USER,
        "subject": subject,
        "status": "SENT"
    }
    receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="Universal Remittance Dispatcher.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"Repo name (default: {DEFAULT_REPO})")
    parser.add_argument("--pr", type=int, default=DEFAULT_PR, help=f"PR number (default: {DEFAULT_PR})")
    parser.add_argument("--maintainer-email", default=DEFAULT_RECIPIENT_EMAIL, help=f"Recipient email (default: {DEFAULT_RECIPIENT_EMAIL})")
    parser.add_argument("--maintainer-name", default=DEFAULT_RECIPIENT_NAME, help=f"Recipient name (default: {DEFAULT_RECIPIENT_NAME})")
    parser.add_argument("--dry-run", action="store_true", help="Print draft without sending")
    parser.add_argument("--force-send", action="store_true", help="Send email regardless of merge state")
    parser.add_argument("--check-and-send", action="store_true", help="Check if PR is merged; send if true")
    args = parser.parse_args()

    if args.dry_run:
        send_remittance(args.repo, args.pr, args.maintainer_email, args.maintainer_name, dry_run=True)
        return 0

    if args.check_and_send:
        merged = check_pr_merged(args.repo, args.pr)
        if not merged:
            print(f"PR {args.repo}#{args.pr} is not yet merged. No email sent.")
            return 0
        print(f"PR {args.repo}#{args.pr} is MERGED! Proceeding with remittance dispatch...")
        send_remittance(args.repo, args.pr, args.maintainer_email, args.maintainer_name, dry_run=False)
        return 0

    if args.force_send:
        print(f"Force-sending remittance email for {args.repo}#{args.pr}...")
        send_remittance(args.repo, args.pr, args.maintainer_email, args.maintainer_name, dry_run=False)
        return 0

    # Default action: dry-run
    send_remittance(args.repo, args.pr, args.maintainer_email, args.maintainer_name, dry_run=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
