"""Record a fresh operational epoch without altering the preserved Cloudflare ledger."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB = Path(r"D:\anonym\war-log\fleet-ledger.sqlite3")
DISPATCHER_DB = Path(r"D:\anonym\scratch\icu_pipeline.db")
SNAPSHOT = Path(r"D:\anonym\scratch\fleet_recovery_live_snapshot_20261026.json")
CHANNELS = (
    "BOUNTY_FLEET_QUEUE_V2", "BOUNTY_FLEET_CLAIM", "BOUNTY_FLEET_LEASE",
    "BOUNTY_FLEET_RESULT", "BOUNTY_FLEET_EXECUTION", "ENGINE_REGISTRATION",
)


def main():
    from fleet_local_relay import DB_PATH, initialize
    if Path(DB_PATH) != DB:
        raise RuntimeError(f"Unexpected SQLite path configured: {DB_PATH}")
    initialize()
    with sqlite3.connect(DB) as db:
        counts = {channel: db.execute(
            "SELECT COUNT(*) FROM fleet_events WHERE channel=?", (channel,)
        ).fetchone()[0] for channel in CHANNELS}
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if any(counts.values()) or integrity != "ok":
        raise RuntimeError("Fresh epoch requires an empty, healthy local fleet ledger")
    if not SNAPSHOT.is_file():
        raise RuntimeError("The last genuine Cloudflare snapshot is missing")
    snapshot_hash = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    dispatcher_counts = {}
    if DISPATCHER_DB.is_file():
        with sqlite3.connect(f"file:{DISPATCHER_DB.as_posix()}?mode=ro", uri=True) as db:
            dispatcher_counts = dict(db.execute(
                "SELECT status,COUNT(*) FROM deliveries GROUP BY status"
            ).fetchall())
    receipt = {
        "mode": "fresh_epoch",
        "passed": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_ledger": str(DB),
        "local_channel_counts": counts,
        "local_integrity": integrity,
        "dispatcher_delivery_counts": dispatcher_counts,
        "last_genuine_cloudflare_snapshot": str(SNAPSHOT),
        "snapshot_sha256": snapshot_hash,
        "historical_reconciliation": "pending_after_cloudflare_daily_reset",
        "old_cloudflare_durable_object": "preserved_and_not_modified",
        "stale_snapshot_replayed": False,
    }
    target = ROOT / "scratch/fleet_local_cutover_receipt.json"
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
