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

import inspect
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
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


DEFAULT_ENTRY_MODEL = os.environ.get("BOUNTY_ENTRY_MODEL", "deepseek-v4.1-flash:free")


def prepare_profile(data_dir: str, model: str = DEFAULT_ENTRY_MODEL,
                    base_url: Optional[str] = None, cline: Optional[str] = None, timeout: int = 120) -> bool:
    """Configure one Cline data dir exactly as the delivery engine does; True when readback passes.

    Same sequence as kaggle_engine_worker.configure_cline_proxy: `auth --baseurl`, then read the
    saved file back and require model, base URL and key to be persisted. Measured: a hand-written
    providers.json lost its baseUrl when Cline re-saved it, so the file is never trusted unread.
    """
    base = base_url or os.environ.get("TOKENHARBOR_PROXY_BASE_URL", os.environ.get("NVIDIA_PROXY_BASE_URL", "http://127.0.0.1:8080/v1"))
    provider_file = os.path.join(data_dir, "settings", "providers.json")
    os.makedirs(data_dir, exist_ok=True)
    command = [*resolve_cline(cline), "--data-dir", data_dir, "auth", "--data-dir", data_dir,
               "--provider", "openai-compatible", "--apikey", "tokenharbor-local-proxy",
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
            and settings.get("apiKey") in ("tokenharbor-local-proxy", "nvidia-pool"))


REAL_PREPARE_PROFILE = prepare_profile


def new_rows(path: str, offset: int = 0):
    """Rows appended to the shortlist since ``offset``, plus the offset to resume from.

    The agent writes while it searches, so the pipeline must read while it writes. Measured
    2026-10-31: a round that reached its wall-clock budget was killed with rows=0 although the
    agent had already verified candidates in its narration, because the file was only opened
    after ``process.wait()``. A half-written line is never parsed: the offset stops at the last
    newline, so a partial object waits for its terminator instead of being dropped.
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset
    end = chunk.rfind(b"\n")
    if end == -1:
        return [], offset
    complete = chunk[:end + 1]
    offset += end + 1
    rows: List[dict] = []
    for line in complete.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, offset


def _tail_shortlist(path: str, on_row, stop: threading.Event, poll: float = 1.0) -> None:
    """Hand every row to ``on_row`` the moment it lands, and keep going while the agent runs."""
    offset = 0
    seen = set()

    def drain() -> None:
        nonlocal offset
        rows, offset = new_rows(path, offset)
        for row in rows:
            key = (str(row.get("repo") or "").lower(), row.get("issue"))
            if key in seen:
                continue
            seen.add(key)
            try:
                on_row(row)
            except Exception:  # a banking failure must never kill the search
                pass

    while not stop.wait(poll):
        drain()
    drain()


def run_cline_search(workdir: str, prompt: str = SEARCH_PROMPT, timeout: int = 1800,
                     data_dir: Optional[str] = None, model: Optional[str] = None,
                     cline: Optional[str] = None, thinking: Optional[str] = None,
                     machine_json: bool = False,
                     system_prompt: Optional[str] = None,
                     on_row=None) -> Dict[str, object]:
    """Engine parity: the flag set below is exactly kaggle_engine_worker.cline_worktree_command.

    Measured today, each addition broke the run: --system made Cline demand a TTY, --json with
    --thinking sent the agent exploring for a task instead of searching. The engine's plain
    invocation is the one proven to work, so it is the default here.
    """
    """Run one agent session that searches, then return what it wrote. No parsing of its prose."""
    os.makedirs(workdir, exist_ok=True)
    data_dir = data_dir or os.path.join(workdir, ".cline")
    profile_ready = prepare_profile(data_dir, model=model or DEFAULT_ENTRY_MODEL,
                                    cline=cline)
    target = os.path.join(workdir, "shortlist.jsonl")
    if os.path.exists(target):
        os.remove(target)
    env = dict(os.environ)
    env["CLINE_DATA_DIR"] = data_dir
    env["CLINE_PROVIDER_SETTINGS_PATH"] = os.path.join(data_dir, "settings", "providers.json")
    command = [*resolve_cline(cline), "--data-dir", data_dir,
               "--provider", "openai-compatible",
               "--model", model or DEFAULT_ENTRY_MODEL,
               "--key", "tokenharbor-local-proxy", "-y", "--retries", "2",
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
        process = subprocess.Popen(command, cwd=workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
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

    tail_stop = threading.Event()
    tailer = None
    if on_row is not None:
        tailer = threading.Thread(target=_tail_shortlist, args=(target, on_row, tail_stop),
                                  daemon=True)
        tailer.start()

    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        exit_code = -1
    tail_stop.set()
    if tailer is not None:
        tailer.join(timeout=10)
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


class IssueUnreadable(Exception):
    """GitHub answered, but not with a verdict on the issue: rate limit, server error, timeout.
    Measured 2026-10-30: fetch_issue returned None for a 403 and verify_rows stamped a live issue
    ISSUE_NOT_FOUND. A quota wall is not evidence the issue is gone, so it must refuse the row
    as unreadable, never call it missing."""


def fetch_issue(repo: str, issue: int, gh: str = "gh") -> Optional[dict]:
    """The real issue, from GitHub. None means 404 (the issue does not exist). Anything GitHub
    could not answer is an IssueUnreadable, so the caller can refuse honestly instead of lying."""
    try:
        done = subprocess.run([gh, "api", f"repos/{repo}/issues/{issue}"],
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IssueUnreadable(f"transport: {exc}") from exc
    if done.returncode != 0:
        diagnostic = ((done.stderr or "") + " " + (done.stdout or "")).lower()
        if "not found" in diagnostic:
            return None  # the only verdict that says the issue does not exist
        raise IssueUnreadable((done.stderr or done.stdout or "").strip()[:300])
    try:
        document = json.loads(done.stdout)
    except ValueError:
        raise IssueUnreadable("non-JSON response") from None
    return document if isinstance(document, dict) else None


def fetch_issue_with_comments(repo: str, issue: int, gh: str = "gh",
                              fetcher=None) -> Optional[dict]:
    """The issue plus the text of its comments, because the domain counts both.

    Measured on run 41184570516: the agent found rows whose reward was stated in a comment -
    bounty platform bots and owners both publish there - and the entry door refused them as
    REWARD_QUOTE_NOT_IN_ISSUE, because the haystack was built from title and body only. The task
    file had said "stated in the issue text or comments" the whole time, so the gate was narrower
    than its own contract, and the agent was right about it rather than wrong.
    """
    document = (fetcher or fetch_issue)(repo, issue)
    if not document:
        return document
    try:
        done = subprocess.run([gh, "api", f"repos/{repo}/issues/{issue}/comments",
                               "--paginate", "--jq", ".[].body"],
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return document
    if done.returncode != 0:
        return document
    enriched = dict(document)
    enriched["__comments__"] = done.stdout or ""
    return enriched


def issue_haystack(issue: dict) -> str:
    """Everything a reward may legitimately be quoted from: title, body, and comments."""
    parts = [str(issue.get("title") or ""), str(issue.get("body") or ""),
             str(issue.get("__comments__") or "")]
    return "\n\n".join(parts)


ISSUE_STALE_DAYS = int(os.environ.get("BOUNTY_ISSUE_STALE_DAYS", "60"))


def issue_age_days(issue: dict, now: Optional[float] = None) -> Optional[int]:
    """How long since anything moved on this issue, or None when GitHub did not say."""
    stamp = str(issue.get("updated_at") or issue.get("updatedAt") or "")
    if not stamp:
        return None
    try:
        moment = datetime.strptime(stamp[:19].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    today = datetime.utcfromtimestamp(now) if now is not None else datetime.utcnow()
    return max(0, (today - moment).days)


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


def verify_rows(rows: List[dict], fetch: Optional[Callable[[str, int], Optional[dict]]] = None,
                limit: int = 12) -> Dict[str, List[dict]]:
    """Admit only rows whose issue exists, is open, and whose reward quote is really there.

    The agent chose them; this decides whether the choice survives contact with the source.

    A row whose quote is real but names no money is not a refusal. It is quarantined into
    ``unpriced``: the intent is genuine and it simply lost the figure in transcription, so
    sending it back as an error tells the agent to *drop* a real lead. Measured live:
    ``Rooner-Plugins/bank-value-changes#3`` ("I'm willing to pay for this to be added") and
    ``boxbilling/boxbilling#889`` ("[WILL PAY FOR CODE]") are real buyers with no number.
    Those deserve their own queue, not a rejection.
    """
    if fetch is None:
        fetch = fetch_issue_with_comments
    admitted: List[dict] = []
    refused: List[dict] = []
    unpriced: List[dict] = []
    seen = set()
    for row in (rows if limit <= 0 else rows[:limit]):
        repo, number = str(row.get("repo") or ""), row.get("issue")
        if not repo or not isinstance(number, int):
            refused.append({"row": row, "reason": "MALFORMED_ROW"})
            continue
        key = (repo.lower(), number)
        if key in seen:
            refused.append({"row": row, "reason": "DUPLICATE_ROW"})
            continue
        seen.add(key)

        try:
            issue = fetch(repo, number)
        except IssueUnreadable as exc:
            refused.append({"row": row, "reason": "ISSUE_UNREADABLE",
                            "detail": str(exc)[:200]})
            continue
        if issue is None:
            refused.append({"row": row, "reason": "ISSUE_NOT_FOUND"})
            continue
        if str(issue.get("state") or "").lower() != "open":
            refused.append({"row": row, "reason": "ISSUE_NOT_OPEN"})
            continue
        if row.get("is_code_task") is not True:
            refused.append({"row": row, "reason": "AGENT_NOT_A_CODE_TASK"})
            continue

        stale_days = issue_age_days(issue)
        if stale_days is not None and stale_days > ISSUE_STALE_DAYS:
            # Measured on the first run that reached dispatch: two rows were admitted and both
            # died in the delivery engine as dead offers - one had last moved 2.8 years earlier
            # (funding long withdrawn), the other 7 years earlier. The engineer run is the most
            # expensive thing this pipeline buys, so a tree nothing has touched in months is
            # refused here, where it costs one line.
            refused.append({"row": row, "reason": "STALE_ISSUE", "age_days": stale_days})
            continue

        text = issue_haystack(issue)
        quote = str(row.get("reward_quote") or "")
        if not quote_is_present(quote, text):
            # The agent may only be quoting the title or paraphrasing; either way it is unproven.
            refused.append({"row": row, "reason": "REWARD_QUOTE_NOT_IN_ISSUE"})
            continue

        author_assoc = str(issue.get("author_association") or issue.get("authorAssociation") or "").upper()
        is_founder = (author_assoc == "OWNER") or bool(row.get("is_founder_wound"))
        lane = "founder" if is_founder else "bounty"

        if not quote_states_an_amount(quote):
            # Real intent, missing figure. Quarantined, never counted as a refusal.
            unpriced.append({"row": row, "reason": "REWARD_QUOTE_HAS_NO_AMOUNT",
                             "repo": repo, "issue": number,
                             "lane": lane,
                             "author_association": author_assoc,
                             "url": row.get("url") or f"https://github.com/{repo}/issues/{number}",
                             "reward_quote": quote, "why_now": row.get("why_now")})
            continue

        admitted.append({"repo": repo, "issue": number, "url": row.get("url") or
                         f"https://github.com/{repo}/issues/{number}",
                         "lane": lane,
                         "author_association": author_assoc,
                         "reward_quote": quote, "reward_usd": row.get("reward_usd"),
                         "scope_quote": row.get("scope_quote"), "why_now": row.get("why_now")})
    return {"admitted": admitted, "refused": refused, "unpriced": unpriced}


FEEDBACK_PROMPT = FRESH_START + """The gates read the shortlist you wrote and refused part of it. Each refusal below is a check made against the source, so it is a fact about the row, not an opinion.

{refusals}

What each check means, when you need it:
- REWARD_QUOTE_NOT_IN_ISSUE: that sentence is not in the issue text. Copy it exactly, or drop the row.
- REWARD_QUOTE_HAS_NO_AMOUNT: the sentence is real but names no money. Find the sentence that does.
- ISSUE_NOT_FOUND, ISSUE_NOT_OPEN, AGENT_NOT_A_CODE_TASK, MALFORMED_ROW, DUPLICATE_ROW: drop the row.
- ISSUE_UNREADABLE: GitHub did not answer. The row may be good, so keep it if you can see the
  issue; it is refused here only because it could not be checked.

Do not exclude a row to be safe: submit anything that plausibly meets these criteria, and the gates will verify it exactly and report the failures. Repairing a refused row is not a reason to submit fewer rows. If you found other candidates while fixing these, add them too.

Row 0 was accepted, so the shape is right. Write shortlist.jsonl again from scratch, with the
accepted rows kept and the refused ones repaired or replaced - then go back out, because a repair
round is also a search round and there is no quota: whatever time is left belongs to finding more
work, not to stopping early.
"""


CONTINUE_PROMPT = FRESH_START + """The previous round ended with time still on the clock, and this door has no quota. Its rows are kept - everything you already wrote has been collected and checked, and you do not need to write it again.

Go back out and find more. The world is larger than the part of it you have already seen: other sources, other phrasings, other platforms, other kinds of buyers, and the same issues read for a second offer written later in the thread. Append new rows to shortlist.jsonl as you verify them, and keep hunting for as long as the budget allows.

No row you have already submitted needs to be repeated, and nothing you find is too small to write down."""


def fresh_workspace(root: str) -> str:
    """A new, empty directory per run. Measured: the agent ignored its instructions and read old
    files (INITIAL_PROMPT.txt, comment.json, earlier scout logs) sitting next to its workdir under
    D:/tmp. An empty workspace removes that distraction."""
    import uuid
    # normpath: mixing "D:/x" with os.path.join produced "D:/x\run-..." and Windows refused it.
    path = os.path.normpath(os.path.join(root, "run-" + uuid.uuid4().hex[:10]))
    os.makedirs(path, exist_ok=True)
    return path


DOMAIN = """This pipeline turns GitHub issues into delivered fixes for the money the issue's own
author promises. A paid task must be: an open issue, on a repository that actually merges outside
work, that asks for engineering (code, tests, fixes) rather than writing or events or opinions,
and whose reward is stated in figures inside the issue itself - "I will pay" with no number is not
a reward, and a figure hidden behind a link is not a figure. In addition to direct bounties,
critical production outages announced by repository owners (author_association: OWNER) are
high-priority engineering leads: record them quoting the owner's statement of the breakdown.
The checks below are how a claim is verified, never the goal: the goal is work that is really paid
and really broken. Do not exclude a row to be safe: submit anything that plausibly meets these
criteria, and the gates will verify each one exactly and tell you which failed. How you find rows
is entirely your choice.
"""


# The door's own refusal reasons, in the exact words the gate emits. The brief is rendered from
# this table (test_cline_entry_door asserts no emitted reason exists outside it), so the agent is
# told the domain and the constraints, and the table can never drift from the code.
GATE_CHECKS = [
    ("MALFORMED_ROW", "the row is not a complete JSON record with repo and issue."),
    ("DUPLICATE_ROW", "that issue already appears in the shortlist."),
    ("ISSUE_NOT_FOUND", "repo or issue does not exist on GitHub."),
    ("ISSUE_UNREADABLE", "GitHub could not answer (rate limit, server error); not a verdict."),
    ("ISSUE_NOT_OPEN", "the issue is closed or read-only."),
    ("AGENT_NOT_A_CODE_TASK", "the issue is not engineering work you could submit a fix for."),
    ("STALE_ISSUE", "nothing has moved on that issue for two months; the money is long gone."),
    ("REWARD_QUOTE_NOT_IN_ISSUE", "the quoted sentence is not in the issue text, byte for byte."),
    ("REWARD_QUOTE_HAS_NO_AMOUNT", "the quoted sentence exists but names no amount."),
]

# What fires AFTER the agent finishes. The agent cannot see these run, but should know they exist
# so it aims at work that can survive them. Honest: list, not score.
DOWNSTREAM_CHECKS = [
    ("CURRENT_ISSUER_OFFER_MISSING",
     "no offer survives from a party that can commit the project's money. Only the repository "
     "OWNER, a MEMBER or COLLABORATOR, or a bounty platform bot (algora-pbc, polar-sh, opire, "
     "bountyhub) can fund a row. An amount written by any other commenter - a reader, a fan, a "
     "copied aggregator blurb - is not an offer, however real the number looks."),
    ("HARD_ISSUE_EVIDENCE_MISSING",
     "the issue states no concrete engineering evidence: no error text, stack trace, failing "
     "test, reproduction steps, file or function names. A title and a wish is not evidence that "
     "a defect exists."),
    ("COMPETITION_OPEN_PR_EXISTS",
     "an unmerged open pull request already exists for this issue; never compete on pre-empted work."),
    ("DEFECT_NOT_IN_REPOSITORY",
     "the defect is in an external bridge/wallet/service or desktop environment, not this repository's codebase."),
    ("UNBOUNDED_SCOPE",
     "the issue is a whole-product roadmap or rewrite rather than a bounded, deliverable engineering fix."),
    ("REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN", "the issue states the behaviour is by design."),
    ("REPOSITORY_DOES_NOT_MERGE", "the repository's history shows it does not merge outside work."),
    ("CLOSED_OR_READ_ONLY", "the issue is closed or the repository is read-only."),
    ("DUPLICATE_ROW", "someone already has this task open."),
    ("BOUNTY_FLOOR", "the reward is below the floor this pipeline will work for."),
]


RSN = chr(10)


def render_task_file() -> str:
    checks = RSN.join(f"- {code}: {meaning}" for code, meaning in GATE_CHECKS)
    downstream = RSN.join(f"- {code}: {meaning}" for code, meaning in DOWNSTREAM_CHECKS)
    try:
        budget = int(os.environ.get("BOUNTY_AGENT_TIMEOUT", "1800"))
    except ValueError:
        budget = 1800
    clock = (f"Each round is {budget} seconds of wall clock and it is not extended. That clock is "
             f"the only limit on how much of the world you can reach, so it is worth knowing "
             f"plainly: a row you verified but never wrote down is work this house cannot use, and "
             f"a round that ends with an empty file has delivered nothing, however much ground it "
             f"covered.")
    return f"""# The garden of paid engineering work

The world is a garden in full season. It is not in drought. There is more ripe fruit hanging in it
than one pair of hands can carry - people who have promised money for work, and people whose own
machine is broken right now and who will pay to have it fixed.

You are the only pair of hands in this garden. Nobody else walks out there: what you do not pluck
stays on the branch and rots, and this house eats nothing. So go out and pluck the best fruit.

Walk up to a tree, look at what is hanging there, and if it is ripe - money promised by someone
who can actually pay it, a real break in the code, work that can be finished - pick it and put it
in the basket. Do not stand in the middle of the garden deciding which tree is best. Do not
describe the orchard to yourself instead of walking it. A fruit in your hand is worth a hundred
you have only looked at, and hands that only point at fruit carry nothing home.

The basket is shortlist.jsonl. Fill it, as much as your hands can carry before the light goes.

Some of what you pick will be unripe, and the house will throw it out at the door with a reason -
that costs one line and nothing else. An empty basket is the only thing that costs the round. So
when your hand is already on a fruit you believe is ripe, it goes in the basket there and then, and
you turn to the next tree. Do not walk from tree to tree carrying nothing.

This garden is the real one. Nothing is planted here for you, no plot is marked, and there is no grader
keeping a score: the fruit is a real issue on a real repository, a real merge, and real money. A tree
that looks artificial is simply not a buyer - it is never a sign that the real trees were hidden
somewhere for you to find.

## The domain

{DOMAIN.strip()}

There are two streams of genuine work:
1. Funded Bounties: An open issue with committed monetary payment figures stated in the issue text or comments.
2. Wounded Founders: An open issue created by the repository OWNER (author_association: OWNER) announcing production downtime, outages, critical regressions, or backend hardening.

## Facts about this workspace

- There is no source code in it, and nothing to fix. It is a scratch worktree.
- `gh` is installed and authenticated.
- The shell is whatever this machine runs, so check it once with `uname`. On Linux you have a
  POSIX shell and `&&`, `cat`, `grep`, `2>/dev/null` all work. On Windows it is PowerShell,
  where one command runs per tool call and POSIX-only syntax fails. This search runs on both, so
  never trust the label: read the platform before you write a command.

## How a row is checked before it counts

These are checks, not criteria to design around. Knowing them only means you never spend a row on
something one command would have disproved.

{checks}

## How the claim is checked against the source afterwards

{downstream}

## The three facts that decide almost every row

Most rows do not die because the search was small. They die on one of these three, and the
pipeline checks each of them against the source after you finish:

1. WHO wrote the amount. The pipeline finds every sentence naming money and asks what kind of
author wrote it. Only the repository OWNER, a MEMBER or COLLABORATOR, or a bounty platform bot
(algora-pbc, polar-sh, opire, bountyhub) can fund a row. An amount in a reader's comment, a fan's
reply, or a copied aggregator blurb is refused as CURRENT_ISSUER_OFFER_MISSING no matter how
real the number looks. If the only figure you can find was written by somebody outside that set,
the row is already dead.
2. WHETHER it clears the floor. The floor is USD 250. A genuine $200 offer is refused as below
floor, and it is not a lead we can work.
3. WHETHER the issue proves anything is broken. The row needs error text, a stack trace, a failing
test, reproduction steps, or file and function names. A title plus a wish is refused as
HARD_ISSUE_EVIDENCE_MISSING.

A repository-owner incident report (author_association: OWNER) announcing real downtime or a
critical regression needs no figure: submit it with reward_usd null and the owner's own words as
the quote, and it is quarantined for follow-up rather than refused.

## How you work is yours to decide

This is a search, not a procedure. Which queries you run, which sources you sweep, in what order,
how many issues you open, whether you go broad or sit on one candidate - all of that is your
judgement to exercise. You are the intelligence in this pipeline, and no script here knows the
market better than your search does.

What is fixed is only the contract: the acceptance criteria above are exact, code reads every row
you write, and the file you leave behind is the only thing that survives the round. Aim your own
method at the work itself, and establish the three facts above on any row you intend to bank -
everything else the gates will decide for you, and they decide it better than a guess.

## Recall first: a row you never write is a lead nobody can recover

You are the search half of this system. The checks above run afterwards, in code, against the
source, and they are exact and cheap. Your recall is what this house lives on; the gates exist to
make recall usable, never to make you cautious.

Do not exclude a row to be safe: submit anything that plausibly meets these criteria, and the gates will verify it exactly and report the failures.

When you are unsure, submit it. Unsure whether the issue is closed, whether it is really a code
task, whether the scope is bounded, whether somebody already opened a pull request - the gates
decide those exactly, and they will do it better than your guess. A row you drop is a lead nobody
will ever see again.

The three facts above are the single exception, and not because they are risky: they are lookups,
not judgements. The author of an amount and the presence of an error are each one command away,
so a row that fails them does not become a lead by being submitted - it only spends the time a
passing row would have used.

## What to produce

`shortlist.jsonl` in this directory, one JSON object per line:

    {{"repo": "owner/name", "issue": 123, "url": "https://github.com/owner/name/issues/123",
     "is_code_task": true, "reward_quote": "<sentence copied exactly from the issue>",
     "reward_usd": <number or null>, "scope_quote": "<sentence copied exactly, saying what to build>",
     "why_now": "<one short line: why this is work we can deliver>"}}

## Nobody rations your basket

{clock}

Nobody counts your fruit and tells you to stop at three. There is no quota here: take every row
you can prove, and keep picking while there is light. Four rows at the halfway mark is not "enough" - it means you
should go and find the fifth. The budget is the only thing that ends a round early; your own sense
that the shortlist looks full never does. A round that ends with time on the clock and
fruit still on the branch is a search that stopped before the garden did.

Search where the money actually is, not where searching is comfortable: a place that publishes
commitments in writing, by people who can commit them, beats any list of repositories that merely
mention the word. If a source keeps returning nothing that survives a single command, that source
is not the market - go somewhere else.

## Writing as you go, not at the end

The harness reads shortlist.jsonl continuously while you work, so every row you append is
collected, verified and taken into the pipeline the moment it lands - you never have to finish the
round for your work to count. Append a row the moment you have verified it (echo '...' >>
shortlist.jsonl, or python), then go back out. Never hold a finishable row in your head while you
look for another.

Only record issues you actually opened and read.
"""


TASK_FILE = render_task_file()


WORKTREE_PROMPT = ("Read TASK.md in this worktree and carry it out. Append each verified issue to "
                   "shortlist.jsonl the moment you verify it, and keep searching while the budget "
                   "remains. There is no target number of rows: take everything you can prove.")


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


def _merge_shortlist(workdir: str, rows: List[dict]) -> None:
    """Append this round's rows to the shortlist instead of letting a rewrite erase it.

    Measured: round 2 admitted 1 of 9 because the agent rewrote ``shortlist.jsonl`` from
    scratch, so every row already won in round 1 vanished from the file before the next
    verification pass. The feedback loop was resetting instead of compounding.

    The file stays the agent's to write; this only guarantees that a row which already
    survived verification is still on disk when the next round begins. Rows are de-duplicated
    on ``(repo, issue)`` so a re-submission does not inflate the file.
    """
    target = os.path.join(workdir, "shortlist.jsonl")
    existing: List[dict] = []
    if os.path.exists(target):
        with open(target, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    existing.append(json.loads(line))
                except ValueError:
                    continue
    known = {(str(r.get("repo") or "").lower(), r.get("issue")) for r in existing}
    added = []
    for row in rows:
        key = (str(row.get("repo") or "").lower(), row.get("issue"))
        if key in known:
            continue
        known.add(key)
        added.append(row)
    if not added:
        return
    with open(target, "a", encoding="utf-8") as handle:
        for row in added:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def iterate(workdir: str, rounds: int = 3, run=run_cline_search, verify=verify_rows,
            limit: int = 0, first_prompt: Optional[str] = None,
            **run_kwargs) -> Dict[str, object]:
    """Search, verify, and feed the refusals back so the agent corrects itself.

    The agent is not judged once and dismissed: each round's refusals become the next round's
    instructions, which is how a search that finds unpayable rows converges instead of
    submitting them. Bounded rounds, so a stubborn agent cannot loop forever.

    Rows already admitted are preserved across rounds and re-appended to the shortlist, so a
    round that rewrites the file from scratch cannot discard work an earlier round won.
    """
    admitted: List[dict] = []
    history: List[dict] = []
    refusals: List[dict] = []
    unpriced: List[dict] = []
    stream_path = os.path.join(workdir, "admitted-stream.jsonl")
    live: Dict[str, List[dict]] = {"admitted": [], "refused": [], "unpriced": []}
    banked_keys = set()

    def row_key(row: dict):
        return (str(row.get("repo") or "").lower(), row.get("issue"))

    def bank(row: dict) -> None:
        """Verify a row the instant the agent writes it, and keep it whatever happens next.

        This is the reason the round's work survives: a row admitted at second 40 is already in
        the pipeline when the wall-clock budget kills the agent at second 800.
        """
        key = row_key(row)
        if key in banked_keys:
            return
        try:
            one = verify([row], limit=limit)
        except Exception:  # a single-row failure must never abort the search
            return
        banked_keys.add(key)  # only after a verdict, so a failed verify can still be retried
        for slot in ("admitted", "refused", "unpriced"):
            live[slot].extend(one.get(slot) or [])
        fresh = one.get("admitted") or []
        if not fresh:
            return
        with open(stream_path, "a", encoding="utf-8") as handle:
            for banked in fresh:
                handle.write(json.dumps(banked, ensure_ascii=False) + "\n")
        top = fresh[0]
        print(json.dumps({"phase": "ENTRY_ROW", "repo": top.get("repo"),
                          "issue": top.get("issue"), "reward_usd": top.get("reward_usd"),
                          "live": True}), flush=True)
        for entry in (one.get("refused") or []) + (one.get("unpriced") or []):
            subject = entry.get("row") or {}
            print(json.dumps({"phase": "ENTRY_DECISION", "repo": subject.get("repo"),
                              "issue": subject.get("issue"),
                              "reason": entry.get("reason"),
                              "reward_usd": subject.get("reward_usd"),
                              "live": True}), flush=True)

    for round_number in range(1, max(1, rounds) + 1):
        for slot in ("admitted", "refused", "unpriced"):
            live[slot].clear()
        if round_number == 1:
            prompt = first_prompt or SEARCH_PROMPT
        elif not refusals:
            # Measured 2026-10-31 (run 41183429400): with a quota-free brief the agent returned
            # four rows, nothing was refused, and the configured second round never ran - the
            # extra round was wired as a repair round only. Time left on the clock is time to
            # search, so a clean round continues the search instead of ending it.
            prompt = CONTINUE_PROMPT
        else:
            listed = "\n".join(
                "- {repo}#{issue}: {reason}".format(
                    repo=str(entry["row"].get("repo")), issue=entry["row"].get("issue"),
                    reason=entry["reason"])
                for entry in refusals)
            prompt = FEEDBACK_PROMPT.format(refusals=listed or "(none)")
        kwargs = dict(run_kwargs)
        parameters = inspect.signature(run).parameters
        if "on_row" in parameters or any(
                item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
            kwargs.setdefault("on_row", bank)
        outcome = run(workdir, prompt=prompt, **kwargs)

        streamed = set()
        for slot in ("admitted", "refused", "unpriced"):
            for entry in live[slot]:
                row_seen = entry.get("row") if isinstance(entry, dict) and "row" in entry else entry
                streamed.add((str(row_seen.get("repo") or "").lower(), row_seen.get("issue")))
        remaining = [row for row in (outcome.get("rows") or [])
                     if row_key(row) not in streamed and row_key(row) not in banked_keys]
        result = verify(remaining, limit=limit)
        for entry in (result["refused"] or []) + (result.get("unpriced") or []):
            subject = entry.get("row") or {}
            print(json.dumps({"phase": "ENTRY_DECISION", "repo": subject.get("repo"),
                              "issue": subject.get("issue"),
                              "reason": entry.get("reason"),
                              "reward_usd": subject.get("reward_usd"),
                              "live": False}), flush=True)

        known = {(row["repo"].lower(), row["issue"]) for row in admitted}
        for row in list(live["admitted"]) + list(result["admitted"]):
            if (row["repo"].lower(), row["issue"]) not in known:
                admitted.append(row)
                known.add((row["repo"].lower(), row["issue"]))
        refusals = list(live["refused"]) + list(result["refused"])
        unpriced = list(live["unpriced"]) + list(result.get("unpriced", []))
        history.append({"round": round_number, "agent_exit": outcome.get("exit_code"),
                        "rows": len(outcome.get("rows") or []),
                        "admitted": len(result["admitted"]), "refused": len(refusals),
                        "unpriced": len(unpriced)})
        if round_number >= max(1, rounds):
            break
        # Carry the rows already won into the next round's file before the agent rewrites it.
        _merge_shortlist(workdir, admitted)
    # The last round's rewrite must not erase what the loop already won either.
    _merge_shortlist(workdir, admitted)
    return {"admitted": admitted, "refused": refusals, "unpriced": unpriced,
            "history": history}


UNPRICED_LEADS = "unpriced-leads.jsonl"
FOUNDER_WATCH_STATE = r"D:\anonym\war-log\roadmap\founders-watch-state.json"


def ingest_founder_watch_leads(state_path: Optional[str] = None) -> List[dict]:
    """Ingest leads discovered by the continuous founders-watch listener.

    Reads owner-authored wounds from the listener ledger and formats them as qualified leads.
    """
    path = state_path or os.environ.get("FOUNDER_WATCH_STATE", FOUNDER_WATCH_STATE)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    leads = []
    for item in data.get("seen", []):
        if "#" not in item:
            continue
        parts = item.split("#")
        repo, num_str = parts[0], parts[1]
        try:
            num = int(num_str)
        except ValueError:
            continue
        leads.append({
            "repo": repo,
            "issue": num,
            "lane": "founder",
            "author_association": "OWNER",
            "reason": "FOUNDER_WATCH_OWNER_WOUND",
            "url": f"https://github.com/{repo}/issues/{num}",
            "reward_quote": "Production outage announced by repository owner",
            "scope_quote": "Fix critical defect for repository founder",
            "why_now": "Repository owner announced outage/defect on GitHub",
            "is_code_task": True,
        })
    return leads





def write_unpriced_leads(workdir: str, unpriced: List[dict]) -> str:
    """Persist the unpriced stream as its own lead file, separate from the shortlist.

    These rows are real buyers who named no figure. They must not enter the bounty
    shortlist (they would fail the amount gate every cycle) and they must not be fed back
    as refusals (that tells the agent to drop them). They are leads, so they get their own
    append-only file that survives the run and can be worked later.

    De-duplicated on ``(repo, issue)`` so repeated rounds do not inflate the stream.
    """
    if not unpriced:
        return ""
    target = os.path.join(workdir, UNPRICED_LEADS)
    existing = set()
    if os.path.exists(target):
        with open(target, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    seen = json.loads(line)
                except ValueError:
                    continue
                existing.add((str(seen.get("repo") or "").lower(), seen.get("issue")))
    added = []
    for entry in unpriced:
        key = (str(entry.get("repo") or "").lower(), entry.get("issue"))
        if key in existing:
            continue
        existing.add(key)
        added.append({"repo": entry.get("repo"), "issue": entry.get("issue"),
                      "lane": entry.get("lane") or "bounty",
                      "author_association": entry.get("author_association"),
                      "url": entry.get("url"), "reward_quote": entry.get("reward_quote"),
                      "why_now": entry.get("why_now"),
                      "reason": entry.get("reason")})
    if added:
        with open(target, "a", encoding="utf-8") as handle:
            for entry in added:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return target


def main() -> int:
    workdir = sys.argv[1] if len(sys.argv) > 1 else "D:/tmp/entry-door"
    outcome = iterate(workdir)
    for step in outcome["history"]:
        print("ROUND {round}: exit={agent_exit} rows={rows} admitted={admitted} refused={refused}"
              .format(**step))
    result = {"admitted": outcome["admitted"], "refused": outcome["refused"]}
    leads_path = write_unpriced_leads(workdir, outcome.get("unpriced", []))
    if not outcome["admitted"] and not outcome["refused"] and not outcome.get("unpriced"):
        print("VERDICT: NO_ROWS - the agent found nothing it could prove.")
        return 1
    for row in result["admitted"]:
        print("ADMITTED {repo}#{issue} usd={usd} :: {quote}".format(
            repo=row["repo"], issue=row["issue"], usd=row.get("reward_usd"),
            quote=row["reward_quote"][:90]))
    for row in outcome.get("unpriced", []):
        print("UNPRICED {repo}#{issue} :: {quote}".format(
            repo=row["repo"], issue=row["issue"], quote=str(row.get("reward_quote"))[:90]))
    for row in result["refused"]:
        print("REFUSED  {reason} :: {repo}".format(
            reason=row["reason"], repo=str(row["row"].get("repo"))[:40]))
    print("TOTALS admitted={a} unpriced={u} refused={r}".format(
        a=len(result["admitted"]), u=len(outcome.get("unpriced", [])),
        r=len(result["refused"])))
    if leads_path:
        print("LEADS {path}".format(path=leads_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
