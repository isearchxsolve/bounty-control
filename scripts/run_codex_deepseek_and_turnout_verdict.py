import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Kunal Das, 22-year Principal Systems Architect and Technology Leader) has given a direct royal command:

"But Sam, did Codex give the verdict like why there was zero issue result? Also, ask Codex to review and fix the deepseek issue, why deepseek is failing consistently."

================================================================================
BABA'S MANDATE: FORENSIC VERDICT ON ZERO-ISSUE RESULTS & FIX DEEPSEEK CONSISTENT FAILURES
================================================================================

CRITICAL OPERATIONAL RULE: DO NOT execute any process-killing commands (`Stop-Process`, `pkill`, `kill`). The automation processes are already stopped.

You are granted full workspace access in `D:\\anonym` to inspect the code, fix `scripts/autonomous_icu_pipeline.py` and `scripts/tokenharbor_router.py`, verify with `test_icu_pipeline_suite.py`, and deliver the definitive architectural verdict report.

--------------------------------------------------------------------------------
PART 1: VERDICT ON WHY THERE WAS ZERO ISSUE RESULT
--------------------------------------------------------------------------------
Provide the clear, definitive forensic verdict explaining to Baba:
1. In earlier runs, why did queries like `bounty "concurrency"` or `bounty "$200"` return literally `Found 0 candidates` across 21 consecutive cycles?
   - Explain how the 2-hour rolling timestamp window (`created:>={now - 2 hours}`) combined with `bounty` created an artificial desert on GitHub (global bounty generation volume vs. window size).
   - Explain the exact GitHub Search API behavior: how double quotes, operators, and search rate limits impacted discovery.
2. In the recent run without `created:>=`, why did the pipeline find 3-10 candidates per query but still zero PRs opened?
   - Detail the "Bounty Claim" noise: third-party contributors opening tickets with `[PAYOUT CLAIM]` (e.g. `osmesirius-ship-it/daxda-next-gen#24` claiming $14,000 for work already done), community claims (`bujiproject-art/agentmidasopendevteam`), closed tickets, and unfunded discussions.
   - Explain how to fix the search queries to exclude claim spam (e.g. `-claim -"payout claim"`) and target genuine, uncontested, open bounties.

--------------------------------------------------------------------------------
PART 2: REVIEW & FIX WHY DEEPSEEK IS FAILING CONSISTENTLY
--------------------------------------------------------------------------------
DeepSeek-v4.1 Flash Free via Token Harbor (17 keys in `vault/tokenharbor_keys.json`).
Baba noted DeepSeek is failing consistently in our pipeline. Diagnose the root causes:
1. **Aggressive Escalation Keyword Filter**: In `scripts/autonomous_icu_pipeline.py`, `_CODEX_ESCALATION_KEYWORDS` matched `payment`, `billing`, `wallet`, `settlement`, `concurrency`, `race condition`, `deadlock`, `security`. Since almost every bounty task contains these words, `should_escalate_to_codex()` evaluated to True, completely bypassing DeepSeek! DeepSeek was never even called on bounty tasks!
2. **Timeout Bottleneck**: In `scripts/autonomous_icu_pipeline.py`, line 1074, `call_deepseek_flash(prompt, timeout=60)` used 60s. In `scripts/deepseek_inbound_pipeline.py`, line 181, `timeout=35` was used. When DeepSeek generates multi-file architectural code (1,000-1,500 tokens), it can take 60-120 seconds. A 35s or 60s timeout causes an instant `URLError: The read operation timed out`.
3. **Prompt & Context Size**: When `prompt` is too large or contains raw unescaped file dumps, how does Token Harbor respond?
4. **Cline + DeepSeek Configuration**: If Baba uses Cline with DeepSeek-v4.1 Flash via Token Harbor, what causes Cline to fail or loop, and how must Cline's settings (temperature, max tokens, custom instructions, timeout) be tuned for reliable multi-turn coding?

--------------------------------------------------------------------------------
PART 3: DIRECT CODE CORRECTIONS
--------------------------------------------------------------------------------
Directly edit `D:\\anonym\\scripts\\autonomous_icu_pipeline.py` and `D:\\anonym\\scripts\\tokenharbor_router.py`:
1. In `scripts/autonomous_icu_pipeline.py`:
   - Adjust `should_escalate_to_codex` so it does NOT immediately bypass DeepSeek merely because a bounty issue mentions 'payment', 'wallet', 'bounty', or 'settlement'. Let Tier-1 DeepSeek-Flash handle Turn 1-2 drafting, and escalate to Codex only when DeepSeek fails or on hard turns (Turn > 2) or explicit user override.
   - Increase DeepSeek timeout to 120s in `autonomous_icu_pipeline.py` and `tokenharbor_router.py` to allow DeepSeek enough runway to complete code generation without premature read timeouts.
   - Update the dynamic search queries in `autonomous_icu_pipeline.py` to append `-claim -"payout claim"` to eliminate third-party claim submissions from the discovery funnel.
2. In `scripts/tokenharbor_router.py`:
   - Ensure timeout defaults to 120s.
   - Ensure clean error reporting and resilient retry behavior across the 17 keys.
3. Run `python scripts/test_icu_pipeline_suite.py` to ensure all 12 tests pass 100% green.

--------------------------------------------------------------------------------
PART 4: WRITE DEFINITIVE VERDICT REPORT
--------------------------------------------------------------------------------
Write the complete verdict and explanation to `D:\\anonym\\scratch\\codex_deepseek_and_turnout_verdict.md`.
Ensure the report covers all of Baba's questions in depth with Ramanujan precision and Principal Systems Architect authority.
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

print("Launching Codex (gpt-5.6-terra) to diagnose zero issue results, fix DeepSeek failures, and deliver the verdict...")
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

with open(r"D:\anonym\scratch\codex_deepseek_verdict_output.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
