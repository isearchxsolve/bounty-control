import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Kunal Das, 22-year Principal Systems Architect and Technology Leader) has given a direct royal command:

"Sam, get the automation code audited, reviewed, and corrected by Codex. Ask him why there is no target open issue turnout."

================================================================================
BABA'S MANDATE: FULL FORENSIC AUDIT, CODE CORRECTION, AND TURNOUT DIAGNOSIS
================================================================================

Baba is asking why our autonomous pipeline has had low or zero open issue turnout (no new target open issues converting into successfully opened PRs).
You are granted full workspace access in `D:\\anonym` to inspect the code, logs, and database, directly edit and fix the files, and deliver your comprehensive verdict.

1. FORENSIC AUDIT OF THE TURNOUT PROBLEM:
Examine `D:\\anonym\\scripts\\autonomous_icu_pipeline.py`, `D:\\anonym\\scripts\\active_icu_supervisor.py`, `D:\\anonym\\scratch\\supervisor_logs\\autonomous_pipeline_live.log`, and `D:\\anonym\\scratch\\icu_pipeline.db`.
Answer Baba's question forensically:
- Why is there no target open issue turnout?
- Are the GitHub search queries returning 0 results, or are candidates being found but subsequently rejected by our pipeline gates?
- Inspect every filter stage:
  a. GitHub Search Syntax: Does GitHub's search API support all the query combinations we use? Does `gh search issues` handle operators like `comments:<=2` or quotes properly, or does it trigger search rate limits?
  b. Pre-Screen & Candidate Filters: Are genuine bounties or high-complexity tasks being discarded by over-restrictive regexes (e.g. `_parse_explicit_payment_amount`, `is_commercial_consulting_eligible`, `detect_author_corridor`, student patterns, non-incident filters)?
  c. Delivery & Ingestion Flow: When a candidate passes search, what causes it to halt? (e.g. `BLOCKED_BASELINE`, test harness discovery, worktree setup, Windows `.CMD` resolution, Token Harbor router timeouts, or competitor checks)?
  d. What is the real-world volume of accessible, uncontested GitHub bounty/hard-task issues per day, and how should our targeting matrix be engineered to maximize high-yield discovery without spamming?

2. DIRECTLY CORRECT AND OPTIMIZE THE CODE:
Directly edit `D:\\anonym\\scripts\\autonomous_icu_pipeline.py` (and `D:\\anonym\\scripts\\active_icu_supervisor.py` or test suite if needed):
- Fix any bugs, bottlenecks, or over-aggressive filters that cause false-positive rejections on viable open bounties and architecture issues.
- Optimize the search query matrix so it reliably surfaces genuine, active, uncontested targets (uncontested = 0 to 2 comments, 0 open PRs).
- Ensure the pipeline cleanly handles both explicit dollar bounties ($50 - $5,000) AND deep architecture issues with bounty labels or platform backing (Algora, Polar.sh, Opire, etc.).
- Maintain all Supreme Edicts strictly:
  * Zero Disavowal (Baba's 22-year architectural instinct is sovereign).
  * Zero-Competition Law (Pre-screen GitHub; if an unmerged open PR exists, NEVER touch it).
  * Hermetic Pre-PR Invariant (ZERO unverified code on GitHub; 100% tests must pass locally first).
  * Zero-Manufacture Law (Raw truth, zero synthetic receipts).
  * No-Signature DM Law (Zero signatures, corporate titles, or sign-offs).
  * Approved Enterprise Corridors & Hard Exclusions (Preserve exclusions for regional Kolkata/WB, China, Pakistan).

3. VERIFY WITH THE MASTER TEST SUITE:
Run `python scripts/test_icu_pipeline_suite.py` and ensure 100% of all tests pass green. If you modify any logic that affects the test suite, ensure the tests reflect the correct invariants and pass completely.

4. DELIVER THE ARCHITECTURAL VERDICT FOR BABA:
Provide a clear, rigorous, Principal Systems Architect report explaining:
- Exactly why there was no issue turnout previously (root-cause breakdown).
- Exactly what changes and corrections you made to the codebase.
- The verified results of `test_icu_pipeline_suite.py`.
- Concrete recommendations for maximizing uncontested bounty turnout going forward.
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

print("Launching Codex (gpt-5.6-terra) to audit, correct the code, and diagnose open issue turnout...")
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

with open(r"D:\anonym\scratch\codex_turnout_audit_report.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
