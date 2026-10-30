import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Principal Systems Architect) has given a direct royal order:
"ask codex to wire deepseek along with the proposed architecture for deepseek"

Implement the complete tiered architecture you proposed for DeepSeek-v4.1 Flash-Free + Token Harbor + Codex escalation:

================================================================================
1. IMPLEMENT TOKEN HARBOR KEY ROUTER: `D:\\anonym\\scripts\\tokenharbor_router.py`
================================================================================
Create a robust, thread-safe key router module managing the 14+ Token Harbor API keys located at `D:\\anonym\\vault\\tokenharbor_keys.json`:
- Key States: `READY`, `LEASED`, `COOLDOWN`, `DISABLED`.
- Endpoint: `https://tokenharbor.ai/v1/chat/completions`
- Model: `deepseek-v4.1-flash:free`
- Router capabilities:
  - Leases an available `READY` key per request (1 in-flight per key).
  - On HTTP 429: puts key into `COOLDOWN` with exponential backoff + jitter (honoring `Retry-After` if header present), and transparently retries with the next `READY` key.
  - On HTTP 401/403: marks key `DISABLED` immediately, logs alert, and falls back to next key.
  - On network timeout or 5xx: retries once with fallback key.
  - Returns `(success: bool, response_text: str, model_used: str, error_msg: Optional[str])`.
  - Export functions: `call_deepseek_flash(prompt: str, system_prompt: Optional[str] = None, timeout: int = 60) -> Tuple[bool, str, Optional[str]]` and `get_router_status() -> dict`.

================================================================================
2. WIRE TIERED GENERATION INTO `D:\\anonym\\scripts\\autonomous_icu_pipeline.py`
================================================================================
Wire the Token Harbor DeepSeek worker and Codex escalation into `autonomous_icu_pipeline.py`:
- In `generate_grounded_proposal(repo, title, body, author, author_comments, iteration_feedback=None, force_model=None)`:
  - Check escalation conditions:
    - Escalate to Codex (`gpt-5.6-terra`) if:
      - `turn > 2` (stalled Flash repairs).
      - Domain involves security, auth, concurrency, payments, or data-loss invariants.
      - Explicit `force_model="codex"`.
    - Otherwise, use Tier 1: `call_deepseek_flash`.
    - If DeepSeek fails, times out, or exhausts keys, automatically failover to Codex (`gpt-5.6-terra`) so the pipeline never halts.
- In `run_engineering_iteration_loop`:
  - Turn 1: DeepSeek-v4.1 Flash attempts initial grounded implementation and tests.
  - Turn 2: If test/lint fails, DeepSeek-v4.1 Flash attempts repair with diagnostic error feedback.
  - Turn 3+: If turn 2 failed, escalate to Codex (`gpt-5.6-terra`) with full prior error feedback.
  - Log model transitions cleanly (e.g. `[TIER-1 DEEPSEEK-FLASH]` vs `[TIER-2 CODEX-ESCALATION]`).

================================================================================
3. EXPAND TEST SUITE IN `D:\\anonym\\scripts\\test_icu_pipeline_suite.py`
================================================================================
Add tests in `test_icu_pipeline_suite.py` (e.g. Test 12: Tiered DeepSeek & Token Harbor Key Router):
- Test key router state transitions (`READY`, `LEASED`, `COOLDOWN`, `DISABLED`).
- Test 429 rate limit cooldown and fallback to next available key.
- Test escalation trigger logic (concurrency/security keywords trigger Codex, turn > 2 triggers Codex).
- Test DeepSeek response handling and transparent failover.

================================================================================
4. VERIFICATION INVARIANTS
================================================================================
- Run `python scripts/test_icu_pipeline_suite.py` and verify 100% tests pass GREEN.
- Run `python -m py_compile scripts/autonomous_icu_pipeline.py scripts/tokenharbor_router.py scripts/test_icu_pipeline_suite.py` with 0 errors.
- Run `git diff --check` and verify ZERO whitespace warnings.
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

print("Launching Codex (gpt-5.6-terra) to WIRE DeepSeek-v4.1 Flash + Token Harbor + Tiered Architecture...")
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

with open(r"D:\anonym\scratch\codex_wire_deepseek_report.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
