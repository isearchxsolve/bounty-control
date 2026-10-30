import os
import re

# Read TokenHarbor router
with open("scripts/tokenharbor_router.py", "r", encoding="utf-8") as f:
    th_code = f.read().replace("from __future__ import annotations", "# from __future__ import annotations")

# Read autonomous_icu_pipeline.py
with open("scripts/autonomous_icu_pipeline.py", "r", encoding="utf-8") as f:
    icu_code = f.read()

# Extract run_cmd
run_cmd_match = re.search(r"(def run_cmd\(.*?\n)(?=def get_author_profile)", icu_code, re.DOTALL)
assert run_cmd_match, "run_cmd not found"
run_cmd_code = run_cmd_match.group(1)

# Extract execution block: from sanitize_prompt_input to attempt_automated_pull_request end
exec_start = icu_code.find("def sanitize_prompt_input(text):")
exec_end = icu_code.find("def has_existing_open_pr(repo, number):")
assert exec_start != -1 and exec_end != -1, "exec block not found"
exec_code = icu_code[exec_start:exec_end]

# Build worker.py
worker_parts = [
    '''#!/usr/bin/env python3
from __future__ import annotations
# ==============================================================================
# KAGGLE 5-ENGINE DISTRIBUTED EXECUTION WORKER
# Direct Partition of autonomous_icu_pipeline.py (Part 2: Cloud Execution)
# The Supreme Edict: Zero Disavowal & Pixel-Perfect Craftsmanship
# ==============================================================================
import os
import sys
import json
import time
import re
import shutil
import hashlib
import tempfile
import urllib.request
import urllib.error
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any

# Enforce UTF-8 line buffering
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

DOOR = "https://omniroute-relay.omniroute-fleet-kd.workers.dev"
DOOR_TOKEN = "GOLD24"
ENGINE_ID = os.environ.get("ENGINE_ID", "kaggle-engine-unknown")

# Cloud sandbox and paths
SANDBOX_DIR = "/tmp/sandbox"
PACKET_DIR = "/tmp/candidate_packets"
DB_FILE = "/tmp/icu_pipeline.db"
CSV_FILE = "/tmp/icu_desperation_ledger.csv"
CLIENT_CONTACT_EMAIL = "isearch.xsolve@gmail.com"
DEEPSEEK_FLASH_MODEL = "deepseek-v4.1-flash:free"

os.makedirs(SANDBOX_DIR, exist_ok=True)
os.makedirs(PACKET_DIR, exist_ok=True)

# Database dummy/local logging stubs for Kaggle sandbox
def mark_issue_blocked_baseline(repo, number, reason):
    print(f"  [BLOCKED BASELINE] {repo}#{number}: {reason[:200]}", flush=True)

def update_delivery_pr(repo, number, pr_url):
    print(f"  [PR RECORDED] {repo}#{number} -> {pr_url}", flush=True)
''',

    # Embedded TokenHarbor Router
    "\n# ==============================================================================\n"
    "# EMBEDDED TOKENHARBOR ROUTER (17 ROTATING KEYS)\n"
    "# ==============================================================================\n"
    + th_code,

    # run_cmd
    "\n# ==============================================================================\n"
    "# SUBPROCESS EXECUTION ENGINE\n"
    "# ==============================================================================\n"
    + run_cmd_code,

    # Original execution block from autonomous_icu_pipeline.py
    "\n# ==============================================================================\n"
    "# MULTI-TURN ITERATIVE VERIFICATION & PR ENGINE (ORIGINAL ICU PIPELINE LOGIC)\n"
    "# ==============================================================================\n"
    + exec_code,

    # Kaggle worker loop & door communications
    '''
# ==============================================================================
# KAGGLE ENGINE WORKER LOOP & RECEIPT VERIFICATION
# ==============================================================================

def setup_kaggle_env():
    global SANDBOX_DIR, PACKET_DIR
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    os.makedirs(PACKET_DIR, exist_ok=True)

    # 1. Install or locate gh CLI
    if not shutil.which("gh"):
        gh_tar = "/tmp/gh.tar.gz"
        gh_dir = "/tmp/gh_install"
        try:
            print("[Init] Downloading portable GitHub CLI for Linux...", flush=True)
            urllib.request.urlretrieve("https://github.com/cli/cli/releases/download/v2.42.1/gh_2.42.1_linux_amd64.tar.gz", gh_tar)
            os.makedirs(gh_dir, exist_ok=True)
            subprocess.run(["tar", "-xzf", gh_tar, "-C", gh_dir, "--strip-components=1"], check=True)
            bin_dir = os.path.join(gh_dir, "bin")
            os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
            print(f"[Init] GitHub CLI installed at {bin_dir}", flush=True)
        except Exception as e:
            print(f"[Init] gh download error: {e}. Trying apt-get...", flush=True)
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "gh"], check=False)

    # 2. Configure git identity
    subprocess.run(["git", "config", "--global", "user.name", "isearchxsolve"], check=False)
    subprocess.run(["git", "config", "--global", "user.email", "isearch.xsolve@gmail.com"], check=False)

def get_worker_github_token() -> str:
    """Read the worker-local secret; task orders never contain credentials."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        from kaggle_secrets import UserSecretsClient
        secrets = UserSecretsClient()
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            value = (secrets.get_secret(name) or "").strip()
            if value:
                return value
    except Exception:
        pass
    return ""

def configure_task_github_auth() -> bool:
    token = get_worker_github_token()
    if not token:
        print(f"[{ENGINE_ID}] [FAIL-CLOSED] No worker-local GitHub secret is available.", flush=True)
        return False
    os.environ["GH_TOKEN"] = token
    os.environ["GITHUB_TOKEN"] = token
    # gh configures Git's credential helper without putting a token into a
    # command line, a task payload, or a persistent URL rewrite.
    return subprocess.run(["gh", "auth", "setup-git"], check=False).returncode == 0

def door_say(text: str, body: str = "BOUNTY_RESULT"):
    try:
        data = json.dumps({"body": body, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{DOOR}/say?body={body}&token={DOOR_TOKEN}",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "kaggle-engine"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[{ENGINE_ID}] door_say error: {e}", flush=True)
        return False

def fetch_tasks(limit: int = 10) -> List[dict]:
    try:
        url = f"{DOOR}/say?body=BOUNTY_TASK&token={DOOR_TOKEN}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "kaggle-engine"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            orders = data.get("orders", [])
            tasks = []
            for o in orders:
                try:
                    tasks.append(json.loads(o.get("text", "{}")))
                except Exception:
                    pass
            return tasks
    except Exception as e:
        print(f"[{ENGINE_ID}] fetch_tasks error: {e}", flush=True)
        return []

def deliver_pr_receipt(repo: str, number: int, pr_url: str, proposal: str, title: str, author: str, corridor_info: str, reason: str) -> bool:
    print(f"Delivering authoritative assessment to GitHub issue referencing verified PR {pr_url}...", flush=True)
    comment_payload = f"{proposal}\\n\\n---\\n**Verified Pull Request**: {pr_url}"
    post_cmd = ["gh", "api", f"repos/{repo}/issues/{number}/comments", "-X", "POST", "-f", f"body={comment_payload}"]
    out, err, code = run_cmd(post_cmd, timeout=30, retries=1)
    if code == 0 and out:
        try:
            resp_data = json.loads(out)
            comment_id = str(resp_data.get("id", ""))
            receipt_url = resp_data.get("html_url", "")
            server_body = resp_data.get("body", "")

            local_digest = hashlib.sha256(comment_payload.encode("utf-8")).hexdigest()
            server_digest = hashlib.sha256(server_body.encode("utf-8")).hexdigest()

            if local_digest == server_digest:
                print(f"✅ [CRYPTOGRAPHIC RECEIPT CONFIRMED] Comment ID: {comment_id} | PR: {pr_url} | SHA: {local_digest[:16]}", flush=True)
                return True
            else:
                print(f"⚠️ SHA digest mismatch between sent and server body.", flush=True)
                return False
        except Exception as e:
            print(f"Receipt parsing error: {e}", flush=True)
            return False
    else:
        print(f"Failed posting comment: {err or out}", flush=True)
        return False

def run_worker_loop():
    setup_kaggle_env()
    print("=" * 70, flush=True)
    print(f"⚡ KAGGLE 5-ENGINE DISTRIBUTED WORKER INITIALIZED", flush=True)
    print(f"Engine ID: {ENGINE_ID}", flush=True)
    print(f"Permanent Door: {DOOR}", flush=True)
    print("=" * 70, flush=True)

    door_say(f"ONLINE {ENGINE_ID} ready for uncontested bounties", body="ENGINE_REGISTRATION")

    processed_tasks = set()

    while True:
        try:
            tasks = fetch_tasks(limit=10)
            if not tasks:
                time.sleep(15)
                continue

            for task in tasks:
                task_id = task.get("task_id", "")
                repo = task.get("repo", "")
                number = task.get("issue_number")
                title = task.get("title", "")
                body = task.get("body", "")
                author = task.get("author", "")
                author_comments = task.get("author_comments", [])
                corridor_info = task.get("corridor_info", "")
                reason = task.get("reason", "")

                if not task_id or not repo or not number:
                    continue
                if task_id in processed_tasks:
                    continue

                processed_tasks.add(task_id)
                print(f"\\n⚡ [{ENGINE_ID}] CLAIMING TASK: {task_id} ({repo}#{number})", flush=True)
                door_say(f"CLAIMED {task_id} by {ENGINE_ID}", body="BOUNTY_CLAIM")

                if not configure_task_github_auth():
                    door_say(f"FAILED {ENGINE_ID} lacks a worker-local GitHub secret for {repo}#{number}", body="BOUNTY_RESULT")
                    continue

                # The authoritative issue assessment belongs in the execution
                # half of the partition, so the laptop remains a dispatcher.
                proposal = generate_grounded_proposal(repo, title, body, author, author_comments, turn=1)
                if not proposal:
                    door_say(f"FAILED {ENGINE_ID} DeepSeek generation failed closed for {repo}#{number}", body="BOUNTY_RESULT")
                    continue
                proposal_safe, proposal_message = sanitize_and_validate_payload(proposal)
                if not proposal_safe:
                    door_say(f"FAILED {ENGINE_ID} assessment safety gate: {proposal_message[:120]} for {repo}#{number}", body="BOUNTY_RESULT")
                    continue

                # Execute original Multi-Turn Iterative Verification Engine
                print(f"[{ENGINE_ID}] Executing Multi-Turn Iterative Verification Engine on {repo}#{number}...", flush=True)
                pr_url = attempt_automated_pull_request(repo, number, title, body, live_mode=True)

                if pr_url:
                    print(f"🎉 [{ENGINE_ID}] VERIFICATION GREEN! Pull Request Opened: {pr_url}", flush=True)
                    # Delivery is successful only when the authoritative issue
                    # comment round-trips with a matching SHA-256 receipt.
                    receipt_ok = deliver_pr_receipt(repo, number, pr_url, proposal, title, author, corridor_info, reason)
                    if receipt_ok:
                        door_say(f"SUCCESS {ENGINE_ID} opened verified PR and SHA-256 receipt: {pr_url} for {repo}#{number}", body="BOUNTY_RESULT")
                    else:
                        door_say(f"FAILED {ENGINE_ID} PR exists but authoritative SHA-256 issue receipt failed: {pr_url} for {repo}#{number}", body="BOUNTY_RESULT")
                else:
                    print(f"❌ [{ENGINE_ID}] Multi-turn verification did not produce green PR for {repo}#{number}", flush=True)
                    door_say(f"FAILED {ENGINE_ID} verification failed for {repo}#{number}", body="BOUNTY_RESULT")

            time.sleep(15)
        except Exception as e:
            print(f"[{ENGINE_ID}] Error in worker loop: {e}", flush=True)
            time.sleep(15)

if __name__ == "__main__":
    run_worker_loop()
'''
]

full_worker = "".join(worker_parts)
with open("scripts/kaggle_engine_worker.py", "w", encoding="utf-8") as f:
    f.write(full_worker)

print(f"SUCCESS: Generated scripts/kaggle_engine_worker.py ({len(full_worker.splitlines())} lines)")
