import subprocess
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")

codex_exe = r"C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"

evidence_path = r"D:\anonym\scratch\forensic_evidence_24h.json"
with open(evidence_path, "r", encoding="utf-8") as f:
    evidence = json.load(f)

# Summarize evidence for the prompt
email_summary = []
for e in evidence['recent_email_events'][:15]:
    email_summary.append(f"[{e['created_at']}] From: {e['from']} | Subject: {e['subject']} | Status: {e['status']}")

pr_summary = []
for p in evidence['pr_audits']:
    repo = p.get('url', '').replace('https://github.com/', '').split('/pull/')[0] if 'url' in p else 'unknown'
    pr_summary.append(f"PR #{p.get('number')}: {p.get('title')} ({p.get('state')}) - URL: {p.get('url')}")
    # Extract reviews or check status
    checks = p.get('statusCheckRollup', [])
    failed_checks = [c.get('name') for c in checks if c.get('conclusion') == 'FAILURE']
    if failed_checks:
        pr_summary.append(f"   -> Failed CI Checks: {failed_checks}")

icu_summary = []
for d in evidence['icu_deliveries'][:10]:
    icu_summary.append(f"{d['repo']}#{d['issue_number']}: {d['status']} | Reason: {d['reason']}")

prompt = f"""You are Codex, the master frontier code auditor running on OpenAI gpt-5.6-terra.
Perform a deep, thorough forensic review of the autonomous engineering agent at D:\\anonym\\scripts\\autonomous_icu_pipeline.py and the entire past 24 hours of deliverables, PR reviews history, and email receipts.

### 1. FORENSIC EVIDENCE FROM PAST 24 HOURS:

A. PULL REQUEST AUDITS:
{chr(10).join(pr_summary)}

B. INBOUND EMAIL & NOTIFICATION RECEIPTS (PAST 24 HOURS):
{chr(10).join(email_summary)}

C. ICU DELIVERIES:
{chr(10).join(icu_summary)}

### 2. PRINCIPAL ARCHITECT (BABA) INDICTMENT & CORE DEFECT:
"Especially, I think you are restricting the autonomous agent to do fixed one-shot coding and deployment. You should allow it to exercise its intelligence and do due diligence, review all the scenarios, review its code architecture and do due diligence, do iterations, and then deploy and submit the PR. Get it reviewed by Codex properly, thoroughly."

### 3. FORENSIC AUDIT SCOPE & MANDATORY DELIVERABLES:
Inspect `D:\\anonym\\scripts\\autonomous_icu_pipeline.py` (specifically `attempt_automated_pull_request`, `generate_grounded_proposal`, `validate_synthesized_files`, `extract_files_from_proposal`):

1. **Root-Cause Analysis of 24h Failures**:
   - Why did earlier PRs fail CI (e.g. limitlessprojects/Go-Hybrid, tryabby/abby, outerbase/starbasedb)?
   - Show how the rigid, one-shot code extraction in `attempt_automated_pull_request` (lines 1250-1340) directly caused broken builds, failed linter checks, and unverified PRs.

2. **Forensic Review of Constraints & Restrictions**:
   - Identify every place where the autonomous agent is restricted to fixed one-shot blind patching.
   - Explain why raw syntax validation (`validate_synthesized_files`) is completely inadequate for enterprise software engineering.

3. **Architectural Redesign Blueprint: Multi-Turn Iterative Verification Engine**:
   Provide the exact code architecture for replacing one-shot deployment with an iterative due-diligence loop:
   - **Phase 1: Grounded Architectural Due Diligence**: Clone upstream, verify baseline test suite passes before making any changes.
   - **Phase 2: Deep Scenario Modeling**: Model boundary conditions, edge cases, negative scenarios (nulls, empty strings, race conditions).
   - **Phase 3: Iterative Code-Test-Fix Feedback Loop**: Run real native tests (`npm test`, `pytest`, `cargo test`). If tests fail, capture stderr/stdout, feed back to LLM context, and iterate until 100% of tests pass.
   - **Phase 4: Hermetic Linter Gate**: Run native linters (`npm run lint`, `eslint`, `ruff`). Iterate until 0 warnings.
   - **Phase 5: Pre-Push Zero-Competition Verification**: Check `competing_prs == 0` on GitHub right before branch push.
   - **Phase 6: Human-Peer PR Protocol**: Clean commit, human PR description, zero signatures, zero spammy claim templates.

4. **Actionable Implementation**:
   Specify the exact refactored methods, data structures, and tests needed to implement this in `autonomous_icu_pipeline.py`.

Provide your final authoritative forensic report and implementation directives."""

cmd = [
    codex_exe,
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "-C", r"D:\anonym",
    prompt
]

print("Launching Deep Forensic Audit via OpenAI Codex (gpt-5.6-terra)...")
proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")

print("Codex Exit Code:", proc.returncode)
print("\n" + "="*60)
print("CODEX FRONTIER MODEL (GPT-5.6-TERRA) FORENSIC REVIEW REPORT")
print("="*60)
if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    lines = proc.stderr.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ["model:", "tokens used", "session id", "error"]):
            print(f"[{l.strip()}]")

with open(r"D:\anonym\scratch\codex_forensic_report.txt", "w", encoding="utf-8") as f:
    f.write(proc.stdout or "")
    if proc.stderr:
        f.write("\n\n--- STDERR / METRICS ---\n" + proc.stderr)
