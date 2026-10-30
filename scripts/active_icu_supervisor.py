import os
import sys
import time
import json
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

BASE_DIR = r"D:\anonym"
SCRATCH_DIR = os.path.join(BASE_DIR, "scratch")
ICU_DB = os.path.join(SCRATCH_DIR, "icu_pipeline.db")
EMAIL_DB = os.path.join(SCRATCH_DIR, "email_pipeline.db")
LOG_DIR = os.path.join(SCRATCH_DIR, "supervisor_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Add scripts to path for router import
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
try:
    from tokenharbor_router import get_router_status
except Exception:
    get_router_status = lambda: {}


def get_latest_deliveries(limit=5):
    if not os.path.exists(ICU_DB):
        return []
    try:
        with sqlite3.connect(ICU_DB, timeout=10) as con:
            cur = con.cursor()
            rows = cur.execute("""
                SELECT repo, issue_number, status, claimed_at, delivered_at, pr_url, reason
                FROM deliveries
                ORDER BY rowid DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [
                {
                    "repo": r[0],
                    "issue": r[1],
                    "status": r[2],
                    "claimed_at": r[3],
                    "delivered_at": r[4],
                    "pr_url": r[5],
                    "reason": r[6]
                }
                for r in rows
            ]
    except Exception as e:
        return []


def get_latest_email_receipts(limit=5):
    if not os.path.exists(EMAIL_DB):
        return []
    try:
        with sqlite3.connect(EMAIL_DB, timeout=10) as con:
            cur = con.cursor()
            rows = cur.execute("""
                SELECT msg_uid, from_addr, subject, date_str, category, actionable, status, created_at
                FROM email_events
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [
                {
                    "uid": r[0],
                    "from": r[1],
                    "subject": r[2],
                    "date": r[3],
                    "category": r[4],
                    "actionable": bool(r[5]),
                    "status": r[6],
                    "created_at": r[7]
                }
                for r in rows
            ]
    except Exception as e:
        return []


def get_open_pr_reviews():
    try:
        cmd = ["gh", "search", "prs", "--author", "isearchxsolve", "--state", "open", "--json", "repository,number,title,url,createdAt"]
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        if proc.returncode != 0 or not proc.stdout:
            return []
        prs = json.loads(proc.stdout)
        results = []
        for p in prs:
            repo_name = p.get("repository", {}).get("nameWithOwner")
            pr_num = p.get("number")
            if not repo_name or not pr_num:
                continue
            # Query detailed status & checks
            detail_cmd = ["gh", "pr", "view", str(pr_num), "--repo", repo_name, "--json", "state,title,url,statusCheckRollup,latestReviews,comments"]
            d_proc = subprocess.run(detail_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
            if d_proc.returncode == 0 and d_proc.stdout:
                detail = json.loads(d_proc.stdout)
                checks = detail.get("statusCheckRollup", []) or []
                failing_checks = [c.get("name") for c in checks if c.get("conclusion") == "FAILURE"]
                passing_checks = [c.get("name") for c in checks if c.get("conclusion") == "SUCCESS"]
                pending_checks = [c.get("name") for c in checks if c.get("status") in ["IN_PROGRESS", "QUEUED"]]
                reviews = detail.get("latestReviews", []) or []
                comments = detail.get("comments", []) or []
                results.append({
                    "repo": repo_name,
                    "number": pr_num,
                    "title": detail.get("title"),
                    "url": detail.get("url"),
                    "failing_checks": failing_checks,
                    "passing_checks_count": len(passing_checks),
                    "pending_checks_count": len(pending_checks),
                    "reviews_count": len(reviews),
                    "comments_count": len(comments),
                    "latest_comment": comments[-1].get("body", "")[:120] if comments else None
                })
        return results
    except Exception:
        return []


def run_supervision_cycle():
    now_ist = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")
    print("\n" + "=" * 70)
    print(f"📊 [ACTIVE SUPERVISION TICK] - {now_ist}")
    print("=" * 70)

    # 1. Router State
    router_status = get_router_status()
    if router_status:
        states = router_status.get("states", {})
        ready_cnt = states.get("READY", 0)
        cooldown_cnt = states.get("COOLDOWN", 0)
        disabled_cnt = states.get("DISABLED", 0)
        leased_cnt = states.get("LEASED", 0)
        total_cnt = router_status.get("total_keys", 0)
        print(f"🔑 [TOKEN HARBOR ROUTER] Total: {total_cnt} | READY: {ready_cnt} | LEASED: {leased_cnt} | COOLDOWN: {cooldown_cnt} | DISABLED: {disabled_cnt}")

    # 2. Open PR Reviews & CI Checks
    open_prs = get_open_pr_reviews()
    print(f"\n🚀 [OPEN PULL REQUESTS SUPERVISED] ({len(open_prs)} active PRs):")
    if not open_prs:
        print("   (No active open PRs currently registered under isearchxsolve)")
    else:
        for pr in open_prs:
            print(f"   • {pr['repo']}#{pr['number']}: '{pr['title']}'")
            print(f"     URL: {pr['url']}")
            print(f"     CI Status: {pr['passing_checks_count']} Passed | {len(pr['failing_checks'])} Failed | {pr['pending_checks_count']} Pending")
            if pr['failing_checks']:
                print(f"     ⚠️ Failing Checks: {', '.join(pr['failing_checks'])}")
            if pr['latest_comment']:
                print(f"     💬 Latest Comment: \"{pr['latest_comment']}...\"")

    # 3. Latest Deliveries & Pipeline State
    deliveries = get_latest_deliveries(limit=5)
    print(f"\n📦 [LATEST ICU DELIVERIES] (Recent {len(deliveries)}):")
    if not deliveries:
        print("   (No deliveries recorded yet)")
    else:
        for d in deliveries:
            time_str = d['delivered_at'] or d['claimed_at'] or "pending"
            pr_note = f" -> PR: {d['pr_url']}" if d['pr_url'] else ""
            print(f"   • [{time_str}] {d['repo']}#{d['issue']} | Status: {d['status']}{pr_note}")
            if d['reason']:
                print(f"     Reason: {d['reason'][:100]}")

    # 4. Email Inbound Receipts
    emails = get_latest_email_receipts(limit=5)
    print(f"\n📨 [LATEST EMAIL RECEIPTS] (Recent {len(emails)}):")
    if not emails:
        print("   (No email receipts recorded yet)")
    else:
        for e in emails:
            act_note = " [ACTIONABLE]" if e['actionable'] else ""
            print(f"   • [{e['date'] or e['created_at']}] From: {e['from']} | Category: {e['category']}{act_note}")
            print(f"     Subject: {e['subject']}")

    print("=" * 70 + "\n")


def main():
    print("\n" + "=" * 70)
    print("⚡ ACTIVE ICU PRODUCTION PIPELINE & RECEIPT SUPERVISOR")
    print("Standard: Active Deliveries, Email Receipts, and PR Reviews Monitored Live")
    print("======================================================================\n")

    # Launch pipeline daemon in child process
    cmd = [sys.executable, os.path.join(BASE_DIR, "scripts", "autonomous_icu_pipeline.py"), "--anytime", "--live"]
    log_file = os.path.join(LOG_DIR, "autonomous_pipeline_live.log")
    
    print(f"▶️ Starting Autonomous ICU Pipeline Daemon (--anytime --live)...")
    print(f"   Log output: {log_file}")
    
    with open(log_file, "a", encoding="utf-8") as out_handle:
        proc = subprocess.Popen(
            cmd,
            stdout=out_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=BASE_DIR
        )

    print(f"✅ Daemon running under PID {proc.pid}. Starting supervision ticker (sweep every 60s)...")

    try:
        while True:
            # Check if child process is still alive
            ret = proc.poll()
            if ret is not None:
                print(f"⚠️ [SUPERVISOR WARNING] Daemon process (PID {proc.pid}) exited with code {ret}. Restarting...")
                with open(log_file, "a", encoding="utf-8") as out_handle:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=out_handle,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        cwd=BASE_DIR
                    )
                print(f"✅ Daemon restarted under new PID {proc.pid}.")

            run_supervision_cycle()
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n[SUPERVISOR SHUTDOWN] Terminating child daemon process...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("✅ Daemon stopped cleanly.")


if __name__ == "__main__":
    main()
