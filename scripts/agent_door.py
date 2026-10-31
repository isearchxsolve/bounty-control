"""The agent entry door, wired for the discovery workflow.

Why this exists (measured 2026-10-30): discovery searched with 74 static expressions and refused
roughly 15,000 issues across 122 runs, 11,840 of them from one hardcoded offer rule. The agent that
can follow a bounty and read a payer's own words was never asked to search. This module puts the
agent in front of the search, and leaves every gate behind it untouched.

Contract:
  * ``find_issues()`` returns rows the agent verified, or an empty list plus a reason;
  * nothing here admits anything: the dispatcher queues these rows and the existing admission,
    capacity and dispatch gates decide what happens to them;
  * any failure (no keys, no Cline, no rows) is reported as a named reason and discovery carries
    on with its static lane - the door must never take the pipeline down with it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import tempfile
from typing import Dict, List, Optional

import cline_entry_door

PROXY_PORT = int(os.environ.get("TOKENHARBOR_PROXY_PORT", os.environ.get("NVIDIA_PROXY_PORT", "8080")))
CLINE_PACKAGE = os.environ.get("CLINE_PACKAGE", "cline@3.0.74")


def _keys_available() -> bool:
    return bool(os.environ.get("TOKENHARBOR_KEYS_JSON") or os.environ.get("TOKENHARBOR_KEY_FILE")
                or os.path.exists(r"D:\anonym\vault\tokenharbor_keys.json")
                or os.environ.get("NVIDIA_KEYS_JSON") or os.environ.get("NVIDIA_API_KEY"))


def start_gateway(timeout: float = 20.0) -> bool:
    """Bring up the local OpenAI-compatible TokenHarbor gateway Cline talks to. False means no gateway.

    Cline is never pointed straight at the provider: proxy handles key rotation and failover.
    """
    import urllib.error
    import urllib.request

    probe = f"http://127.0.0.1:{PROXY_PORT}/health"

    def alive() -> bool:
        try:
            with urllib.request.urlopen(probe, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    if alive():
        return True
    if not _keys_available():
        print(json.dumps({"phase": "ENTRY_DOOR", "gateway": "NO_KEYS",
                          "detail": "set TOKENHARBOR_KEYS_JSON"}), flush=True)
        return False

    try:
        import kaggle_engine_worker as worker
        ok, diag = worker.ensure_cline_proxy_running()
        if ok and alive():
            print(json.dumps({"phase": "ENTRY_DOOR", "gateway": "UP",
                              "url": f"http://127.0.0.1:{PROXY_PORT}/v1"}), flush=True)
            return True
        thread = threading.Thread(target=worker.run_cline_proxy_server, daemon=True)
        thread.start()
    except Exception:
        try:
            import nvidia_openai_proxy
            thread = threading.Thread(target=nvidia_openai_proxy.main, daemon=True)
            thread.start()
        except Exception:
            return False

    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if alive():
            print(json.dumps({"phase": "ENTRY_DOOR", "gateway": "UP",
                              "url": f"http://127.0.0.1:{PROXY_PORT}/v1"}), flush=True)
            return True
        time.sleep(0.5)
    print(json.dumps({"phase": "ENTRY_DOOR", "gateway": "TIMEOUT"}), flush=True)
    return False


def ensure_cline(timeout: int = 900) -> Optional[str]:
    """Path to a runnable Cline launcher, installing the pinned version when it is missing."""
    existing = shutil.which("cline")
    if existing:
        return existing
    npm = shutil.which("npm")
    if not npm:
        print(json.dumps({"phase": "ENTRY_DOOR", "cline": "NO_NPM"}), flush=True)
        return None
    print(json.dumps({"phase": "ENTRY_DOOR", "cline": "INSTALLING", "package": CLINE_PACKAGE}),
          flush=True)
    try:
        done = subprocess.run([npm, "install", "--global", "--no-audit", "--no-fund", CLINE_PACKAGE],
                              capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"phase": "ENTRY_DOOR", "cline": "INSTALL_FAILED",
                          "detail": str(exc)[:200]}), flush=True)
        return None
    if done.returncode != 0:
        print(json.dumps({"phase": "ENTRY_DOOR", "cline": "INSTALL_FAILED",
                          "detail": (done.stderr or done.stdout or "")[-400:]}), flush=True)
        return None
    return shutil.which("cline")


def find_issues(root: Optional[str] = None, rounds: int = 1, timeout: int = 600,
                limit: int = 0, on_admitted=None, lanes=None, prior_refusals=None) -> Dict[str, object]:
    """Run the agent door and return what survived its gate. Never raises."""
    root = root or os.environ.get("BOUNTY_AGENT_WORKSPACE", "/tmp/bounty-agent")
    gated = os.environ.get("BOUNTY_ENTRY_DOOR", "").strip().lower()
    if gated not in ("cline", "agent", "1", "true"):
        return {"rows": [], "reason": "DOOR_DISABLED"}
    cline = ensure_cline()
    if not cline:
        return {"rows": [], "reason": "CLINE_UNAVAILABLE"}
    if not start_gateway():
        return {"rows": [], "reason": "GATEWAY_UNAVAILABLE"}
    try:
        workdir = cline_entry_door.scaffold_workspace(root)
        leads = cline_entry_door.ingest_founder_watch_leads()
        if leads:
            with open(os.path.join(workdir, "founder-leads.json"), "w", encoding="utf-8") as handle:
                json.dump(leads, handle)
        from actions_github import GitHub  # noqa: E402
        prompt = cline_entry_door.WORKTREE_PROMPT
        prompt += '''
You decide admission by reading the actual source; the host checks literal evidence, not keywords.
For every priced row include funding: {amount: "250", currency: "USD", payer: "exact source author login",
source_url: "exact issue/comment permalink"},
admission_reason: your interpretation of current funding, authority, bounded code scope and repository intent,
scope_quote: a literal issue/comment sentence describing the change, and reward_quote: the literal priced offer.
Inspect the actual repository code before selecting it. Include code_evidence: {path: "repository-relative
source file", sha: "actual GitHub blob SHA", quote: "literal source excerpt", is_product_code: true}.
This must be a source file you read, not a README, digest, grant announcement or a speculative file name.
Choose the file and explain its relationship to the requested change in admission_reason. The host checks
that the exact blob and quoted source exist. A repository with no actual product code cannot satisfy this.
Read the whole conversation, including later withdrawals and awards. Do not mistake budget mentions,
copied third-party offers, already-paid rewards or symbolic bounties for a current committed offer.
Never invent a payer, authority, quote, amount or source. Code checks the chosen source and amount.
For an unpriced repository-owner incident, set is_founder_wound true and cite the OWNER-authored issue
in funding.source_url and funding.payer; omit amount and currency.
Still supply the scope quote, actual product-code evidence and your admission_reason.
The host records this as an unpriced owner request, without asserting a monetary promise.
'''
        if prior_refusals:
            with open(os.path.join(workdir, "prior-refusals.json"), "w", encoding="utf-8") as handle:
                json.dump(prior_refusals, handle, indent=2)
            prompt += ("\nRead prior-refusals.json before reconsidering previously refused work. "
                       "If the old verdict is wrong or facts changed, include reconsideration: "
                       "{previous_updated_at: the exact old updated_at, reason: your source-backed explanation}. "
                       "Preserve the old diagnosis; do not automatically replay the backlog.")
        if lanes:
            prompt += ("\nSet source_lane on each shortlist row to one of these active source lanes: "
                       + ", ".join(lanes) + ". Choose its lane from the actual source; do not invent evidence.")
        if leads:
            prompt += "\nInspect founder-leads.json as unverified leads; read their sources before admitting anything."
        outcome = cline_entry_door.iterate(
            workdir, rounds=rounds,
            data_dir=os.path.join(tempfile.gettempdir(), "bounty-search-profiles", os.path.basename(workdir)),
            limit=limit, timeout=timeout, cline=cline,
            verify=cline_entry_door.verify_model_rows,
            model=os.environ.get("BOUNTY_ENTRY_MODEL", "deepseek-v4.1-flash:free"),
            first_prompt=prompt, on_admitted=on_admitted,
            admission_client=GitHub())
        cline_entry_door.write_unpriced_leads(workdir, outcome.get("unpriced") or [])
    except Exception as exc:  # a broken door must not stop discovery
        print(json.dumps({"phase": "ENTRY_DOOR", "error": type(exc).__name__,
                          "detail": str(exc)[:300]}), flush=True)
        return {"rows": [], "reason": "DOOR_FAILED"}
    rows: List[dict] = list(outcome.get("admitted") or [])
    print(json.dumps({"phase": "ENTRY_DOOR", "workspace": workdir,
                      "history": outcome.get("history"), "admitted": len(rows),
                      "refused": len(outcome.get("refused") or [])}), flush=True)
    return {"rows": rows, "reason": "OK" if rows else "NO_ROWS", "workspace": workdir,
            "history": outcome.get("history"), "refused": outcome.get("refused") or [],
            "unpriced": outcome.get("unpriced") or []}


def main() -> int:
    result = find_issues(rounds=int(os.environ.get("BOUNTY_AGENT_ROUNDS", "1")))
    print(json.dumps({"reason": result.get("reason"), "rows": len(result.get("rows") or [])}))
    for row in result.get("rows") or []:
        print("ROW {repo}#{issue} :: {quote}".format(
            repo=row.get("repo"), issue=row.get("issue"),
            quote=str(row.get("reward_quote"))[:100]))
    return 0 if result.get("rows") else 1


if __name__ == "__main__":
    raise SystemExit(main())
