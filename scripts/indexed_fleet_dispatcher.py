#!/usr/bin/env python3
"""Hand recently qualified index results to the existing fleet dispatcher.

The default is a read-only preview.  Live mode repeats the index check and the
existing dispatch gates because a bounty or PR can change after indexing.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import autonomous_icu_pipeline as policy
import bounty_candidate_index as index


def open_index(path: Path, live: bool):
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError("The candidate index does not exist")
    db = sqlite3.connect(str(path) if live else path.as_uri() + "?mode=ro", uri=not live, timeout=15)
    try:
        if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"]:
            raise sqlite3.DatabaseError("Candidate index integrity check failed")
        return db
    except Exception:
        db.close()
        raise


def dispatch_index(db, max_age: int, limit: int, live: bool = False):
    candidates = index.search_index(db, max_age)[:limit]
    if not live:
        return {"mode": "preview", "candidates": candidates}
    if not policy.REMOTE_FLEET_MODE:
        raise RuntimeError("Remote fleet mode must be enabled before live dispatch")
    integrity = policy.verify_delivery_database_integrity()
    if integrity.get("integrity") != "ok":
        raise RuntimeError("An existing, intact delivery database is required before live dispatch")
    outcomes = []
    for candidate in candidates:
        repo, number = candidate["repo"], candidate["number"]
        fresh = index.refresh_candidate(db, repo, number, max_pages=5)
        if fresh["status"] != "qualified":
            outcomes.append({"repo": repo, "number": number, "status": "held", "reason": fresh["reason"]})
            continue
        data = policy.get_issue_fast(repo, number)
        if not data or data.get("state") != "OPEN":
            outcomes.append({"repo": repo, "number": number, "status": "held", "reason": "issue unavailable or no longer open"})
            continue
        author = (data.get("author") or {}).get("login", "")
        funding = fresh.get("evidence", {}).get("funding", {})
        funding_reason = (f"{fresh['reason']}; payer={funding.get('actor', '')}; "
                          f"amount={funding.get('amount', '')}; evidence={funding.get('source_url', '')}")
        delivered = policy.post_grounded_proposal(
            repo, number, data.get("title", ""), author,
            f"https://github.com/{repo}/issues/{number}", data.get("body", ""),
            data.get("author_comments", []), data.get("labels", []), funding_reason,
            fresh.get("evidence", {}).get("corridor", ""),
            author_assoc=data.get("authorAssociation", "NONE"), live_mode=True,
            payer_assoc=fresh.get("evidence", {}).get("funding", {}).get("payer_association", "NONE"))
        outcomes.append({"repo": repo, "number": number,
                         "status": "queued" if delivered else "held",
                         "reason": "dispatch accepted" if delivered else "existing dispatch gate did not accept"})
    return {"mode": "live", "outcomes": outcomes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("scratch/bounty_candidate_index.sqlite3"))
    parser.add_argument("--max-age", type=int, default=900)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.max_age <= 0 or args.limit <= 0:
        parser.error("--max-age and --limit must be positive")
    with closing(open_index(args.db, args.live)) as db:
        result = dispatch_index(db, args.max_age, args.limit, args.live)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
