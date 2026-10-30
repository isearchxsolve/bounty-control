"""Report the conversion state of every pull request this house has published.

Why this exists (measured 2026-10-30): the funnel can prepare cheaper and refuse smarter, and the
metric - "qualified candidates that produced a reviewable upstream patch" - still reads 1, because
`fyne-io/fyne#6637` has been open, mergeable and 13/13 green since 2026-10-28 with **zero reviews**.
Nothing in the house watches a published PR, so nothing notices a PR that is waiting for a human,
and nothing asks a human to look.

This lane is read-only. It never comments, never pushes, never re-runs CI, never closes anything.
It answers one question per PR: *what would move this forward, and is it ours to do?*

Exit codes: 0 = nothing actionable, 2 = at least one PR needs a nudge or an author fix,
1 = the probe itself failed (so a broken probe is never mistaken for a quiet week).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

DEFAULT_AUTHOR = "isearchxsolve"
# Days a green PR may sit with no reviewer before it is reported as needing a nudge. Two days is
# chosen from the measured case, not from taste: fyne#6637 was green on 2026-10-28 and unreviewed
# on 2026-10-30, which is the exact window in which a polite factual comment still reads as
# attentive rather than as pressure.
NUDGE_AFTER_DAYS = 2
# A PR with no activity at all for this long is dead weight; it is reported so a human decides,
# never closed automatically.
STALE_AFTER_DAYS = 14


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_between(then: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    if then is None:
        return None
    now = now or _utcnow()
    return round((now - then).total_seconds() / 86400.0, 1)


def classify(facts: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, str]:
    """Decide what this PR needs. Pure: same facts in, same verdict out.

    The order matters. A merged PR is finished whatever else is true. A closed one is finished too.
    A draft is not yet published, so it is never nudged. Failing checks are ours to fix before any
    human is asked to look - asking for review on red CI spends the maintainer's attention on work
    we should have finished. Changes requested is ours. Everything else that is green and unreviewed
    is waiting on a human, and the only useful action is one factual comment.
    """
    now = now or _utcnow()
    age = days_between(parse_ts(facts.get("created_at")), now) or 0.0
    idle = days_between(parse_ts(facts.get("updated_at")), now) or 0.0

    if facts.get("merged_at"):
        return {"state": "MERGED", "action": "none", "reason": "merged"}
    if str(facts.get("state", "")).lower() == "closed":
        return {"state": "CLOSED", "action": "none", "reason": "closed without merge"}
    if facts.get("draft"):
        return {"state": "DRAFT", "action": "publish_when_ready",
                "reason": "draft PRs are not review candidates"}

    checks = facts.get("checks") or {}
    if checks.get("failing"):
        return {"state": "BLOCKED_CI", "action": "fix_checks",
                "reason": "%d failing check(s)" % checks["failing"]}
    if checks.get("pending"):
        return {"state": "CI_RUNNING", "action": "wait",
                "reason": "%d check(s) still running" % checks["pending"]}

    review = (facts.get("review_decision") or "none").lower()
    if review == "changes_requested":
        return {"state": "CHANGES_REQUESTED", "action": "address_review",
                "reason": "reviewer asked for changes"}
    if review == "approved":
        return {"state": "APPROVED", "action": "wait_for_merge",
                "reason": "approved, awaiting merge"}
    if review == "review_required":
        return {"state": "NEEDS_REVIEW", "action": "wait",
                "reason": "required reviewers not yet assigned a verdict"}

    reviewers = facts.get("review_count") or 0
    if reviewers == 0 and idle >= NUDGE_AFTER_DAYS:
        return {"state": "NEEDS_NUDGE",
                "action": "one_factual_comment",
                "reason": "green, %s day(s) idle, zero reviews" % idle}
    if reviewers == 0:
        return {"state": "WAITING_FRESH", "action": "wait",
                "reason": "green, %s day(s) old, no review yet" % age}
    if idle >= STALE_AFTER_DAYS:
        return {"state": "STALE_WITH_COMMENTS", "action": "human_decision",
                "reason": "%d review(s), %s day(s) idle" % (reviewers, idle)}
    return {"state": "IN_REVIEW", "action": "wait",
            "reason": "%d review(s), %s day(s) idle" % (reviewers, idle)}


def _gh(args: List[str], timeout: int = 30) -> Any:
    """One authenticated GitHub read. Raises on failure; a probe must not invent silence.

    Encoding is pinned to UTF-8 with replacement: the Windows console is cp1252 and an issue or PR
    title outside that code page killed the reader thread on 2026-10-30 while `returncode` stayed 0,
    so an unreadable response arrived as an empty one and the lane reported a quiet week.
    """
    result = subprocess.run(["gh", *args], capture_output=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args[:3]),
                                                (result.stderr or result.stdout or "").strip()[:300]))
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("gh %s returned no output" % " ".join(args[:3]))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh %s returned unparseable output: %s" % (" ".join(args[:3]), exc))


def discover_prs(author: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Every PR we authored, any state. Search covers forks we opened from, which a repo list does not."""
    query = "author:%s type:pr" % author
    payload = _gh(["api", "-X", "GET", "search/issues",
                   "-f", "q=" + query, "-f", "sort=updated", "-f", "order=desc",
                   "-f", "per_page=" + str(min(limit, 100))], timeout=60)
    # A missing `items` key is a failed read, not an empty result. Silence is a verdict someone
    # acts on, so it is never produced from a payload that did not answer the question.
    if not isinstance(payload, dict) or "items" not in payload:
        raise RuntimeError("search returned no items field: " + str(payload)[:200])
    items = payload.get("items") or []
    found = []
    for item in items:
        repo = (item.get("repository_url") or "").rsplit("/repos/", 1)[-1]
        if not repo:
            continue
        found.append({"repo": repo, "number": item.get("number"),
                      "title": item.get("title") or "", "url": item.get("html_url") or ""})
    return found


def pr_facts(repo: str, number: int) -> Dict[str, Any]:
    """Read one PR's review and check state. Public reads only."""
    pr = _gh(["api", "repos/%s/pulls/%d" % (repo, number)]) or {}
    facts: Dict[str, Any] = {
        "repo": repo,
        "number": number,
        "title": pr.get("title") or "",
        "url": pr.get("html_url") or "",
        "state": pr.get("state"),
        "draft": bool(pr.get("draft")),
        "merged_at": pr.get("merged_at"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "head_sha": (pr.get("head") or {}).get("sha"),
        "base_ref": (pr.get("base") or {}).get("ref"),
        "mergeable": pr.get("mergeable"),
        "merge_state": pr.get("mergeStateStatus"),
    }

    reviews = _gh(["api", "repos/%s/pulls/%d/reviews" % (repo, number)]) or []
    facts["review_count"] = len([r for r in reviews if (r or {}).get("state")])
    states = [(r or {}).get("state", "").upper() for r in reviews]
    if "CHANGES_REQUESTED" in states:
        facts["review_decision"] = "changes_requested"
    elif "APPROVED" in states:
        facts["review_decision"] = "approved"
    else:
        facts["review_decision"] = "none"

    facts["checks"] = {"total": 0, "failing": 0, "pending": 0, "passing": 0}
    if pr.get("state") == "open" and facts["head_sha"]:
        try:
            runs = _gh(["api", "repos/%s/commits/%s/check-runs" % (repo, facts["head_sha"])]) or {}
            total = int(runs.get("total_count") or 0)
            failing = pending = passing = 0
            for run in runs.get("check_runs") or []:
                status = (run or {}).get("status")
                conclusion = ((run or {}).get("conclusion") or "").lower()
                if status != "completed":
                    pending += 1
                elif conclusion in ("failure", "timed_out", "cancelled", "action_required"):
                    failing += 1
                elif conclusion in ("success", "neutral", "skipped"):
                    passing += 1
            facts["checks"] = {"total": total, "failing": failing,
                               "pending": pending, "passing": passing}
        except RuntimeError as exc:
            # A check-read failure is data, not silence: record it and let classification proceed on
            # what is known, without pretending the CI is green.
            facts["checks_error"] = str(exc)[:200]
    return facts


# A repository that has already closed this many of our PRs without merging is not a place where a
# comment converts anything. Measured 2026-10-30: 29 of 47 closures sit in five such repositories and
# every one of them was closed within eight hours of opening, most within one.
FARM_REPO_CLOSED_THRESHOLD = 2


def apply_repo_history(rows: List[Dict[str, Any]],
                       own_owner: str = DEFAULT_AUTHOR) -> List[Dict[str, Any]]:
    """Downgrade an open PR in a repository that repeatedly rejected us.

    The evidence is in the same report, so this needs no extra API call: a repository with
    `FARM_REPO_CLOSED_THRESHOLD` or more of our closed-unmerged PRs has already answered the
    question, and nudging there spends attention on a mill rather than a maintainer.
    """
    closed_by_repo: Dict[str, int] = {}
    for row in rows:
        if row["verdict"]["state"] == "CLOSED":
            closed_by_repo[row["facts"]["repo"]] = closed_by_repo.get(row["facts"]["repo"], 0) + 1
    for row in rows:
        repo = row["facts"]["repo"]
        if row["verdict"]["action"] != "one_factual_comment":
            continue
        if closed_by_repo.get(repo, 0) >= FARM_REPO_CLOSED_THRESHOLD:
            row["verdict"] = {
                "state": "REPEATEDLY_CLOSED_REPO",
                "action": "do_not_nudge",
                "reason": "this repository already closed %d of our PRs unmerged"
                          % closed_by_repo[repo],
            }
    return rows


def summarise(rows: List[Dict[str, Any]],
              own_owner: str = DEFAULT_AUTHOR) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]["state"]] = counts.get(row["verdict"]["state"], 0) + 1
    # A merge in our own repository proves nothing about the market. It is counted separately so the
    # headline can never read "1 merged" and mean a self-merge.
    external = [r for r in rows if not r["facts"]["repo"].startswith(own_owner + "/")]
    external_merged = len([r for r in external if r["verdict"]["state"] == "MERGED"])
    external_reviewed = len([r for r in external if r["verdict"]["state"] in
                             ("APPROVED", "CHANGES_REQUESTED", "IN_REVIEW",
                              "STALE_WITH_COMMENTS", "MERGED")])
    actionable = [row for row in rows if row["verdict"]["action"] in
                  ("one_factual_comment", "fix_checks", "address_review", "human_decision")]
    return {
        "prs": len(rows),
        "external_prs": len(external),
        "counts": counts,
        "actionable": len(actionable),
        "merged": counts.get("MERGED", 0),
        "external_merged": external_merged,
        "external_reviewed": external_reviewed,
        "reviewed_or_better": len([r for r in rows if r["verdict"]["state"] in
                                   ("APPROVED", "CHANGES_REQUESTED", "IN_REVIEW",
                                    "STALE_WITH_COMMENTS", "MERGED")]),
    }


def render_markdown(rows: List[Dict[str, Any]], summary: Dict[str, Any],
                    now: Optional[datetime] = None) -> str:
    now = now or _utcnow()
    lines = ["# PR conversion watch - " + now.strftime("%Y-%m-%d %H:%MZ"), ""]
    lines.append("Published PRs: **%d** (**%d** external) | external merged: **%d** | "
                 "external reached review: **%d** | actionable now: **%d**"
                 % (summary["prs"], summary.get("external_prs", summary["prs"]),
                    summary.get("external_merged", 0),
                    summary.get("external_reviewed", 0), summary["actionable"]))
    lines.append("")
    lines.append("| PR | state | age (d) | idle (d) | checks | action | reason |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        facts, verdict = row["facts"], row["verdict"]
        checks = facts.get("checks") or {}
        lines.append("| %s#%s | %s | %s | %s | %d pass / %d fail / %d pending | %s | %s |" % (
            facts["repo"], facts["number"], verdict["state"],
            days_between(parse_ts(facts.get("created_at")), now),
            days_between(parse_ts(facts.get("updated_at")), now),
            checks.get("passing", 0), checks.get("failing", 0), checks.get("pending", 0),
            verdict["action"], verdict["reason"]))
    lines.append("")
    actionable = [r for r in rows if r["verdict"]["action"] != "none"
                  and r["verdict"]["action"] != "wait"]
    if actionable:
        lines.append("## Do these, in order")
        lines.append("")
        for row in actionable:
            facts, verdict = row["facts"], row["verdict"]
            lines.append("- **%s#%s** - %s (%s)" % (facts["repo"], facts["number"],
                                                    verdict["action"], verdict["reason"]))
    else:
        lines.append("## Nothing actionable")
        lines.append("")
        lines.append("Every published PR is merged, closed, or legitimately waiting.")
    return "\n".join(lines) + "\n"


def write_receipt(directory: Path, report: Dict[str, Any], markdown: str,
                  now: Optional[datetime] = None) -> Dict[str, str]:
    now = now or _utcnow()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    json_path = directory / ("report-" + stamp + ".json")
    md_path = directory / ("report-" + stamp + ".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--author", default=DEFAULT_AUTHOR)
    parser.add_argument("--pr", action="append", default=[],
                        help="repo#number to check instead of the search (repeatable)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default=str(Path("scratch") / "pr-conversion-watch"))
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        targets = []
        if args.pr:
            for spec in args.pr:
                repo, _, number = spec.rpartition("#")
                if not repo or not number.isdigit():
                    parser.error("--pr expects owner/name#number, got " + spec)
                targets.append({"repo": repo, "number": int(number)})
        else:
            targets = discover_prs(args.author, args.limit)
        rows = []
        for target in targets:
            facts = pr_facts(target["repo"], int(target["number"]))
            rows.append({"facts": facts, "verdict": classify(facts)})
        rows = apply_repo_history(rows, args.author)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"phase": "PROBE_FAILED", "error": str(exc)[:400]}))
        return 1

    summary = summarise(rows)
    markdown = render_markdown(rows, summary)
    report = {"generated_at": _utcnow().isoformat(), "author": args.author,
              "summary": summary, "rows": rows}
    paths = write_receipt(Path(args.out), report, markdown)
    report["receipts"] = paths

    if args.json_only:
        print(json.dumps(report))
    else:
        print(markdown)
        print("receipts: " + paths["markdown"] + " + " + paths["json"])
        print("VERDICT: " + ("ACTION_REQUIRED" if summary["actionable"] else "QUIET")
              + " prs=%d actionable=%d reviewed=%d merged=%d"
              % (summary["prs"], summary["actionable"], summary["reviewed_or_better"],
                 summary["merged"]))
    return 2 if summary["actionable"] else 0


if __name__ == "__main__":
    sys.exit(main())
