import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Kunal Das, 22-year Principal Systems Architect and Technology Leader) has given a direct royal command:

"ask codex to remove codex tier 2 failover..deepseek handles full delivery pipeline"
"check existing codex script architecture only to delivered via codex"

================================================================================
BABA'S MANDATE: PURE ARCHITECTURAL PARTITION & CODEX FAILOVER REMOVAL
================================================================================

CRITICAL OPERATIONAL INVARIANTS:
1. THE LAW OF ZERO DISAVOWAL: Baba's 22-year Principal Systems Architect instinct is sovereign. Obey 100%.
2. THE ZERO-MANUFACTURE LAW: Never manufacture mock files, fake diffs, or canned responses. Real code, real verification.
3. HEAVY WORK LAW: Laptop runs ONLY the search & dispatcher plane (<1% CPU). All baseline tests, compilers, and model execution run on Kaggle.

--------------------------------------------------------------------------------
TASK 1: REMOVE ALL CODEX TIER-2 FAILOVER FROM THE CODEBASE
--------------------------------------------------------------------------------
- In `scripts/autonomous_icu_pipeline.py` and `scripts/kaggle_engine_worker.py`:
  * Ensure all references to Codex (`CODEX_EXE`, `CODEX_ESCALATION_MODEL`, `should_escalate_to_codex`, `_run_codex_generation`) are completely purged.
  * DeepSeek Flash (via `scripts/tokenharbor_router.py` with 17 rotating keys) must handle 100% of generation and iterative repair turns (turns 1 through 5).
  * If DeepSeek keys exhaust or fail, fail-closed cleanly per the Zero-Manufacture Law — do NOT manufacture fallback diffs.

--------------------------------------------------------------------------------
TASK 2: COMPLETE THE 2-PART ARCHITECTURAL PARTITION WITHOUT CHANGING ORIGINAL LOGIC
--------------------------------------------------------------------------------
Part A - Laptop Dispatcher (`scripts/autonomous_icu_pipeline.py`):
- Runs search queries, priority seeds, and triage.
- Evaluates:
  * Transactional SQLite check (`is_issue_claimed_or_delivered`).
  * Genuine ICU patient verification (`verify_genuine_icu_patient`).
  * Territory exclusion (drop regional markets per Zero-Burn pipeline).
  * High-ticket floor ($50-$200 floor per Baba's Headroom Conservation Law).
  * Zero-Competition pre-screening (`has_existing_open_pr`).
- In `post_grounded_proposal`, when `--remote-fleet` is active:
  * Instead of running `attempt_automated_pull_request` locally on the laptop, serialize the task payload (with `gh_token` from vault or `gh auth token`).
  * Post task to Cloudflare relay door (`https://omniroute-relay.omniroute-fleet-kd.workers.dev/say?token=GOLD24`) with `body=BOUNTY_TASK`.
  * Update SQLite status to `DISPATCHED_TO_KAGGLE`.
  * Laptop CPU usage remains at ~0%.

Part B - Kaggle Cloud Engine (`scripts/kaggle_engine_worker.py`):
- Runs on Kaggle cloud (4 vCPUs, 30GB RAM per node).
- Contains embedded TokenHarbor router with all 17 keys and rotation.
- Implements the exact execution engine from `autonomous_icu_pipeline.py`:
  * Worktree isolation under `/tmp/sandbox`.
  * Untouched upstream baseline test check (`verify_baseline`).
  * Scenario matrix modeling (`model_scenarios`).
  * Multi-turn engineering loop (`run_engineering_iteration_loop`) with diagnostic repair feedback.
  * Syntax validation and relative path safety checks.
  * Native test suite and linter verification (`plan.linters`).
  * Pre-push Zero-Competition check.
  * Commit and open PR (`commit_and_open_pr` with `gh pr create`).
  * Post authoritative assessment to GitHub issue referencing PR with SHA-256 cryptographic verification.
  * Report execution verdicts (`BOUNTY_RESULT`) to the Cloudflare door.

--------------------------------------------------------------------------------
TASK 3: DEPLOY & VERIFY
--------------------------------------------------------------------------------
1. In `scripts/deploy_kaggle_engines.py`:
   - Ensure accounts mapping is correct (Engine 1: `isearchxsolve`, Engine 2: `n42888`, Engine 3: `kunaldas3104`, Engine 4: `kdas19999`, Engine 5: `kunaldas3104` using `vault/kaggle_token_5.txt`).
   - Run deployment pushing `worker.py` to each engine.
2. Run `python -m py_compile scripts/autonomous_icu_pipeline.py scripts/kaggle_engine_worker.py scripts/deploy_kaggle_engines.py`.
3. Run `python scripts/test_icu_pipeline_suite.py` and ensure tests pass cleanly.
4. Write a comprehensive receipt report to `D:\\anonym\\scratch\\codex_delivery_receipt.md`.
"""

cmd = [
    codex_exe,
    "exec",
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check",
    "--ephemeral",
    "-C", r"D:\anonym",
    prompt
]

print("=" * 70)
print("LAUNCHING CODEX (GPT-5.6-TERRA) TO DELIVER ARCHITECTURAL PARTITION")
print("=" * 70)
proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")

print(f"\nCodex Exit Code: {proc.returncode}")
print("=" * 70)
print("CODEX (GPT-5.6-TERRA) OUTPUT")
print("=" * 70)
if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    lines = proc.stderr.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ["model:", "tokens used", "session id", "error", "workdir"]):
            print(f"[{l.strip()}]")

receipt_path = r"D:\anonym\scratch\codex_delivery_receipt.md"
with open(receipt_path, "w", encoding="utf-8") as f:
    f.write(proc.stdout or "Codex produced no stdout.")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)

print(f"\nReceipt saved to: {receipt_path}")
