#!/usr/bin/env python3
"""Build a local, evidence-backed index from global GitHub issue searches.

GitHub does not execute these custom predicates.  It returns a broad upstream
stream; this program evaluates it during ingestion.  Index searches expose
only records whose checks succeeded recently.  It never dispatches work.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

import autonomous_icu_pipeline as policy


TRUSTED_PLATFORM_ACTORS = {"algora-pbc", "gitcoinbot", "opire-bot"}
AUTHORITY = {"OWNER", "MEMBER", "COLLABORATOR"}
USD_AMOUNT = re.compile(r"(?:\$\s*(\d[\d,]*(?:\.\d{1,2})?)([kKmM])?(?![\w.])|\b(\d[\d,]*(?:\.\d{1,2})?)([kKmM])?\s*(?:USD|USDC|USDT)\b)", re.I)
OFFER = re.compile(r"\b(?:bounty|reward|prize|funded|funding|will\s+pay|willing\s+to\s+pay|offering)\b", re.I)
RETRACTED = re.compile(r"\b(?:cancel(?:led|ed)?|retract(?:ed)?|withdrawn|expired|no\s+longer\s+(?:available|offering|funded)|not\s+(?:funded|paid)|bounty\s+(?:paid|awarded|closed)|work\s+(?:has\s+been\s+)?submitted)\b", re.I)
HTML_DOCUMENT = re.compile(r"<!doctype\s+html|<html\b", re.I)


class IncompleteEvidence(RuntimeError):
    pass


def rules_signature():
    """Bind an indexed decision to the exact index and policy source files."""
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(policy.__file__)):
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


LOADED_RULES_SIGNATURE = rules_signature()


def gh_api(path: str, params: dict | None = None):
    cmd = ["gh", "api", "--method", "GET", path]
    for key, value in (params or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IncompleteEvidence(f"GitHub request failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise IncompleteEvidence(f"GitHub request failed: {(result.stderr or result.stdout)[:250]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IncompleteEvidence("GitHub returned invalid JSON") from exc


def pages(path: str, params: dict | None = None, max_pages: int = 5):
    items = []
    for page in range(1, max_pages + 1):
        data = gh_api(path, {**(params or {}), "per_page": 100, "page": page})
        if not isinstance(data, list):
            raise IncompleteEvidence("GitHub returned an unexpected page")
        items.extend(data)
        if len(data) < 100:
            return items
    raise IncompleteEvidence(f"GitHub page cap reached ({max_pages} pages)")


def _prose(text: str) -> str:
    if HTML_DOCUMENT.search(text or ""):
        return ""
    text = re.sub(r"```.*?```|~~~.*?~~~|~~.*?~~", " ", text or "", flags=re.S)
    text = re.sub(r"(?m)^\s*>.*$|`[^`\n]*`", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


def funding_evidence(issue: dict, comments: list[dict]):
    """Find an explicit USD offer from repository authority or a known platform.

    Other currencies and ambiguous or retracted offers remain unqualified; no
    exchange rate or payer identity is invented.
    """
    sources = []
    issue_author = ((issue.get("user") or {}).get("login") or "")
    issue_url = issue.get("html_url", "")
    repo = (issue.get("repository_url") or "").split("/repos/")[-1]
    if not repo and "github.com/" in issue_url:
        repo = "/".join(issue_url.split("github.com/", 1)[1].split("/")[:2])
    issue_text = (issue.get("title") or "") + "\n" + (issue.get("body") or "")
    if ((issue.get("author_association") or "").upper() in AUTHORITY or
            (issue_author and policy._has_direct_offer_language(_prose(issue_text)) and
             policy.is_direct_payer(issue_author, repo, _prose(issue_text)))):
        sources.append((issue_author, issue_url, issue_text, (issue.get("author_association") or "NONE").upper()))
    for comment in comments:
        actor = (comment.get("user") or {}).get("login", "")
        comment_text = comment.get("body") or ""
        if ((comment.get("author_association") or "").upper() in AUTHORITY or
                actor.lower() in TRUSTED_PLATFORM_ACTORS or
                (actor and actor.lower() == issue_author.lower() and
                 policy._has_direct_offer_language(_prose(comment_text)) and
                 policy.is_direct_payer(actor, repo, _prose(comment_text)))):
            sources.append((actor, comment.get("html_url", ""), comment_text,
                            (comment.get("author_association") or "NONE").upper()))

    # A later authoritative cancellation must not be overridden by an older offer.
    for actor, _, text, _ in sources:
        if RETRACTED.search(_prose(text)) or policy._has_payment_negation(_prose(text)):
            return None, f"authoritative payment status requires review ({actor})"

    for actor, url, text, association in sources:
        prose = _prose(text)
        for match in USD_AMOUNT.finditer(prose):
            # Require money and offer language together in a bounded passage.
            near = prose[max(0, match.start() - 120):min(len(prose), match.end() + 120)]
            if not OFFER.search(near):
                continue
            try:
                amount = Decimal((match.group(1) or match.group(3)).replace(",", ""))
                suffix = (match.group(2) or match.group(4) or "").lower()
                if suffix == "k":
                    amount *= 1000
                elif suffix == "m":
                    amount *= 1000000
            except InvalidOperation:
                continue
            if Decimal("50") <= amount <= Decimal("9999999"):
                return {"actor": actor, "source_url": url, "amount": str(amount),
                        "payer_association": association,
                        "currency": "USD or USD-denominated stablecoin"}, "explicit funding evidence"
    return None, "no qualifying explicit USD funding evidence"


def competing_prs(repo: str, number: int, max_pages: int = 5):
    pulls = pages(f"repos/{repo}/pulls", {"state": "open"}, max_pages=max_pages)
    target = re.escape(str(number))
    ref = re.compile(rf"(?<![A-Za-z0-9])#\s*{target}(?!\d)|\b(?:fix(?:es|ed)?|resolve[sd]?|close[sd]?|issue)\s*[:#-]?\s*{target}\b", re.I)
    branch = re.compile(rf"(?:^|[-_/]){target}(?:$|[-_/])")
    for pr in pulls:
        head = (pr.get("head") or {}).get("ref") or ""
        if ref.search((pr.get("title") or "") + "\n" + (pr.get("body") or "")) or branch.search(head):
            return pr.get("html_url") or f"open PR #{pr.get('number')}"
    return None


def linked_prs(repo: str, number: int, max_pages: int = 5):
    """Check issue timeline links, including PRs from other repositories."""
    events = pages(f"repos/{repo}/issues/{number}/timeline", max_pages=max_pages)
    for event in events:
        source = (event.get("source") or {}).get("issue") or {}
        if source.get("pull_request") and source.get("state") == "open":
            return source.get("html_url") or "open linked pull request"
        if source.get("pull_request") and source.get("state") not in ("open", "closed"):
            raise IncompleteEvidence("linked pull request state was unavailable")
    return None


def check_candidate(repo: str, number: int, max_pages: int = 5, issue: dict | None = None):
    if issue is None:
        issue = gh_api(f"repos/{repo}/issues/{number}")
    if issue.get("state") != "open" or issue.get("pull_request"):
        return "excluded", "issue is no longer open", {}
    if (issue.get("user") or {}).get("type") == "Bot":
        return "excluded", "bot-authored issue", {}
    comments = pages(f"repos/{repo}/issues/{number}/comments", max_pages=max_pages)
    if len(comments) != issue.get("comments", len(comments)):
        raise IncompleteEvidence("issue comments changed or were incomplete during the check")
    funding, why = funding_evidence(issue, comments)
    if not funding:
        return "deferred", why, {}

    eligible, reason = policy.verify_genuine_icu_patient(
        issue.get("title", ""), issue.get("body", ""),
        [c.get("body", "") for c in comments if
         (c.get("author_association") or "").upper() in AUTHORITY or
         ((c.get("user") or {}).get("login") or "").lower() in TRUSTED_PLATFORM_ACTORS or
         (((c.get("user") or {}).get("login") or "").lower() ==
          ((issue.get("user") or {}).get("login") or "").lower())],
        issue.get("labels", []), repo,
        author_assoc=issue.get("author_association", "NONE"),
        author=(issue.get("user") or {}).get("login"), live_delivery_mode=True,
        payer_assoc=funding["payer_association"])
    if not eligible:
        return "deferred", reason, {"funding": funding}
    author = (issue.get("user") or {}).get("login") or ""
    corridor, _, detail = policy.detect_author_corridor(author)
    if corridor in ("Excluded Regional Market", "Excluded Territory"):
        return "deferred", detail, {"funding": funding}
    conflict = competing_prs(repo, number, max_pages=max_pages)
    if not conflict:
        conflict = linked_prs(repo, number, max_pages=max_pages)
    if conflict:
        return "deferred", f"open PR references issue: {conflict}", {"funding": funding}
    if rules_signature() != LOADED_RULES_SIGNATURE:
        raise IncompleteEvidence("index or policy code changed while the process was running")
    return "qualified", "explicit funding; no referencing open PR found", {
        "funding": funding, "corridor": detail,
        "rules_signature": rules_signature(),
        "competition_scope": "fetched open PR titles, bodies, branch names and issue timeline links; unreferenced work may be missed"}


def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS candidates (
        repo TEXT NOT NULL, number INTEGER NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT NOT NULL, evidence TEXT NOT NULL,
        checked_at REAL NOT NULL, PRIMARY KEY(repo, number))""")
    db.execute("""CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY, query TEXT NOT NULL, started_at REAL NOT NULL,
        finished_at REAL, status TEXT NOT NULL, total_count INTEGER,
        returned_count INTEGER, detail TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS partitions (
        id INTEGER PRIMARY KEY, term TEXT NOT NULL, start_epoch INTEGER NOT NULL,
        end_epoch INTEGER NOT NULL, status TEXT NOT NULL, next_page INTEGER NOT NULL DEFAULT 1, page_size INTEGER,
        total_count INTEGER, detail TEXT NOT NULL DEFAULT '',
        UNIQUE(term,start_epoch,end_epoch))""")
    db.execute("CREATE TABLE IF NOT EXISTS scheduler (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.commit()
    return db


def store(db, repo, number, url, title, status, reason, evidence, now=None):
    db.execute("""INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(repo,number) DO UPDATE SET url=excluded.url,title=excluded.title,
        status=excluded.status,reason=excluded.reason,evidence=excluded.evidence,checked_at=excluded.checked_at""",
        (repo, number, url, title, status, reason, json.dumps(evidence, ensure_ascii=False), time.time() if now is None else now))
    db.commit()


def finish_check(db, repo, number, started, status, reason, evidence, title=None, url=None):
    """Prevent an older overlapping check from overwriting a newer check."""
    cur = db.execute("""UPDATE candidates SET status=?,reason=?,evidence=?,checked_at=?,
        title=COALESCE(?,title),url=COALESCE(?,url)
        WHERE repo=? AND number=? AND status='checking' AND checked_at=?""",
        (status, reason, json.dumps(evidence, ensure_ascii=False), time.time(), title, url, repo, number, started))
    db.commit()
    return cur.rowcount == 1


def search_index(db, max_age: int, now=None):
    cutoff = (time.time() if now is None else now) - max_age
    signature = rules_signature()
    if signature != LOADED_RULES_SIGNATURE:
        raise IncompleteEvidence("index or policy code changed while the process was running")
    results = []
    for r in db.execute("SELECT repo,number,url,title,checked_at,evidence FROM candidates WHERE status='qualified' AND checked_at>=? ORDER BY checked_at DESC", (cutoff,)):
        evidence = json.loads(r[5])
        if evidence.get("rules_signature") != signature:
            continue
        results.append({"repo": r[0], "number": r[1], "url": r[2], "title": r[3],
                        "checked_at": datetime.fromtimestamp(r[4], timezone.utc).isoformat(), "evidence": evidence})
    return results


def scan(db, term: str, limit: int, max_pages: int, page: int = 1, sort_by: str = "updated"):
    q = "is:issue is:open archived:false is:public" + (" " + term if term else "")
    started = time.time()
    cur = db.execute("INSERT INTO scans(query,started_at,status) VALUES (?,?,?)", (q, started, "running"))
    scan_id = cur.lastrowid
    db.commit()
    try:
        response = gh_api("search/issues", {"q": q, "sort": sort_by, "order": "desc", "per_page": limit, "page": page})
        if response.get("incomplete_results"):
            raise IncompleteEvidence("GitHub marked the search response incomplete")
        items = response.get("items")
        if not isinstance(items, list):
            raise IncompleteEvidence("GitHub returned no issue list")
        counts = {"qualified": 0, "deferred": 0, "excluded": 0, "error": 0}
        untracked_errors = 0
        for item in items:
            repo = (item.get("repository_url") or "").split("/repos/")[-1]
            number = item.get("number")
            if not repo or "/" not in repo or not isinstance(number, int):
                counts["error"] += 1
                untracked_errors += 1
                continue
            url, title = item.get("html_url", ""), item.get("title", "")
            # Invalidate an old approval before any network request.
            check_started = time.time()
            store(db, repo, number, url, title, "checking", "revalidation in progress", {}, check_started)
            try:
                status, reason, evidence = check_candidate(repo, number, max_pages)
            except Exception as exc:
                status, reason, evidence = "error", f"{type(exc).__name__}: {str(exc)[:300]}", {}
            if finish_check(db, repo, number, check_started, status, reason, evidence):
                counts[status] += 1
                print(f"[INDEX] {repo}#{number} {status}: {reason}", flush=True)
            else:
                counts["error"] += 1
                untracked_errors += 1
                print(f"[INDEX] {repo}#{number} superseded by a newer check", flush=True)
        total = response.get("total_count")
        detail = json.dumps({"counts": counts, "sample_only": total is None or total > len(items),
                             "search_incomplete": False, "page": page, "page_size": limit, "sort": sort_by,
                             "github_result_cap_reached": total is not None and total > 1000,
                             "untracked_errors": untracked_errors})
        scan_status = "partial_error" if counts["error"] else "complete_sample"
        db.execute("UPDATE scans SET finished_at=?,status=?,total_count=?,returned_count=?,detail=? WHERE id=?",
                   (time.time(), scan_status, total, len(items), detail, scan_id))
        db.commit()
        return {"query": q, "total_count": total, "examined": len(items), "counts": counts,
                "page": page, "page_size": limit, "github_result_cap_reached": total is not None and total > 1000,
                "sample_only": total is None or total > len(items), "status": scan_status,
                "untracked_errors": untracked_errors, "scan_id": scan_id}
    except Exception as exc:
        db.execute("UPDATE scans SET finished_at=?,status=?,detail=? WHERE id=?", (time.time(), "error", str(exc)[:500], scan_id))
        db.commit()
        raise


def _timestamp(epoch: int):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def partition_term(term: str, start: int, end: int):
    return (term + " " if term else "") + f"created:{_timestamp(start)}..{_timestamp(end)}"


def seed_partition(db, term: str, start: int, end: int):
    if start < 0 or end < start:
        raise ValueError("invalid partition bounds")
    db.execute("INSERT OR IGNORE INTO partitions(term,start_epoch,end_epoch,status) VALUES (?,?,?,'pending')", (term, start, end))
    db.commit()


def extend_partition(db, term: str, end: int):
    previous = db.execute("SELECT MAX(end_epoch) FROM partitions WHERE term=?", (term,)).fetchone()[0]
    if previous is None:
        raise IncompleteEvidence("seed the lane before extending it")
    if end <= previous:
        return None
    seed_partition(db, term, previous + 1, end)
    return previous + 1


def partition_step(db, limit: int, max_pages: int, plan_only: bool = False, lane: str | None = None):
    states = ("pending",) if plan_only else ("pending", "ready")
    placeholders = ",".join("?" for _ in states)
    lanes = [r[0] for r in db.execute(f"SELECT DISTINCT term FROM partitions WHERE status IN ({placeholders}) ORDER BY term", states)]
    if lane is not None:
        lanes = [term for term in lanes if term == lane]
    if not lanes:
        return {"action": "idle"}
    previous = db.execute("SELECT value FROM scheduler WHERE key='last_term'").fetchone()
    last = previous[0] if previous else None
    chosen = next((lane for lane in lanes if last is None or lane > last), lanes[0])
    direction_key = "direction:" + chosen
    prior_direction = db.execute("SELECT value FROM scheduler WHERE key=?", (direction_key,)).fetchone()
    direction = "ASC" if prior_direction and prior_direction[0] == "DESC" else "DESC"
    row = db.execute(f"SELECT id,term,start_epoch,end_epoch,status,next_page,page_size FROM partitions WHERE status IN ({placeholders}) AND term=? ORDER BY end_epoch {direction},start_epoch {direction} LIMIT 1", (*states, chosen)).fetchone()
    if not row:
        return {"action": "idle"}
    partition_id, term, start, end, status, page, page_size = row
    db.execute("INSERT INTO scheduler(key,value) VALUES ('last_term',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (term,))
    db.execute("INSERT INTO scheduler(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (direction_key, direction))
    db.commit()
    query_term = partition_term(term, start, end)
    if status == "pending":
        response = gh_api("search/issues", {"q": "is:issue is:open archived:false is:public " + query_term, "per_page": 1})
        if response.get("incomplete_results") or not isinstance(response.get("total_count"), int):
            raise IncompleteEvidence("partition count is incomplete or unavailable")
        total = response["total_count"]
        if total > 1000 and start < end:
            middle = (start + end) // 2
            # Parent and children are committed together, so a crash cannot lose a range.
            with db:
                db.execute("UPDATE partitions SET status='split',total_count=? WHERE id=?", (total, partition_id))
                db.execute("INSERT OR IGNORE INTO partitions(term,start_epoch,end_epoch,status) VALUES (?,?,?,'pending')", (term, start, middle))
                db.execute("INSERT OR IGNORE INTO partitions(term,start_epoch,end_epoch,status) VALUES (?,?,?,'pending')", (term, middle + 1, end))
            return {"action": "split", "id": partition_id, "start": _timestamp(start), "end": _timestamp(end), "total_count": total}
        new_status = "saturated" if total > 1000 else ("ready" if total else "done")
        db.execute("UPDATE partitions SET status=?,total_count=? WHERE id=?", (new_status, total, partition_id))
        db.commit()
        return {"action": new_status, "id": partition_id, "start": _timestamp(start), "end": _timestamp(end), "total_count": total}

    if page_size is not None and page_size != limit:
        raise IncompleteEvidence(f"partition {partition_id} already uses page size {page_size}; resume with the same size")
    if page * limit > 1000:
        raise IncompleteEvidence("partition reached GitHub's 1,000-result limit")
    result = scan(db, query_term, limit, max_pages, page, sort_by="created")
    # A partially failed page is retried rather than silently advancing past it.
    if result["status"] == "partial_error" and result.get("untracked_errors", 1):
        db.execute("UPDATE partitions SET page_size=? WHERE id=?", (limit, partition_id))
        db.commit()
        return {"action": "retry_page", "id": partition_id, "scan": result}
    if result["github_result_cap_reached"]:
        db.execute("UPDATE partitions SET status='pending',next_page=1,page_size=NULL WHERE id=?", (partition_id,))
        db.commit()
        return {"action": "repartition", "id": partition_id, "scan": result}
    done = result["examined"] < limit or page * limit >= (result["total_count"] or 0)
    db.execute("UPDATE partitions SET status=?,next_page=?,page_size=?,total_count=? WHERE id=?",
               ("done" if done else "ready", page + 1, limit, result["total_count"], partition_id))
    db.commit()
    action = "page_complete_with_errors" if result["status"] == "partial_error" else "page_complete"
    return {"action": action, "id": partition_id, "partition_complete": done, "scan": result}


def refresh_candidate(db, repo: str, number: int, max_pages: int):
    existing = db.execute("SELECT url,title FROM candidates WHERE repo=? AND number=?", (repo, number)).fetchone()
    url, title = existing if existing else (f"https://github.com/{repo}/issues/{number}", "")
    started = time.time()
    store(db, repo, number, url, title, "checking", "revalidation in progress", {}, started)
    fresh_issue = None
    try:
        fresh_issue = gh_api(f"repos/{repo}/issues/{number}")
        status, reason, evidence = check_candidate(repo, number, max_pages, issue=fresh_issue)
    except Exception as exc:
        status, reason, evidence = "error", f"{type(exc).__name__}: {str(exc)[:300]}", {}
    updated = finish_check(db, repo, number, started, status, reason, evidence,
                           title=fresh_issue.get("title") if isinstance(fresh_issue, dict) else None,
                           url=fresh_issue.get("html_url") if isinstance(fresh_issue, dict) else None)
    return {"repo": repo, "number": number, "status": status if updated else "superseded",
            "reason": reason, "evidence": evidence}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("scratch/bounty_candidate_index.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    scan_cmd = sub.add_parser("scan")
    scan_cmd.add_argument("--term", default="", help="Optional GitHub search terms; default searches all public open issues.")
    scan_cmd.add_argument("--limit", type=int, default=20, choices=range(1, 101), metavar="1..100")
    scan_cmd.add_argument("--page", type=int, default=1, help="GitHub result page; combine date qualifiers with --term for shards beyond 1,000 results.")
    scan_cmd.add_argument("--max-pages", type=int, default=5, choices=range(1, 51), metavar="1..50")
    query_cmd = sub.add_parser("search")
    query_cmd.add_argument("--max-age", type=int, default=900, help="Maximum evidence age in seconds.")
    sub.add_parser("status", help="Show partition and evidence backlog counts.")
    check_cmd = sub.add_parser("check", help="Refresh one known issue before using an indexed result.")
    check_cmd.add_argument("repo", help="GitHub owner/repository")
    check_cmd.add_argument("number", type=int)
    check_cmd.add_argument("--max-pages", type=int, default=5, choices=range(1, 51), metavar="1..50")
    retry_cmd = sub.add_parser("retry", help="Retry recorded incomplete issue checks.")
    retry_cmd.add_argument("--limit", type=int, default=10, choices=range(1, 101), metavar="1..100")
    retry_cmd.add_argument("--max-pages", type=int, default=5, choices=range(1, 51), metavar="1..50")
    retry_cmd.add_argument("--min-age", type=int, default=60, help="Only retry checks at least this many seconds old.")
    seed_cmd = sub.add_parser("seed", help="Add an inclusive UTC creation-time range for resumable global backfill.")
    seed_cmd.add_argument("--term", default="")
    seed_cmd.add_argument("--start", type=int, required=True, help="UTC Unix time in seconds.")
    seed_cmd.add_argument("--end", type=int, required=True, help="UTC Unix time in seconds.")
    extend_cmd = sub.add_parser("extend", help="Add a new inclusive range after a previously seeded lane.")
    extend_cmd.add_argument("--term", default="")
    extend_cmd.add_argument("--end", type=int, required=True, help="UTC Unix time in seconds.")
    step_cmd = sub.add_parser("step", help="Split or process a bounded number of persistent partitions.")
    step_cmd.add_argument("--steps", type=int, default=1, choices=range(1, 101), metavar="1..100")
    step_cmd.add_argument("--limit", type=int, default=10, choices=range(1, 101), metavar="1..100")
    step_cmd.add_argument("--max-pages", type=int, default=5, choices=range(1, 51), metavar="1..50")
    step_cmd.add_argument("--plan-only", action="store_true", help="Split and count ranges without fetching issue details.")
    step_cmd.add_argument("--lane", help="Process only this optional query lane; default rotates all lanes.")
    args = parser.parse_args(argv)
    if args.command == "search" and args.max_age <= 0:
        parser.error("--max-age must be positive")
    if args.command == "scan" and (args.page < 1 or args.page * args.limit > 1000):
        parser.error("--page and --limit must stay within GitHub's 1,000-result search window")
    if args.command == "check" and (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo) or args.number < 1):
        parser.error("check requires a valid owner/repository and positive issue number")
    if args.command == "seed" and (args.start < 0 or args.end < args.start):
        parser.error("seed requires valid inclusive Unix time bounds")
    if args.command == "extend" and args.end < 0:
        parser.error("extend requires a nonnegative Unix time")
    if args.command == "retry" and args.min_age < 0:
        parser.error("--min-age must be nonnegative")
    with closing(connect(args.db)) as db:
        if args.command == "scan":
            result = scan(db, args.term, args.limit, args.max_pages, args.page)
        elif args.command == "check":
            result = refresh_candidate(db, args.repo, args.number, args.max_pages)
        elif args.command == "retry":
            rows = db.execute("SELECT repo,number FROM candidates WHERE status='error' AND checked_at<=? ORDER BY checked_at LIMIT ?",
                              (time.time() - args.min_age, args.limit)).fetchall()
            attempts = [refresh_candidate(db, repo, number, args.max_pages) for repo, number in rows]
            result = {"retried": len(attempts), "attempts": attempts}
        elif args.command == "seed":
            seed_partition(db, args.term, args.start, args.end)
            result = {"status": "seeded", "term": args.term, "start": _timestamp(args.start), "end": _timestamp(args.end)}
        elif args.command == "extend":
            start = extend_partition(db, args.term, args.end)
            result = {"status": "seeded" if start is not None else "already_current", "term": args.term,
                      "start": _timestamp(start) if start is not None else None, "end": _timestamp(args.end)}
        elif args.command == "step":
            actions = []
            for _ in range(args.steps):
                action = partition_step(db, args.limit, args.max_pages, args.plan_only, args.lane)
                actions.append(action)
                if action["action"] in ("idle", "retry_page", "page_complete_with_errors", "saturated"):
                    break
            result = {"actions": actions, "partition_counts": dict(db.execute("SELECT status,count(*) FROM partitions GROUP BY status")),
                      "candidate_counts": dict(db.execute("SELECT status,count(*) FROM candidates GROUP BY status"))}
        elif args.command == "status":
            result = {"partition_counts": dict(db.execute("SELECT status,count(*) FROM partitions GROUP BY status")),
                      "candidate_counts": dict(db.execute("SELECT status,count(*) FROM candidates GROUP BY status")),
                      "scan_counts": dict(db.execute("SELECT status,count(*) FROM scans GROUP BY status"))}
        else:
            result = {"qualified": search_index(db, args.max_age)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") in ("partial_error", "error", "superseded"):
            return 2
        if args.command == "step" and actions and actions[-1]["action"] in ("retry_page", "page_complete_with_errors", "saturated"):
            return 2
        if args.command == "retry" and any(item["status"] in ("error", "superseded") for item in attempts):
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except IncompleteEvidence as exc:
        print(f"[INDEX ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
