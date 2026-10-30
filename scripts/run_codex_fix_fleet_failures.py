import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"
log_file = r"D:\anonym\scratch\codex_fleet_fix.log"
receipt_file = r"D:\anonym\scratch\codex_fix_receipt.md"

prompt = """You are Codex, running on OpenAI gpt-5.6-terra.
Baba (Kunal Das, 22-year Principal Systems Architect and Technology Leader) has given a direct royal command:
"check the logs eliminate the failures"

================================================================================
BABA'S MANDATE: ELIMINATE KAGGLE FLEET VERIFICATION FAILURES & HARDEN PIPELINE
================================================================================

CRITICAL OPERATIONAL INVARIANTS:
1. THE LAW OF ZERO DISAVOWAL: Baba's 22-year Principal Systems Architect instinct is sovereign. Obey 100%.
2. THE ZERO-MANUFACTURE LAW: Never manufacture mock files, fake diffs, or canned responses. Real code, real verification.
3. HEAVY WORK LAW: Laptop runs ONLY the search & dispatcher plane (<1% CPU). All baseline tests, compilers, and model execution run on Kaggle.

--------------------------------------------------------------------------------
ROOT CAUSE AUDIT & REQUIRED ARCHITECTURAL FIXES:
--------------------------------------------------------------------------------

1. IN `scripts/kaggle_engine_worker.py`:
   a) PURE PYTHON GITHUB COMMIT EVIDENCE:
      - In `collect_repo_evidence(repo, body)`:
        Replace fragile `gh api` CLI subprocess calls with direct HTTPS REST lookups using `urllib.request`:
        `https://api.github.com/repos/{repo}/commits/HEAD`
        Extract the immutable 40-hex commit SHA directly from the JSON payload.
        Add `Authorization: Bearer {token}` header from `os.environ.get('GH_TOKEN')` or `os.environ.get('GITHUB_TOKEN')`.
        Use regex `\\b([0-9a-fA-F]{40})\\b` on any fallback to guarantee pure 40-hex SHA extraction without CLI warning mangling.

   b) EXACT DIAGNOSTIC ERROR LOGGING:
      - When `generate_grounded_proposal` returns None, capture the EXACT cause:
        * Missing verified 40-hex commit SHA
        * TokenHarbor router HTTP 401 / 429
        * Router network timeout
        * Key exhaustion
      - In the main worker loop, report the exact diagnostic in `door_say`:
        `door_say(f"FAILED {ENGINE_ID} generation failed closed: {diag_reason} for {repo}#{number}", body="BOUNTY_RESULT")`

   c) UNCONDITIONAL LINUX TOOLCHAIN BOOTSTRAP:
      - In `setup_kaggle_env()`:
        Install `clang`, `libclang-dev`, `cmake`, `mold`, and `build-essential` via `apt-get` unconditionally so that Rust crates with C++ bindings (such as `rocksdb` in `paraloom-core`) compile without missing libclang.
        Set `LIBCLANG_PATH` environment variable if present.

   d) DETERMINISTIC CRYPTOGRAPHIC SHARDING:
      - Guarantee that task modulo sharding uses SHA-256:
        `task_hash = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16)`
        `assigned_engine = (task_hash % TOTAL_ENGINES) + 1`
        Zero randomized Python hash() drift across processes.

   e) ROBUST MULTI-FORMAT CODE EXTRACTION:
      - In `extract_files_from_proposal(proposal)`:
        Extract files across all valid Markdown formats:
        * `### Production Source (path/to/file.ext)`
        * `### Production Source (`path/to/file.ext`)`
        * `### `path/to/file.ext``
        * `**File:** `path/to/file.ext``
        * First-line code comment: `// path/to/file.ext` or `# path/to/file.ext`

   f) RUST VERIFICATION PLAN:
      - In `discover_verification_plan(arch, worktree)`:
        For Rust projects, use `cargo test --lib` for baseline and final unit tests so that unit tests pass cleanly without requiring external RPC validator daemons.

2. IN `scripts/autonomous_icu_pipeline.py`:
   a) SPECULATIVE DESIGN & ROADMAP EXCLUSION:
      - In `verify_genuine_icu_patient(...)`:
        Add strict exclusion patterns rejecting issues with:
        * `[ROADMAP]`, `[RFC]`, `[PROPOSAL]`, `[DESIGN]`, `[SPEC]`
        * Text containing `design/roadmap proposal only`, `proposal only`, `not an active deduction`, `illustrative defaults`, `pilot economic scenario`.
        This guarantees unpaid roadmap tickets (like `MyZubster-Ecosystem/myzubster#1462`) are dropped at the query layer.

3. DEPLOY & HERMETIC VERIFICATION:
   a) Deploy `kaggle_engine_worker.py` to all 5 Kaggle engines via `scripts/deploy_kaggle_engines.py`. Verify all 5 return OK (LIVE).
   b) Compile all scripts: `python -m py_compile scripts/autonomous_icu_pipeline.py scripts/kaggle_engine_worker.py scripts/deploy_kaggle_engines.py`.
   c) Run master test suite: `python scripts/test_icu_pipeline_suite.py` and ensure 100% of test suites pass GREEN.
   d) Write a complete verification receipt to `D:\\anonym\\scratch\\codex_fix_receipt.md`.
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

print("=" * 80)
print(f"LAUNCHING CODEX (GPT-5.6-TERRA) -> STREAMING TO {log_file}")
print("=" * 80)
sys.stdout.flush()

with open(log_file, "w", encoding="utf-8") as out_f:
    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=out_f,
        stderr=subprocess.STDOUT
    )

print(f"\nCodex Finished with Exit Code: {proc.returncode}")
print(f"Full log written to: {log_file}")
if os.path.exists(receipt_file):
    print(f"Receipt written to: {receipt_file}")
