#!/usr/bin/env python3
"""Run a bounded, read-only GitHub discovery sweep into the candidate index.

This process never dispatches work or writes to GitHub.  It stops when a
candidate appears so that the evidence can be inspected promptly.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import time

import bounty_candidate_index as index


def scout(db, cycles: int, interval: int, limit: int, max_pages: int):
    had_errors = False
    for cycle in range(1, cycles + 1):
        # Extend each existing lane in bounded windows after a short indexing lag.
        now = int(time.time())
        lanes = [r[0] for r in db.execute("SELECT DISTINCT term FROM partitions")]
        if not lanes:
            raise index.IncompleteEvidence("No search lanes have been seeded")
        for lane in lanes:
            latest = db.execute("SELECT MAX(end_epoch) FROM partitions WHERE term=?", (lane,)).fetchone()[0]
            if now - 300 > latest + 300:
                index.extend_partition(db, lane, now - 300)
        try:
            action = index.partition_step(db, limit, max_pages)
        except index.IncompleteEvidence as exc:
            action = {"action": "error", "detail": str(exc)}
        if action["action"] in ("error", "retry_page", "page_complete_with_errors", "saturated"):
            had_errors = True
        retried = None
        if cycle % 3 == 0:
            stale = db.execute("SELECT repo,number FROM candidates WHERE status='error' AND checked_at<=? ORDER BY checked_at LIMIT 1", (time.time() - 600,)).fetchone()
            if stale:
                retried = index.refresh_candidate(db, stale[0], stale[1], max_pages)
        candidates = index.search_index(db, 900)
        print(json.dumps({"cycle": cycle, "action": action, "qualified": candidates,
                          "retry": retried, "error_backlog": db.execute("SELECT count(*) FROM candidates WHERE status='error'").fetchone()[0]}, ensure_ascii=False), flush=True)
        if candidates:
            return "candidate_available"
        if action["action"] == "idle":
            return "no_pending_partitions"
        if cycle < cycles:
            time.sleep(interval)
    return "cycle_budget_exhausted_with_errors" if had_errors else "cycle_budget_exhausted"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("the index database must already exist")
    if not (1 <= args.cycles <= 1000 and 10 <= args.interval <= 3600 and
            1 <= args.limit <= 100 and 1 <= args.max_pages <= 50):
        parser.error("invalid scout limits")
    with closing(index.connect(args.db)) as db:
        result = scout(db, args.cycles, args.interval, args.limit, args.max_pages)
    print(json.dumps({"scout_status": result}), flush=True)
    return 2 if result == "cycle_budget_exhausted_with_errors" else 0


if __name__ == "__main__":
    raise SystemExit(main())
