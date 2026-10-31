"""Stream source-bound agent decisions into durable, generation-fenced dispatch.

No issue classification lives here. The agent chooses; these gates check its evidence.
"""
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3

from actions_github import GitHub, GitHubError, StateStore, task_id, utcnow
from pipeline_evidence import digest, require_evidence


def discover(lanes, max_dispatches=2, live=False, state_dir=None, hydrate_only=False,
             finder=None, api=None, store=None):
    from actions_dispatch import dispatch, repository_size_kb, repository_over_capacity
    from agent_door import find_issues
    folder = Path(state_dir or os.environ.get("BOUNTY_STATE_DIR", "scratch/actions-discovery"))
    folder.mkdir(parents=True, exist_ok=True)
    api, store = api or GitHub(), store or StateStore()
    counts, dispatched, seen = Counter(), [], set()
    refusal_counts, qualified_ids = Counter(), set()
    capacity = {}
    ledger = None
    # One workflow concurrency group serializes cache writers. Per-task remote CAS is
    # still authoritative for ownership, including callers outside this workflow.
    con = sqlite3.connect(folder / "agent-queue.sqlite3", timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS decisions(task_id TEXT PRIMARY KEY,payload TEXT,"
                "revision TEXT,disposition TEXT,at TEXT)")

    def records():
        nonlocal ledger
        if ledger is None:
            ledger = list(store.records() or ())
        return ledger

    def event(phase, **fields):
        document = {"at": utcnow(), "phase": phase, **fields}
        with (folder / "agent-events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document) + "\n")
        print(json.dumps(document), flush=True)

    def save(identity, row, disposition):
        con.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?)",
                    (identity, json.dumps(row), digest(row), disposition, utcnow()))
        con.commit()

    def ingest(row):
        revision = digest(row)
        if revision in seen:
            return
        seen.add(revision)
        identity = task_id(row["repo"], row["issue"])
        save(identity, row, "received")
        counts["received"] += 1
        try:
            lane = row.get("source_lane") or row.get("lane")
            # 'bounty' was the old admission type, not a configurable search lane.
            if lane == "bounty":
                lane = "normal"
            if lane not in lanes:
                raise ValueError("OUT_OF_LANE")
            context = api.issue_context(row["repo"], row["issue"])
            proof, verdict = require_evidence(row, context)
            context["lane"] = row.get("lane")
            if repository_over_capacity(repository_size_kb(api, context["repo"])):
                raise ValueError("CAPACITY_EXCLUDED")
            counts["qualified"] += 1
            qualified_ids.add(identity)
            if not live:
                save(identity, row, "preview")
                return
            if len(dispatched) >= max_dispatches:
                save(identity, row, "capacity_wait")
                counts["capacity_wait"] += 1
                return
            if "used" not in capacity:
                active = []
                for status in ("queued", "in_progress", "waiting", "pending", "requested"):
                    active.extend(api.workflow_runs(store.repo, status=status))
                reservations = {r["task_id"] for r in records()
                                if r.get("status") in ("DISPATCHING", "DISPATCHED", "CLAIMED", "ENGINEERING", "VERIFIED", "PUBLISHING")}
                capacity["used"] = max(len({r["id"] for r in active}), len(reservations))
            if capacity["used"] >= 4:
                save(identity, row, "capacity_wait")
                counts["capacity_wait"] += 1
                return
            result = dispatch(api, store, context, proof, [lane],
                              sovereign_admission=True, competition=verdict)
            dispatched.append(result)
            capacity["used"] += 1
            save(identity, row, "dispatched")
            event("DISPATCHED", task_id=identity)
        except (ValueError, GitHubError, OSError, KeyError, TypeError) as exc:
            counts[str(exc)] += 1
            refusal_counts[str(exc)] += 1
            save(identity, row, "deferred")
            event("AGENT_HANDOFF_DEFERRED", task_id=identity, reason=str(exc))

    door = {}

    def write_summary():
        pending = con.execute("SELECT count(*) FROM decisions WHERE disposition IN "
                              "('capacity_wait','deferred','received')").fetchone()[0]
        summary = {"at": utcnow(), "mode": "LIVE" if live else "READ_ONLY",
                   "door_reason": door.get("reason"), "counts": dict(counts),
                   "qualified_unique": len(qualified_ids), "dispatched": dispatched,
                   "pending_hydration": pending}
        for name, document in (("receipts.jsonl", summary),
                               ("census.jsonl", {**summary, "refusals": dict(refusal_counts)})):
            with (folder / name).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(document) + "\n")
        print(json.dumps(summary), flush=True)
        return summary
    try:
        if hydrate_only:
            # Only source-bound agent decisions are replayed; factual freshness is checked
            # again. Changed sources go back to the search agent on its next pass.
            rows = [json.loads(r[0]) for r in con.execute(
                "SELECT payload FROM decisions WHERE disposition IN ('capacity_wait','deferred') ORDER BY at")]
            for row in rows:
                ingest(row)
            door = {"reason": "HYDRATE_ONLY"}
        else:
            door = (finder or find_issues)(root=str(folder / "agent-workspaces"),
                rounds=int(os.environ.get("BOUNTY_AGENT_ROUNDS", "1")),
                timeout=int(os.environ.get("BOUNTY_AGENT_TIMEOUT", "600")),
                limit=int(os.environ.get("BOUNTY_AGENT_ROW_LIMIT", "0")),
                on_admitted=ingest, lanes=lanes,
                prior_refusals=[r for r in records() if str(r.get("status", "")).startswith("REJECTED_")])
            for row in door.get("rows") or []:
                ingest(row)
            for refusal in door.get("refused") or []:
                counts[refusal.get("reason", "UNKNOWN_REFUSAL")] += 1
                refusal_counts[refusal.get("reason", "UNKNOWN_REFUSAL")] += 1
        return write_summary()
    except Exception as exc:
        counts["DISCOVERY_ERROR"] += 1
        event("DISCOVERY_ERROR", error=type(exc).__name__, reason=str(exc))
        write_summary()
        raise
    finally:
        con.close()
