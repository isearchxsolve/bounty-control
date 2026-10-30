import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Principal Systems Architect) has given two direct royal commands:

================================================================================
MANDATE 1: DIRECTLY FIX D:\\anonym\\scripts\\autonomous_icu_pipeline.py AND D:\\anonym\\scripts\\test_icu_pipeline_suite.py
================================================================================
In your previous forensic audit, you rejected the implementation with 8 blocking findings.
You are granted full workspace access to directly edit and fix `D:\\anonym\\scripts\\autonomous_icu_pipeline.py` and `D:\\anonym\\scripts\\test_icu_pipeline_suite.py` in place.

Fix every single one of your blocking findings:
1. Multi-turn repair feedback loop: Ensure `prior_failures` (test failures, lint failures, syntax errors) is explicitly passed into `generate_grounded_proposal` prompt on turns 2-5 so the model diagnoses and repairs the exact error. Reset worktree to clean upstream state before applying repair turn.
2. Filesystem-safe path protection: In `is_safe_relative_path`, resolve realpaths and symlinks (`os.path.realpath`, `os.path.commonpath`), and make `.github/workflows` blocking case-insensitive so casing variants cannot bypass it.
3. Upstream default branch & error handling: In `prepare_isolated_worktree`, dynamically discover the repo's default branch (`gh repo view ... --json defaultBranchRef`), and check the exit code of every git command (`clone`, `remote`, `fetch`, `checkout`, `reset`, `clean`, `rev-parse`) fail-closed.
4. Syntax gate & BLOCKED_BASELINE: Wire `validate_synthesized_files` into the iteration loop before running native tests. Explicitly record `BLOCKED_BASELINE` state in the SQLite deliveries table when baseline tests fail.
5. Polyglot architecture detection: Update `inspect_repository_architecture` to record all active ecosystems without mutually exclusive `elif`.
6. Zero-competition search completeness: In `check_competing_prs_fail_closed`, query `--limit 100` with `body` included, and search title, headRefName, and body for exact issue number references (e.g. `#142`, `fixes #142`, `resolves #142`).
7. Real PR receipts & single-commit discipline: In `build_peer_pr_body`, embed exact verification receipts (base SHA, command list, exit codes, durations). In `commit_and_open_pr`, stage ONLY the verified modified files (eliminate `git add -A`), verify pre/post commit SHAs and `git rev-list --count` equals 1.
8. Comprehensive Test 11 coverage: Expand `test_icu_pipeline_suite.py` to execute and verify the actual repair loop, symlink rejection, default branch handling, and single-commit discipline.
9. Zero trailing whitespace: Ensure `git diff --check` passes with zero warnings.

After making the edits, run `python scripts/test_icu_pipeline_suite.py` to ensure 100% of all tests pass green.

================================================================================
MANDATE 2: ARCHITECTURAL CONSULTATION FOR BABA ON DEEPSEEK-V4.1 FLASH-FREE + CLINE + TOKEN HARBOR (14 KEYS)
================================================================================
Baba asks:
"Can we use deepseek-v4.1 flash-free instead of any other model like Codex itself? For the autonomous agent, we will be using cline combined with deepseek-v4.1 flash-free provided by Token Harbor, rotated among 14 API keys. Ask Codex."

Provide a thorough, highly technical architectural assessment from a Principal Systems Architect perspective:
1. Feasibility & Model Capability: How does deepseek-v4.1 flash-free perform on complex multi-turn coding, tool use, JSON/file patching, and syntax precision compared to frontier models like Codex/gpt-5.6-terra?
2. Architecture & Orchestration: How should Cline be orchestrated with Token Harbor rotating across 14 API keys? (Key rotation pool strategy, cooldown on 429 rate limits, concurrency limits, fallback routing).
3. Token Economics & Cost: Compare the cost efficiency and operational runway of 14 rotated free keys vs commercial models.
4. Potential Failure Modes & Mitigation: What are the risks (e.g. context window limits, instruction drift on multi-turn iterations, rate-limit cascades) and how to mitigate them hermetically?
5. Final Verdict & Recommendation: Can deepseek-v4.1 flash-free + Cline + Token Harbor be used as the primary engine for the 24/7 autonomous agent?
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

print("Launching Codex (gpt-5.6-terra) to DIRECTLY FIX the codebase and deliver Baba's architectural consultation...")
proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")

print("Codex Exit Code:", proc.returncode)
print("\n" + "="*60)
print("CODEX (GPT-5.6-TERRA) OUTPUT")
print("="*60)
if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    lines = proc.stderr.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ["model:", "tokens used", "session id", "error"]):
            print(f"[{l.strip()}]")

with open(r"D:\anonym\scratch\codex_fix_and_consult_report.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
