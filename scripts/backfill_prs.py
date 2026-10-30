import json
import os
import re
import sqlite3
import subprocess
import sys
sys.path.insert(0, os.path.abspath("."))
from scripts.autonomous_icu_pipeline import (
    attempt_automated_pull_request,
    extract_files_from_proposal,
    update_delivery_pr
)

def backfill():
    sys.stdout.reconfigure(encoding='utf-8')
    conn = sqlite3.connect('scratch/icu_pipeline.db')
    rows = conn.execute(
        "SELECT repo, issue_number, title, comment_id FROM deliveries WHERE pr_url IS NULL"
    ).fetchall()
    print(f"Inspecting {len(rows)} deliveries for PR backfill...")

    for repo, number, title, comment_id in rows:
        if not comment_id:
            continue

        # Fetch comment body from GitHub API
        cmd = ['gh', 'api', f'repos/{repo}/issues/comments/{comment_id}']
        res = subprocess.run(cmd, capture_output=True, encoding='utf-8')
        if res.returncode != 0:
            print(f"Skipping {repo}#{number}: comment {comment_id} unreachable")
            continue

        try:
            body = json.loads(res.stdout)['body']
        except Exception:
            continue

        files = extract_files_from_proposal(body)
        if not files:
            print(f"Skipping {repo}#{number}: no file blocks found")
            continue

        print(f"\n⚡ [BACKFILL TARGET FOUND] {repo}#{number} ({len(files)} files)")
        for p, code in files:
            print(f"   - {p} ({len(code)} bytes)")

        # Create PR
        pr_url = attempt_automated_pull_request(repo, number, title, body, live_mode=True)
        if pr_url:
            print(f"🎉 [BACKFILL SUCCESS] {repo}#{number} -> {pr_url}")
            update_delivery_pr(repo, number, pr_url)
        else:
            print(f"❌ [BACKFILL FAILED] {repo}#{number}")

if __name__ == '__main__':
    backfill()
