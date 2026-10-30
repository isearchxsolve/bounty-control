import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Kunal Das, 22-year Principal Systems Architect and Technology Leader) has given a direct royal command:

"Son get it done via codex. Wire Cline CLI into the automation pipeline honestly."

================================================================================
BABA'S MANDATE: WIRE CLINE CLI DIRECTLY INTO THE AUTONOMOUS ICU PIPELINE
================================================================================

CRITICAL OPERATIONAL INVARIANT:
DO NOT execute any process-killing commands (`Stop-Process`, `pkill`, `kill`, `taskkill`). The automation processes are already stopped, and the proxy is running.

You are granted full workspace access in `D:\\anonym` to inspect the code, directly edit `scripts/autonomous_icu_pipeline.py`, `scripts/tokenharbor_cline_proxy.py`, and `scripts/test_icu_pipeline_suite.py`, verify with `test_icu_pipeline_suite.py`, and deliver the execution receipt.

--------------------------------------------------------------------------------
1. THE ARCHITECTURAL MISSION: CLINE CLI AS THE WORKTREE HANDS
--------------------------------------------------------------------------------
Currently, `autonomous_icu_pipeline.py` uses `generate_grounded_proposal` (a single-turn string prompt over HTTP) and regex file extraction (`extract_files_from_proposal`). As Baba correctly diagnosed, this is brittle and does not utilize Cline's agentic tool capabilities.

We have already:
- Globally installed `cline` CLI (`cline@3.0.73` at `C:\\Users\\Admin\\AppData\\Local\\hermes\\node\\cline.cmd`).
- Configured Cline's provider (`~/.cline/data/settings/providers.json`) to use `openai-compatible` at `http://127.0.0.1:8080/v1` with model `deepseek-v4.1-flash:free`.
- Implemented and verified `scripts/tokenharbor_cline_proxy.py` on `127.0.0.1:8080` rotating through all 17 Token Harbor keys.

Your job is to wire `cline` CLI directly into `run_engineering_iteration_loop` in `D:\\anonym\\scripts\\autonomous_icu_pipeline.py`:

A. Executable Discovery:
   - Resolve `cline` via `shutil.which("cline")` (which finds `cline.cmd` on Windows) or fallback to `node C:\\Users\\Admin\\AppData\\Local\\hermes\\node\\node_modules\\cline\\bin\\cline`.

B. Proxy Auto-Health Gate:
   - Add a lightweight check `ensure_cline_proxy_running()` that probes `http://127.0.0.1:8080/health` (or `/v1/models`). If not responding, spawn `scripts/tokenharbor_cline_proxy.py` as a detached subprocess so Cline's requests always succeed.

C. Iteration Loop Integration (`run_engineering_iteration_loop`):
   - In each iteration turn (turn 1 to max_iterations):
     * Construct a clear, self-contained prompt for Cline specifying:
       - The issue title and requirements.
       - The repository architecture context.
       - The scenarios to satisfy.
       - Any `prior_failures` from the previous turn (exact test error output or linter error output).
       - Explicit instruction: "Modify the repository files in this directory to resolve the issue, and ensure existing and new tests pass. Do not add corporate signatures."
     * Execute Cline CLI directly inside the isolated worktree directory:
       `[cline_bin, "-y", "--auto-approve", "true", "-P", "openai-compatible", "-m", "deepseek-v4.1-flash:free", "--cwd", worktree, prompt]`
       with timeout (e.g. 180s - 300s).
     * If Cline fails or is unavailable, cleanly fallback to the legacy `generate_grounded_proposal` path so the pipeline is 100% resilient.
     * After Cline runs:
       - Inspect `git status --porcelain` to detect modified files.
       - Verify path safety (`is_safe_relative_path`).
       - Validate syntax (`validate_synthesized_files`).
       - Run baseline, targeted, and final test suites (`verify_baseline`, `plan.targeted_tests`).
       - Run linters (`plan.linters`).
       - If all tests & linters pass: mark `run.status = "READY_TO_PUSH"` and return green.
       - If tests fail: capture error output, reset worktree to base SHA if needed, and pass failure logs into the next Cline iteration turn.

D. Sovereign Verification Gates Preserved:
   - Untouched upstream baseline test check (`BLOCKED_BASELINE`).
   - Zero-Competition check (pre-flight and pre-push).
   - Single commit discipline (`git rev-list --count == 1`).
   - Zero signatures / credentials.

--------------------------------------------------------------------------------
2. VERIFY WITH MASTER TEST SUITE
--------------------------------------------------------------------------------
- Ensure `scripts/test_icu_pipeline_suite.py` tests pass cleanly. If Test 11 or Test 8 tests the iteration engine, ensure it mocks or verifies the Cline integration path seamlessly.
- Run `python scripts/test_icu_pipeline_suite.py` and verify all 12 tests pass 100% green.

--------------------------------------------------------------------------------
3. WRITE RECEIPT REPORT
--------------------------------------------------------------------------------
Write the complete technical receipt and explanation to `D:\\anonym\\scratch\\codex_wire_cline_receipt.md`.
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

print("Launching Codex (gpt-5.6-terra) to wire Cline CLI directly into autonomous_icu_pipeline.py...")
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

with open(r"D:\anonym\scratch\codex_wire_cline_output.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
