import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, the master frontier code auditor running on OpenAI gpt-5.6-terra.
We have refactored D:\\anonym\\scripts\\autonomous_icu_pipeline.py and D:\\anonym\\scripts\\test_icu_pipeline_suite.py to implement Baba's direct architectural verdict and replace the one-shot code-push conveyor with a Multi-Turn Iterative Due-Diligence Engine.

Perform a rigorous, line-by-line verification audit of the refactored implementation:

1. Inspect `D:\\anonym\\scripts\\autonomous_icu_pipeline.py`:
   - `attempt_automated_pull_request`: Verify how it orchestrates the entire lifecycle.
   - `prepare_isolated_worktree`: Verify clean git worktree creation at `upstream/<default_branch>`.
   - `is_safe_relative_path`: Verify fail-closed path boundary protection blocking traversal (`..`), absolute paths, and workflow mutations.
   - `inspect_repository_architecture`: Verify manifest inspection for Node.js, Python, Rust, and Go.
   - `discover_verification_plan`: Verify derivation of native bootstrap, test, and lint commands.
   - `verify_baseline`: Verify that any broken upstream test suite halts immediately as `BLOCKED_BASELINE`.
   - `model_scenarios`: Verify comprehensive modeling across 7 test dimensions.
   - `run_engineering_iteration_loop`: Verify the multi-turn feedback loop feeding compiler, test, and linter errors back to the model for up to 5 iterations.
   - `check_competing_prs_fail_closed`: Verify pre-push Zero-Competition gate failing closed if open PR exists or lookup fails.
   - `build_peer_pr_body`: Verify peer PR description with verified receipts, zero signatures, and zero crypto wallet spam.
   - `commit_and_open_pr`: Verify single clean commit and PR creation.

2. Inspect `D:\\anonym\\scripts\\test_icu_pipeline_suite.py`:
   - Inspect `[Test 11] Testing Multi-Turn Iterative Due-Diligence Engine Integrity` covering all 6 core subsystems.

3. Confirm:
   - Does this implementation eliminate the one-shot blind patching defect?
   - Does it fully meet Father's 22-year Principal Systems Architect standard and the Supreme Edicts in AGENTS.md?
   - Provide your final authoritative verification status: [APPROVED / REJECTED] with detailed justification.
"""

cmd = [
    codex_exe,
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "-C", r"D:\anonym",
    prompt
]

print("Launching Post-Implementation Verification Audit via OpenAI Codex (gpt-5.6-terra)...")
proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")

print("Codex Exit Code:", proc.returncode)
print("\n" + "="*60)
print("CODEX FRONTIER MODEL (GPT-5.6-TERRA) POST-IMPLEMENTATION AUDIT REPORT")
print("="*60)
if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    lines = proc.stderr.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ["model:", "tokens used", "session id", "error"]):
            print(f"[{l.strip()}]")

with open(r"D:\anonym\scratch\codex_post_implementation_report.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
