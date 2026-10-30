"""Intelligence layer for discovery search: which queries to run, decided from measured yield.

Before this module the discovery lanes ran a fixed round-robin over static strings in
``bounty_queries.json``. A static list cannot learn: an expression that returns nothing useful
keeps its slot forever, and a new niche is never found unless someone types it in. This module
replaces the choice of expression, not the search itself.

Three parts, each failing closed to the static behaviour:

1. Yield ledger. Every expression that ran is scored from what it returned: how many issues
   survived, how many reached a dispatch-ready candidate, how many were refused. The score is
   measured from our own receipts, never from an assumed prior.
2. Proposer. Nemotron (NVIDIA NIM) reads the lane's purpose, the expressions already run with
   their measured yield, and the refusal reasons seen, then proposes new GitHub search
   expressions. Its output is untrusted text: every proposal passes the same syntax check the
   static queries pass, and is refused if it is empty, oversized, or asks for something GitHub
   search does not support.
3. Selector. Mixes exploitation (highest measured yield) with exploration (proposals and
   never-tried expressions), so the planner keeps finding new niches without abandoning proven
   ones.

Any failure - no key, network error, unparseable reply, every proposal rejected - returns the
static queries, and the caller logs which path was taken. The pipeline never stops for lack of
intelligence; it just runs the old behaviour.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

NIM_URL = os.environ.get("NIM_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
NIM_MODEL = os.environ.get("NIM_PLANNER_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
NIM_FALLBACK = os.environ.get("NIM_PLANNER_FALLBACK", "nvidia/nemotron-3-ultra-550b-a55b")
MAX_EXPRESSION_CHARS = 180
MAX_PROPOSALS_PER_CALL = 8
EXPLORE_SHARE = 0.4  # fraction of slots given to proposals and untried expressions
PROPOSER_TIMEOUT_S = 90

# Search syntax GitHub accepts that a proposal may legitimately use. Anything else in a proposal
# is treated as hallucinated and dropped rather than sent to the search API.
_ALLOWED_QUALIFIERS = {
    "is", "label", "in", "repo", "org", "user", "commenter", "language", "no", "created",
    "updated", "comments", "state", "author", "mentions", "linked", "type", "milestone",
    "sort", "assignee",
}
_QUALIFIER_RE = re.compile(r"(?<![\w:])-?([a-z]+):")
_ALLOWED_CHARS_RE = re.compile(r"^[\x20-\x7e]+$")  # printable ASCII only


def validate_expression(expression: str) -> tuple[bool, str]:
    """Reject anything a search API would choke on or that is not a search at all."""
    if not isinstance(expression, str):
        return False, "not_a_string"
    text = expression.strip()
    if not text:
        return False, "empty"
    if len(text) > MAX_EXPRESSION_CHARS:
        return False, "too_long"
    if not _ALLOWED_CHARS_RE.match(text):
        return False, "non_ascii_or_control"
    if text.count('"') % 2:
        return False, "unbalanced_quotes"
    for qualifier in _QUALIFIER_RE.findall(text):
        if qualifier not in _ALLOWED_QUALIFIERS:
            return False, f"unknown_qualifier:{qualifier}"
    if "is:issue" not in text and "is:pr" not in text and "type:issue" not in text:
        # Every lane searches issues; an expression without a type gate would return PRs too.
        return False, "no_issue_type_gate"
    return True, "ok"


def load_ledger(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def record_yield(ledger: dict, lane: str, expression: str, *, returned: int, saturated: bool) -> None:
    """Record one search run: how much it returned and whether GitHub saturated.

    Volume is recorded for diagnosis only. It does not feed the score; outcomes do (set_outcomes).
    """
    key = f"{lane}|{expression}"
    entry = ledger.setdefault(key, {"lane": lane, "expression": expression, "runs": 0,
                                    "returned": 0, "saturated_runs": 0, "last_run": 0.0})
    entry["runs"] += 1
    entry["returned"] += int(returned)
    entry["saturated_runs"] += int(bool(saturated))
    entry["last_run"] = time.time()


def set_outcomes(ledger: dict, lane: str, expression: str, *, tasks: int, dispatched: int,
                 refused: int) -> None:
    """Record what an expression's tasks became. Counts are SET, not incremented.

    The caller recomputes them from the durable task table on every run, so re-counting the same
    history never double-credits an expression. ``tasks`` is every distinct issue the expression
    surfaced; ``dispatched`` reached engineering; ``refused`` was turned away at admission or by
    the engineer.
    """
    key = f"{lane}|{expression}"
    entry = ledger.setdefault(key, {"lane": lane, "expression": expression, "runs": 0,
                                    "returned": 0, "saturated_runs": 0, "last_run": 0.0})
    entry["tasks"] = int(tasks)
    entry["dispatched"] = int(dispatched)
    entry["refused"] = int(refused)


ATTRIBUTION_SQL = """
    SELECT te.lane, te.expression, COUNT(DISTINCT te.task_id),
           SUM(CASE WHEN tof.outcome IN ('dispatched', 'refused_after_dispatch') THEN 1 ELSE 0 END),
           SUM(CASE WHEN tof.outcome = 'refused' OR p.status LIKE 'rejected%'
                         OR p.status LIKE 'query_excluded%' OR p.status LIKE 'current%'
                    THEN 1 ELSE 0 END),
           SUM(CASE WHEN tof.outcome = 'refused_after_dispatch' THEN 1 ELSE 0 END)
    FROM task_expression te
    LEFT JOIN task_outcome tof ON tof.task_id = te.task_id
    LEFT JOIN pending p ON p.task_id = te.task_id
    GROUP BY te.lane, te.expression
"""


def attribute(con, ledger: dict) -> int:
    """Credit each expression with what its tasks became, from the local tables only.

    Returns the number of expressions credited. Pure SQL joins: no API calls, so it cannot
    spend the rate limit the discovery run depends on.
    """
    rows = con.execute(ATTRIBUTION_SQL).fetchall()
    for lane, expression, tasks, dispatched, refused, wasted in rows:
        set_outcomes(ledger, lane, expression, tasks=tasks or 0,
                     dispatched=dispatched or 0, refused=refused or 0)
        # Reported, not scored: the work did reach engineering, and a post-dispatch refusal is
        # the engineer's judgement, not evidence the query was wrong.
        ledger[f"{lane}|{expression}"]["wasted"] = wasted or 0
    return len(rows)


# Prior for an expression with no record: a 20% dispatch rate, weighted as 30 tasks. A
# measured record has to beat this prior to outrank it. Without the prior, one lucky task
# (1 of 1 dispatched) would look better than 8 of 30.
PRIOR_RATE = 0.2
PRIOR_TASKS = 30.0


def score(entry: dict) -> float:
    """Smoothed dispatch rate per surfaced task, penalised by refusals.

    Measures what an expression is worth: of the issues it finds, how many reach engineering.
    Volume is deliberately not rewarded: 1,000 refused issues are worth less than 5 that ship.
    """
    tasks = max(entry.get("tasks", 0), 0)
    dispatched = max(entry.get("dispatched", 0), 0)
    refused = max(entry.get("refused", 0), 0)
    smoothed = (dispatched + PRIOR_RATE * PRIOR_TASKS) / (tasks + PRIOR_TASKS)
    refusal_rate = refused / tasks if tasks else 0.0
    return smoothed - 0.5 * refusal_rate


def propose(lane: str, purpose: str, ledger_rows: list[dict], refusal_reasons: list[str],
            api_key: str) -> tuple[list[str], str]:
    """Ask Nemotron for new GitHub search expressions. Returns (proposals, path_taken)."""
    if not api_key:
        return [], "no_key"
    best = sorted(ledger_rows, key=score, reverse=True)[:12]
    evidence = [
        {"expression": r["expression"], "issues_found": r.get("tasks", 0),
         "dispatched": r.get("dispatched", 0), "refused": r.get("refused", 0),
         "refused_after_dispatch": r.get("wasted", 0)}
        for r in best
    ]
    prompt = (
        "You design GitHub issue-search expressions for a lane that finds open issues where a "
        "paid bounty is attached and a concrete code change is requested.\n"
        f"LANE: {lane}\nPURPOSE: {purpose}\n"
        "Qualifiers allowed: is:issue is:open label: in:title in:body in:comments commenter: "
        "repo: org: language: no: created: updated: comments:. Include is:issue and is:open.\n"
        f"EXPRESSIONS ALREADY RUN WITH MEASURED YIELD (JSON): {json.dumps(evidence)}\n"
        f"REFUSAL REASONS SEEN (the engineer refused these as not code work): "
        f"{json.dumps(refusal_reasons[:12])}\n"
        f"Propose up to {MAX_PROPOSALS_PER_CALL} NEW expressions. Do NOT just vary one term "
        "(for example label:bounty crossed with a language) - that is what the evidence already "
        "shows does not produce new work. Each proposal must differ in its SOURCE vocabulary: "
        "a bounty platform or bot name, a dollar or reward phrasing used in comments "
        "(e.g. a reward amount in the body or a comment by a bounty bot), a maintainer phrase "
        "such as 'bounty available' or 'funded', a specific product area, or an in:comments "
        "search for a claim/reward bot. Avoid any expression already listed. "
        "Reply with ONLY a JSON array of strings, no prose."
    )
    for model, path in ((NIM_MODEL, "nemotron_primary"), (NIM_FALLBACK, "nemotron_fallback")):
        try:
            text = _chat(model, prompt, api_key)
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as exc:
            last = f"{path}_error:{type(exc).__name__}"
            continue
        proposals = _parse_array(text)
        if proposals:
            return proposals[:MAX_PROPOSALS_PER_CALL], path
        last = f"{path}_unparseable"
    return [], last


def _chat(model: str, prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": model, "max_tokens": 900, "temperature": 0.6,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")
    req = urllib.request.Request(NIM_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=PROPOSER_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"].get("content") or ""


def _parse_array(text: str) -> list[str]:
    """Pull the first JSON array out of the reply and keep only strings that validate."""
    match = re.search(r"\[.*\]", text, flags=re.S)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except ValueError:
        return []
    if not isinstance(raw, list):
        return []
    kept, seen = [], set()
    for item in raw:
        ok, _ = validate_expression(item)
        if ok and item.strip() not in seen:
            seen.add(item.strip())
            kept.append(item.strip())
    return kept


def plan(lane: str, static_queries: list[str], ledger: dict, *, slots: int, purpose: str,
         refusal_reasons: list[str], api_key: str, rng: random.Random | None = None
         ) -> tuple[list[str], dict]:
    """Choose ``slots`` expressions for one lane. Returns (expressions, audit).

    The audit records which path produced each slot, so the run receipt shows whether the
    planner decided anything or the static fallback ran.
    """
    rng = rng or random.Random()
    rows = [v for v in ledger.values() if v.get("lane") == lane]
    # Exploit only what has actually dispatched work. An expression that has only returned
    # issues is not proven, however many times it ran.
    proven = sorted((r for r in rows if r.get("dispatched", 0) > 0), key=score, reverse=True)
    tried = {r["expression"] for r in rows}
    untried = [q for q in static_queries if q not in tried]

    exploit_slots = max(0, slots - max(1, round(slots * EXPLORE_SHARE)))
    explore_slots = slots - exploit_slots

    chosen: list[str] = []
    audit = {"lane": lane, "exploit": [], "explore": [], "proposer": None}

    for row in proven[:exploit_slots]:
        chosen.append(row["expression"])
        audit["exploit"].append(row["expression"])

    proposals, path = propose(lane, purpose, rows, refusal_reasons, api_key)
    audit["proposer"] = path
    pool = [p for p in proposals if p not in chosen]
    if not pool:
        pool = [q for q in untried if q not in chosen]
        audit["proposer_fallback_pool"] = "untried_static"
    if not pool:
        # Nothing new anywhere: revisit the static list in a shuffled order so no single
        # static query starves, rather than cycling the same prefix forever.
        pool = [q for q in static_queries if q not in chosen]
        rng.shuffle(pool)
        audit["proposer_fallback_pool"] = "static_shuffled"

    for expression in pool:
        if len(chosen) >= slots:
            break
        chosen.append(expression)
        audit["explore"].append(expression)

    # If exploitation ran short (few proven expressions), top up from the static list.
    for expression in static_queries:
        if len(chosen) >= slots:
            break
        if expression not in chosen:
            chosen.append(expression)
            audit["explore"].append(expression)

    return chosen[:slots], audit
