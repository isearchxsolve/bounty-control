import subprocess
import json
import os
import sys
import time
import re
from datetime import datetime

# Enforce UTF-8 unbuffered output
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

LEDGER_FILE = r"D:\anonym\scratch\mass_attack_ledger.json"
CSV_FILE = r"D:\anonym\scratch\mass_attack_ledger.csv"

# Payment coordinates were removed from this engine on 2026-10-29. They were appended to
# every public issue comment, which is the opposite of what the target guides require:
# "Zero fluff, zero speculation, zero padding" (Silo Guide 3.3) and "small teams have less
# patience for noise" (Startup Guide 4). A bank account in a public thread reads as spam
# and repels the funded founder this pipeline exists to reach. Payment terms now go in a
# private channel, after the founder replies. See scripts/outreach_report.py.
PAYMENT_COORDINATES = ""
if PAYMENT_COORDINATES.strip():
    raise RuntimeError(
        "PAYMENT_COORDINATES must stay empty: payment terms belong in a private "
        "channel after the founder replies, never in a public issue comment."
    )

# Ensure scratch directory exists
os.makedirs(r"D:\anonym\scratch", exist_ok=True)

# Load existing ledger
if os.path.exists(LEDGER_FILE):
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    except Exception:
        ledger = {}
else:
    ledger = {}

# High-yield search queries focused strictly on mission-critical paid bounties
QUERIES = [
    'repo:paraloom-labs/paraloom-core state:open',
    'bounty solana state:open',
    'bounty rust state:open',
    'bounty DEX state:open',
    'bounty "liquidity" state:open',
    'bounty "gateway" state:open',
    'bounty "panic" state:open',
    'bounty "race condition" state:open',
    'bounty "deadlock" state:open',
    'bounty "memory leak" state:open',
    'bounty critical state:open',
    'repo:devpool-directory/devpool-directory state:open',
]

def run_cmd(cmd_list):
    res = subprocess.run(cmd_list, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.stdout.strip(), res.stderr.strip(), res.returncode

def fetch_issues(q):
    if q.startswith("repo:"):
        repo_name = q.split()[0].replace("repo:", "")
        cmd = ["gh", "issue", "list", "--repo", repo_name, "--state", "open", "--limit", "15", "--json", "number,title,labels,body"]
        out, err, code = run_cmd(cmd)
        if code != 0 or not out:
            return []
        try:
            items = json.loads(out)
            for it in items:
                it["repository"] = {"nameWithOwner": repo_name}
                it["url"] = f"https://github.com/{repo_name}/issues/{it.get('number')}"
            return items
        except Exception:
            return []
    else:
        cmd = ["gh", "search", "issues", q, "--sort", "updated", "--limit", "15", "--json", "number,title,repository,url,labels"]
        out, err, code = run_cmd(cmd)
        if code != 0 or not out:
            return []
        try:
            return json.loads(out)
        except Exception:
            return []

def get_issue_body(repo, number):
    cmd = ["gh", "issue", "view", str(number), "--repo", repo, "--json", "body,author,title,labels"]
    out, err, code = run_cmd(cmd)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def is_spam_or_bot_repo(repo_name, author_name):
    spam_indicators = ["bounty-plaza", "bounty-bot", "Trauma-Station", "github-actions", "opire", "claude-builders-bounty"]
    for s in spam_indicators:
        if s.lower() in repo_name.lower() or s.lower() in author_name.lower():
            return True
    return False

def has_explicit_bounty_or_payment(title, body, labels):
    """
    STRICT PAYMENT FILTER:
    Ensures that the issue explicitly offers payment / bounty / rewards.
    """
    text = (title + " " + (body or "")).lower()
    
    # Check labels
    for l in labels:
        lname = l.get("name", "").lower() if isinstance(l, dict) else str(l).lower()
        if "price:" in lname or "bounty" in lname or "reward" in lname:
            return True

    # Check explicit patterns in text
    payment_patterns = [
        r"\[bounty",
        r"\$bounty",
        r"bounty\s*:\s*\$",
        r"bounty\s*\$",
        r"\$\d+",
        r"\b\d+\s*usdc\b",
        r"\b\d+\s*usdt\b",
        r"\b\d+\s*usd\b",
        r"paid bounty",
        r"paid task",
        r"monetary bounty",
        r"bounty attached",
        r"devpool",
        r"reward available"
    ]
    for pattern in payment_patterns:
        if re.search(pattern, text):
            return True

    return False

def build_surgical_diagnosis(title, body, repo, evidence=None):
    """Build the comment body for an issue.

    2026-10-29: this function used to select one of five canned templates by keyword match
    and assert, in public, that we had reproduced the failure and verified a hotfix on a
    private branch with a 100% clean simulation. No such reproduction existed. That is
    manufactured evidence, and it is the fastest way to lose a technical founder who
    checks. The templates are gone.

    A report is now built only from evidence the caller actually holds. Without it, this
    raises, and fire_mass_attack skips the issue instead of posting an assertion.
    """
    if not evidence:
        raise ValueError(
            "refusing to build a report without evidence: the previous templates asserted "
            "a reproduction and a verified hotfix that had not been done. Supply real "
            "evidence (impact, affected, steps, proof, fix) or skip the issue."
        )
    from outreach_report import build_report
    return build_report(
        impact=evidence["impact"],
        affected=evidence["affected"],
        steps=evidence["steps"],
        proof=evidence["proof"],
        fix=evidence["fix"],
        detail=evidence.get("detail"),
        repo=repo,
    )

def fire_mass_attack():
    print(f"[{datetime.now().isoformat()}] MASS ATTACK ENGINE INITIALIZED (STRICT PAYMENT FILTER ACTIVE)")
    print(f"Targeting active ICU patients with explicit bounties and payment offers...")
    
    shots_fired = 0
    
    for q in QUERIES:
        print(f"\n==================================================")
        print(f"--- Scanning Cluster: {q} ---")
        issues = fetch_issues(q)
        print(f"Found {len(issues)} raw candidates.")
        
        for item in issues:
            number = item.get("number")
            repo = item.get("repository", {}).get("nameWithOwner")
            title = item.get("title", "")
            url = item.get("url", "")
            labels = item.get("labels", [])
            
            if not repo or not number:
                continue
                
            issue_id = f"{repo}#{number}"
            
            # Check if already processed
            if issue_id in ledger:
                print(f"[SKIP] {issue_id} already in ledger.")
                continue
                
            # Fetch full issue details to inspect body & author
            issue_data = get_issue_body(repo, number)
            if not issue_data:
                continue
                
            author = issue_data.get("author", {}).get("login", "")
            body = issue_data.get("body", "")
            labels = issue_data.get("labels", labels)
            
            # Filter spam / bots
            if is_spam_or_bot_repo(repo, author):
                print(f"[SKIP SPAM] {issue_id} is spam/bot.")
                ledger[issue_id] = {"status": "SKIPPED_SPAM", "timestamp": datetime.now().isoformat()}
                continue
                
            # STRICT PAYMENT FILTER
            if not has_explicit_bounty_or_payment(title, body, labels):
                print(f"[SKIP NO PAYMENT] {issue_id}: '{title[:50]}' does not offer payment.")
                ledger[issue_id] = {"status": "SKIPPED_NO_PAYMENT", "timestamp": datetime.now().isoformat()}
                continue
                
            # Generate the report. This raises unless real evidence is supplied, so an
            # issue we have not actually diagnosed is skipped, never asserted.
            try:
                diagnosis = build_surgical_diagnosis(title, body, repo)
            except ValueError as exc:
                print(f"[SKIP NO EVIDENCE] {issue_id}: {exc}")
                ledger[issue_id] = {"status": "SKIPPED_NO_EVIDENCE",
                                    "timestamp": datetime.now().isoformat()}
                with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                    json.dump(ledger, f, indent=2)
                continue
            
            print(f"\n🎯 [ICU TARGET LOCKED] {issue_id}")
            print(f"Title: '{title}' by @{author}")
            print(f"URL: {url}")
            print(f"Delivering Chief Neurosurgeon Strike with Multi-Rail Settlement...")
            
            # Post comment via gh cli
            comment_cmd = ["gh", "issue", "comment", str(number), "--repo", repo, "--body", diagnosis]
            out, err, code = run_cmd(comment_cmd)
            
            if code == 0:
                print(f"✅ [STRIKE DELIVERED] Successfully posted to {issue_id}!")
                ledger[issue_id] = {
                    "status": "STRIKE_DELIVERED",
                    "repo": repo,
                    "number": number,
                    "title": title,
                    "author": author,
                    "url": url,
                    "timestamp": datetime.now().isoformat()
                }
                shots_fired += 1
                
                # Append to CSV
                with open(CSV_FILE, "a", encoding="utf-8") as f:
                    f.write(f'"{datetime.now().isoformat()}","{repo}","{number}","{title.replace(chr(34), chr(39))}","{author}","{url}","STRIKE_DELIVERED"\n')
                    
                # Save ledger
                with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                    json.dump(ledger, f, indent=2)
                    
                # Rate limit hygiene (12 seconds)
                time.sleep(12)
            else:
                print(f"❌ [FAILED] Error posting to {issue_id}: {err}")
                ledger[issue_id] = {"status": "FAILED", "error": err, "timestamp": datetime.now().isoformat()}
                with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                    json.dump(ledger, f, indent=2)
                    
    print(f"\n[{datetime.now().isoformat()}] MASS ATTACK ENGINE CYCLE COMPLETE. Total Strikes Delivered: {shots_fired}")

if __name__ == "__main__":
    fire_mass_attack()
