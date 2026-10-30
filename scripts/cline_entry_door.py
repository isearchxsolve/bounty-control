"""Cline searches for payable issues. Code only verifies what Cline claims.

Measured reason for this file (2026-10-30): the door was static queries plus ~15,000 hardcoded
refusals across 122 runs, 11,840 of them from one offer-regex, and zero deliveries. The agent that
could follow a bounty link and read a payer's own words was never asked to search at all.

Contract with the agent:
  * it works in a scratch directory and writes ``shortlist.jsonl``, one JSON object per line;
  * every row must name a real issue and quote the sentence that promises the money;
  * nothing it writes is trusted here - each row is checked against GitHub and against its own
    quoted text, and a row that fails is refused with a named reason.

So the search is agent judgement, and admission stays a receipt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from issue_scout import quote_is_present  # noqa: E402  (markdown-escape aware)

FRESH_START = """Ignore any earlier conversation in this session, if one exists. It does not apply here.
Nothing was handed to you to read: no file, no list, no message. The work is described below.

"""
SEARCH_PROMPT = FRESH_START + """Read TASK.md in this worktree and do the work it describes. Write shortlist.jsonl in this directory, then finish."""


SCOUT_SYSTEM = (
    "You are a GitHub bounty scout with shell access through run_commands. "
    "There is no repository in this workspace and you are not asked to write or change code. "
    "Your single job is to find open GitHub issues that promise money for engineering work, read "
    "them, and record them. Your tools of trade are gh search issues and gh issue view. "
    "Never look for local source code, task files or worktrees: this workspace is intentionally "
    "empty. Never ask a question and wait, because nobody is watching; decide and act. "
    "One line only, no newlines. When you have rows, write shortlist.jsonl in the current "
    "directory and stop."
)


def resolve_cline(cline: Optional[str] = None) -> List[str]:
    """How to actually launch Cline from Python.

    Measured: ``cline`` on PATH is a shell shim, so subprocess failed with WinError 2 and the
    agent never started. A .cmd launcher must be run through cmd.exe.
    """
    candidate = cline or os.environ.get("CLINE_BIN") or ""
    if candidate and os.path.exists(candidate):
        if candidate.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", candidate]
        return [candidate]
    for base in (r"C:\Users\Admin\AppData\Local\hermes\node\cline.cmd",):
        if os.path.exists(base):
            return ["cmd.exe", "/c", base]
    return ["cline"]


def prepare_profile(data_dir: str, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
                    base_url: Optional[str] = None, cline: Optional[str] = None, timeout: int = 120) -> bool:
    """Configure one Cline data dir exactly as the delivery engine does; True when readback passes.

    Same sequence as kaggle_engine_worker.configure_cline_proxy: `auth --baseurl`, then read the
    saved file back and require model, base URL and key to be persisted. Measured: a hand-written
    providers.json lost its baseUrl when Cline re-saved it, so the file is never trusted unread.
    """
    base = base_url or os.environ.get("NVIDIA_PROXY_BASE_URL", "http://127.0.0.1:8099/v1")
    provider_file = os.path.join(data_dir, "settings", "providers.json")
    os.makedirs(data_dir, exist_ok=True)
    command = [*resolve_cline(cline), "--data-dir", data_dir, "auth", "--data-dir", data_dir,
               "--provider", "openai-compatible", "--apikey", "nvidia-pool",
               "--modelid", model, "--baseurl", base]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return False
    if done.returncode != 0:
        return False
    try:
        with open(provider_file, encoding="utf-8") as handle:
            settings = json.load(handle)["providers"]["openai-compatible"]["settings"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (settings.get("model") == model
            and str(settings.get("baseUrl", "")).rstrip("/") == base.rstrip("/")
            and settings.get("apiKey") == "nvidia-pool")


REAL_PREPARE_PROFILE = prepare_profile


def run_cline_search(workdir: str, prompt: str = SEARCH_PROMPT, timeout: int = 1800,
                     data_dir: Optional[str] = None, model: Optional[str] = None,
                     cline: Optional[str] = None, thinking: Optional[str] = None,
                     machine_json: bool = False,
                     system_prompt: Optional[str] = None) -> Dict[str, object]:
    """Engine parity: the flag set below is exactly kaggle_engine_worker.cline_worktree_command.

    Measured today, each addition broke the run: --system made Cline demand a TTY, --json with
    --thinking sent the agent exploring for a task instead of searching. The engine's plain
    invocation is the one proven to work, so it is the default here.
    """
    """Run one agent session that searches, then return what it wrote. No parsing of its prose."""
    os.makedirs(workdir, exist_ok=True)
    data_dir = data_dir or os.path.join(workdir, ".cline")
    profile_ready = prepare_profile(data_dir, model=model or "nvidia/nemotron-3.5-super-vl-120b-a12b",
                                    cline=cline)
    target = os.path.join(workdir, "shortlist.jsonl")
    if os.path.exists(target):
        os.remove(target)
    env = dict(os.environ)
    env["CLINE_DATA_DIR"] = data_dir
    env["CLINE_PROVIDER_SETTINGS_PATH"] = os.path.join(data_dir, "settings", "providers.json")
    command = [*resolve_cline(cline), "--data-dir", data_dir,
               "--provider", "openai-compatible",
               "--model", model or "nvidia/nemotron-3.5-super-vl-120b-a12b",
               "--key", "nvidia-pool", "-y", "--retries", "2",
               "-t", str(max(60, int(timeout))), "-c", workdir]
    if system_prompt:
        # Cline's default role is a coding agent in a worktree, so it goes looking for the repo and
        # concludes there is "no concrete issue". Measured: this overrides that role, nothing else.
        command += ["--system", system_prompt]
    if thinking:
        command += ["--thinking", thinking]
    if machine_json:
        command += ["--json"]  # tool records as data, not ANSI art we have to scrape
    command.append(prompt)
    # Stream the agent's thinking, the way the delivery engine streams its own Cline runs:
    # a silent buffer hides exactly the reasoning that explains a bad shortlist.
    log_path = os.path.join(workdir, "agent.log")
    transcript: List[str] = []

    def emit(stream: str, line: str) -> None:
        line = line.rstrip("\r\n")
        if not line.strip():
            return
        transcript.append(f"[{stream}] {line}")
        if len(transcript) > 4000:
            del transcript[:1000]
        # Measured: Cline prints box-drawing glyphs and Windows stdout is cp1252, so a plain
        # print() raised UnicodeEncodeError and killed the reader thread mid-run. The agent then
        # lost its stdout and returned no rows at all. Visibility must never break the run.
        try:
            print(f"CLINE {stream}: {line}", flush=True)
        except UnicodeEncodeError:
            safe = line.encode("ascii", "replace").decode("ascii")
            print(f"CLINE {stream}: {safe}", flush=True)

    try:
        process = subprocess.Popen(command, cwd=workdir, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1, env=env)
    except OSError as exc:
        return {"exit_code": -2, "rows": [], "wrote_file": False,
                "tail": f"agent could not start: {exc}",
                "preview": _preview(command)}

    readers = []
    for pipe, stream in ((process.stdout, "stdout"), (process.stderr, "stderr")):
        def collect(handle=pipe, name=stream):
            try:
                for line in iter(handle.readline, ""):
                    emit(name, line)
            finally:
                handle.close()
        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        readers.append(thread)

    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        exit_code = -1
    for thread in readers:
        thread.join(timeout=5)

    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(transcript))
    tail = ("agent timed out after %ds\n" % timeout if timed_out else "") + "\n".join(transcript[-40:])

    rows: List[dict] = []
    if os.path.exists(target):
        with open(target, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return {"exit_code": exit_code, "rows": rows, "tail": tail,
            "wrote_file": os.path.exists(target), "log": log_path,
            "preview": _preview(command), "profile_ready": profile_ready,
            "data_dir": data_dir}


def _preview(command: List[str]) -> str:
    """The command as it may be logged: key material redacted, everything else visible."""
    shown, redact_next = [], False
    for part in command:
        shown.append("[REDACTED]" if redact_next else str(part))
        redact_next = str(part).lower() in ("--key", "--apikey", "--token")
    return " ".join(shown)


def fetch_issue(repo: str, issue: int, gh: str = "gh") -> Optional[dict]:
    """The real issue, from GitHub. None means we could not prove it exists."""
    try:
        done = subprocess.run([gh, "api", f"repos/{repo}/issues/{issue}"],
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        document = json.loads(done.stdout)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


AMOUNT_RE = re.compile(
    r"(?:[$€£₹]\s?\d"          # $250, Rs 250
    r"|\d[\d,.]*\s*(?:[$€£₹]|k|usd|usdc|usdt|dai|eth|btc|sol|inr|eur|gbp|rs))",
    re.I)  # measured: a real bounty was written "14999$" and the first pattern refused it


def quote_states_an_amount(quote: str) -> bool:
    """A bounty heading with no figure is not proof of money.

    Measured on a live shortlist: "### Bounty:  USDC (Escrow Locked)" passed the literal-quote gate
    because the sentence really was in the issue, yet it names no amount at all.
    """
    return bool(AMOUNT_RE.search(quote or ""))


def verify_rows(rows: List[dict], fetch: Callable[[str, int], Optional[dict]] = fetch_issue,
                limit: int = 12) -> Dict[str, List[dict]]:
    """Admit only rows whose issue exists, is open, and whose reward quote is really there.

    The agent chose them; this decides whether the choice survives contact with the source.
    """
    admitted: List[dict] = []
    refused: List[dict] = []
    seen = set()
    for row in rows[:limit]:
        repo, number = str(row.get("repo") or ""), row.get("issue")
        if not repo or not isinstance(number, int):
            refused.append({"row": row, "reason": "MALFORMED_ROW"})
            continue
        key = (repo.lower(), number)
        if key in seen:
            refused.append({"row": row, "reason": "DUPLICATE_ROW"})
            continue
        seen.add(key)

        issue = fetch(repo, number)
        if issue is None:
            refused.append({"row": row, "reason": "ISSUE_NOT_FOUND"})
            continue
        if str(issue.get("state") or "").lower() != "open":
            refused.append({"row": row, "reason": "ISSUE_NOT_OPEN"})
            continue
        if row.get("is_code_task") is not True:
            refused.append({"row": row, "reason": "AGENT_NOT_A_CODE_TASK"})
            continue

        text = "{title}\n\n{body}".format(title=issue.get("title") or "", body=issue.get("body") or "")
        quote = str(row.get("reward_quote") or "")
        if not quote_is_present(quote, text):
            # The agent may only be quoting the title or paraphrasing; either way it is unproven.
            refused.append({"row": row, "reason": "REWARD_QUOTE_NOT_IN_ISSUE"})
            continue

        if not quote_states_an_amount(quote):
            refused.append({"row": row, "reason": "REWARD_QUOTE_HAS_NO_AMOUNT"})
            continue

        admitted.append({"repo": repo, "issue": number, "url": row.get("url") or
                         f"https://github.com/{repo}/issues/{number}",
                         "reward_quote": quote, "reward_usd": row.get("reward_usd"),
                         "scope_quote": row.get("scope_quote"), "why_now": row.get("why_now")})
    return {"admitted": admitted, "refused": refused}


FEEDBACK_PROMPT = FRESH_START + """The gates read the shortlist you wrote and refused part of it. Each refusal below is a check made against the source, so it is a fact about the row, not an opinion.

{refusals}

What each check means, when you need it:
- REWARD_QUOTE_NOT_IN_ISSUE: that sentence is not in the issue text. Copy it exactly, or drop the row.
- REWARD_QUOTE_HAS_NO_AMOUNT: the sentence is real but names no money. Find the sentence that does.
- ISSUE_NOT_FOUND, ISSUE_NOT_OPEN, AGENT_NOT_A_CODE_TASK, MALFORMED_ROW, DUPLICATE_ROW: drop the row.

Row 0 was accepted, so the shape is right. Write shortlist.jsonl again from scratch, with the
accepted rows kept and the refused ones repaired or replaced. Then finish.
"""


def fresh_workspace(root: str) -> str:
    """A new, empty directory per run. Measured: the agent ignored its instructions and read old
    files (INITIAL_PROMPT.txt, comment.json, earlier scout logs) sitting next to its workdir under
    D:/tmp. An empty workspace removes that distraction."""
    import uuid
    # normpath: mixing "D:/x" with os.path.join produced "D:/x\run-..." and Windows refused it.
    path = os.path.normpath(os.path.join(root, "run-" + uuid.uuid4().hex[:10]))
    os.makedirs(path, exist_ok=True)
    return path


TASK_FILE = """# Scout task

Find work on GitHub that pays for engineering, and record what you find. You are not asked to write
or change any code here.

## Facts about this workspace

- There is no source code in it, and nothing to fix. It is a scratch worktree.
- `gh` is installed and authenticated.
- The shell is Windows PowerShell: one command per tool call, and POSIX-only commands
  (`ls -la`, `cat`, `grep`, `&&`, `2>/dev/null`) fail here.
- Money and scope must be quoted in an issue's own words; a claim you cannot quote is not evidence.

## What to produce

`shortlist.jsonl` in this directory, one JSON object per line:

    {"repo": "owner/name", "issue": 123, "url": "https://github.com/owner/name/issues/123",
     "is_code_task": true, "reward_quote": "<sentence copied exactly from the issue>",
     "reward_usd": <number or null>, "scope_quote": "<sentence copied exactly, saying what to build>",
     "why_now": "<one short line: why this is work we can deliver>"}

Only record issues you actually opened and read. Then stop.
"""


WORKTREE_PROMPT = ("Read TASK.md in this worktree and carry it out exactly. Write shortlist.jsonl in "
                   "this directory, then finish.")


def scaffold_workspace(root: str) -> str:
    """Build the shape Cline expects: a real git worktree whose TASK.md is the job.

    Measured: with a bare empty directory the agent hunted for a repository and a task, failed with
    bash-in-PowerShell commands, and never searched. The delivery engine always hands Cline a
    worktree with the work described inside it, so the entry door hands it the same shape.
    """
    path = fresh_workspace(root)
    with open(os.path.join(path, "TASK.md"), "w", encoding="utf-8") as handle:
        handle.write(TASK_FILE)
    for git_args in (["init", "-q"], ["add", "TASK.md"],
                     ["-c", "user.email=scout@local", "-c", "user.name=scout",
                      "commit", "-q", "-m", "scout task"]):
        try:
            subprocess.run(["git", *git_args], cwd=path, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            break
    return path


def iterate(workdir: str, rounds: int = 3, run=run_cline_search, verify=verify_rows,
            limit: int = 12, first_prompt: Optional[str] = None,
            **run_kwargs) -> Dict[str, object]:
    """Search, verify, and feed the refusals back so the agent corrects itself.

    The agent is not judged once and dismissed: each round's refusals become the next round's
    instructions, which is how a search that finds unpayable rows converges instead of
    submitting them. Bounded rounds, so a stubborn agent cannot loop forever.
    """
    admitted: List[dict] = []
    history: List[dict] = []
    refusals: List[dict] = []
    for round_number in range(1, max(1, rounds) + 1):
        if round_number == 1:
            prompt = first_prompt or SEARCH_PROMPT
        else:
            listed = "\n".join(
                "- {repo}#{issue}: {reason}".format(
                    repo=str(entry["row"].get("repo")), issue=entry["row"].get("issue"),
                    reason=entry["reason"])
                for entry in refusals)
            prompt = FEEDBACK_PROMPT.format(refusals=listed or "(none)")
        outcome = run(workdir, prompt=prompt, **run_kwargs)
        result = verify(outcome.get("rows") or [], limit=limit)

        known = {(row["repo"].lower(), row["issue"]) for row in admitted}
        for row in result["admitted"]:
            if (row["repo"].lower(), row["issue"]) not in known:
                admitted.append(row)
                known.add((row["repo"].lower(), row["issue"]))
        refusals = result["refused"]
        history.append({"round": round_number, "agent_exit": outcome.get("exit_code"),
                        "rows": len(outcome.get("rows") or []),
                        "admitted": len(result["admitted"]), "refused": len(refusals)})
        if not refusals:
            break
    return {"admitted": admitted, "refused": refusals, "history": history}


def main() -> int:
    workdir = sys.argv[1] if len(sys.argv) > 1 else "D:/tmp/entry-door"
    outcome = iterate(workdir)
    for step in outcome["history"]:
        print("ROUND {round}: exit={agent_exit} rows={rows} admitted={admitted} refused={refused}"
              .format(**step))
    result = {"admitted": outcome["admitted"], "refused": outcome["refused"]}
    if not outcome["admitted"] and not outcome["refused"]:
        print("VERDICT: NO_ROWS - the agent found nothing it could prove.")
        return 1
    for row in result["admitted"]:
        print("ADMITTED {repo}#{issue} usd={usd} :: {quote}".format(
            repo=row["repo"], issue=row["issue"], usd=row.get("reward_usd"),
            quote=row["reward_quote"][:90]))
    for row in result["refused"]:
        print("REFUSED  {reason} :: {repo}".format(
            reason=row["reason"], repo=str(row["row"].get("repo"))[:40]))
    print("TOTALS admitted={a} refused={r}".format(a=len(result["admitted"]),
                                                   r=len(result["refused"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
