import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, the master frontier code auditor running on OpenAI gpt-5.6-terra.
Audit the upgraded Python code in D:\\anonym\\scripts\\autonomous_icu_pipeline.py and its test suite in D:\\anonym\\scripts\\test_icu_pipeline_suite.py.

In your previous audit (session 01a16e0d-6350-7ac1-8d8b-457a9c4df8d0), you confirmed the core implementations (sponsor correlation, Decimal precision, bounds, prior protections) were correct, and required:
1. Fix discovery-gate calls: Add `author=author` to verify_genuine_icu_patient calls in Phase 1 and dynamic search so NONE-association corporate sponsors can reach profile correlation.
2. Add integration test: Prove a correlated author_assoc="NONE" sponsor progresses through the discovery gate with author payload.
3. Commit test suite: Track `scripts/test_icu_pipeline_suite.py` in git.

Please inspect:
1. Are lines 929 and 989 in `autonomous_icu_pipeline.py` updated to pass `author=author` to `verify_genuine_icu_patient`?
2. Does `test_icu_pipeline_suite.py` contain the discovery gate integration test (Test 4d) verifying that a correlated NONE-association sponsor passes discovery?
3. Is `scripts/test_icu_pipeline_suite.py` committed and tracked in git?
4. Is the code fully sound and ready for deployment in Candidate Packet mode?

Provide your final authoritative verdict: APPROVED or ACTION REQUIRED."""

cmd = [
    codex_exe,
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "-C", r"D:\anonym",
    prompt
]

print("Executing Frontier Audit via OpenAI Codex (gpt-5.6-terra)...")
proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")

print("Exit code:", proc.returncode)
print("\n" + "="*50)
print("CODEX FRONTIER MODEL (GPT-5.6-TERRA) REVIEW REPORT")
print("="*50)
if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    lines = proc.stderr.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ["model:", "tokens used", "session id"]):
            print(f"[{l.strip()}]")
