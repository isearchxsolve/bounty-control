"""Page authentic retained fleet ledger rows into the loopback SQLite relay.

Writes are opt-in with --apply. This script never changes Worker routing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request

CHANNELS = (
    "BOUNTY_FLEET_QUEUE_V2",
    "BOUNTY_FLEET_CLAIM",
    "BOUNTY_FLEET_LEASE",
    "BOUNTY_FLEET_RESULT",
    "BOUNTY_FLEET_EXECUTION",
    "ENGINE_REGISTRATION",
)
REMOTE_PAGE_SIZE = 200
LOCAL_PAGE_SIZE = 500
DEFAULT_DOOR = "https://omniroute-relay.omniroute-fleet-kd.workers.dev"
DEFAULT_ADMIN_FILE = Path(r"D:\anonym\vault\fleet_relay_admin_token.txt")


def request_json(url: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    payload = None if data is None else json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; fleet-ledger-migration/1.0)"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=payload, headers=request_headers, method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from relay: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"relay network failure: {getattr(exc, 'reason', str(exc))}") from None
    if not isinstance(value, dict):
        raise RuntimeError("relay returned a non-object JSON response")
    return value


def digest_rows(rows: list[dict]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        canonical = json.dumps({"at": str(row["at"]), "text": row["text"]},
                               ensure_ascii=False, separators=(",", ":")).encode()
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
    return digest.hexdigest()


def row_pair(row: dict) -> tuple[str, str]:
    if not isinstance(row, dict) or "at" not in row or not isinstance(row.get("text"), str):
        raise RuntimeError("ledger page contains an invalid receipt")
    return str(row["at"]), row["text"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--door", default=os.environ.get("FLEET_DOOR", DEFAULT_DOOR))
    parser.add_argument("--local", default="http://127.0.0.1:8778")
    parser.add_argument("--admin-file", type=Path, default=Path(os.environ.get("FLEET_RELAY_ADMIN_TOKEN_FILE", DEFAULT_ADMIN_FILE)))
    parser.add_argument("--receipt", type=Path, default=Path(r"D:\anonym\scratch\fleet_local_cutover_receipt.json"))
    parser.add_argument("--apply", action="store_true", help="import verified source pages into SQLite")
    parser.add_argument("--channels", nargs="+", choices=CHANNELS, default=list(CHANNELS))
    args = parser.parse_args()
    token = os.environ.get("FLEET_DOOR_TOKEN") or os.environ.get("OMNIROUTE_TOKEN")
    if not token:
        raise RuntimeError("FLEET_DOOR_TOKEN or OMNIROUTE_TOKEN must be set; token value is never printed")
    if not args.door.startswith("https://"):
        raise RuntimeError("source door must use HTTPS")
    admin_token = ""
    if args.apply:
        admin_token = args.admin_file.read_text(encoding="utf-8").strip()
        if len(admin_token) < 32:
            raise RuntimeError("local admin token file is missing or too short")
    remote_base = args.door.rstrip("/")
    local_base = args.local.rstrip("/")
    api_token = urllib.parse.quote(token, safe="")
    local_token = urllib.parse.quote(os.environ.get("FLEET_RELAY_TOKEN", "GOLD24"), safe="")
    admin_headers = {"X-Fleet-Admin-Token": admin_token, "Content-Type": "application/json"}
    summaries = []

    health_query = urllib.parse.urlencode({"token": token})
    remote_health = request_json(f"{remote_base}/health?{health_query}")
    if remote_health.get("service") != "omniroute-relay-worker" or remote_health.get("version") != "3.5.0-local-fleet-origin-proxy":
        raise RuntimeError("source Worker is not the verified pagination-capable release")

    for channel in args.channels:
        source_rows: list[dict] = []
        initial_count = None
        for offset in range(0, 2000, REMOTE_PAGE_SIZE):
            query = urllib.parse.urlencode({"token": token, "body": channel,
                                            "limit": REMOTE_PAGE_SIZE, "offset": offset})
            page = request_json(f"{remote_base}/say?{query}")
            count = page.get("count")
            orders = page.get("orders")
            if not isinstance(count, int) or count < 0 or count > 2000 or not isinstance(orders, list):
                raise RuntimeError(f"{channel}: source count/page is invalid or exceeds retained ledger cap")
            if initial_count is None:
                initial_count = count
            elif count != initial_count:
                raise RuntimeError(f"{channel}: source count changed during migration; retry after pausing writers")
            if len(orders) > REMOTE_PAGE_SIZE or len(source_rows) + len(orders) > initial_count:
                raise RuntimeError(f"{channel}: source returned more rows than its declared count")
            for row in orders:
                row_pair(row)
            source_rows.extend(orders)
            if args.apply and orders:
                source_page = [dict(row, source_key=f"{channel}:{offset + index}")
                               for index, row in enumerate(orders)]
                result = request_json(f"{local_base}/admin/import?token={local_token}",
                                      data={"channel": channel, "orders": source_page}, headers=admin_headers)
                if result.get("ok") is not True:
                    raise RuntimeError(f"{channel}: local import rejected a page")
            if not orders:
                break
        if initial_count is None or len(source_rows) != initial_count:
            raise RuntimeError(f"{channel}: incomplete export ({len(source_rows)} of {initial_count})")

        after_query = urllib.parse.urlencode({"token": token, "body": channel, "limit": 1, "offset": 0})
        after = request_json(f"{remote_base}/say?{after_query}")
        if after.get("count") != initial_count:
            raise RuntimeError(f"{channel}: source changed during export; do not switch routing")

        if args.apply:
            local_rows: list[dict] = []
            for offset in range(0, initial_count, LOCAL_PAGE_SIZE):
                query = urllib.parse.urlencode({"token": local_token, "channel": channel,
                                                "limit": LOCAL_PAGE_SIZE, "offset": offset})
                page = request_json(f"{local_base}/admin/export?{query}", headers={"X-Fleet-Admin-Token": admin_token})
                if page.get("ok") is not True or page.get("count") != initial_count:
                    raise RuntimeError(f"{channel}: local row count does not match source")
                local_rows.extend(page.get("orders", []))
            if len(local_rows) != initial_count or digest_rows(local_rows) != digest_rows(source_rows):
                raise RuntimeError(f"{channel}: local receipt content/order hash differs from source")
        summaries.append({"channel": channel, "count": initial_count,
                          "sha256": digest_rows(source_rows), "verified": True})
        print(json.dumps(summaries[-1], sort_keys=True), flush=True)

    local_health_query = urllib.parse.urlencode({"token": local_token})
    health = request_json(f"{local_base}/fleet/health?{local_health_query}")
    if health.get("ready") is not True:
        raise RuntimeError("local fleet relay health did not pass")
    receipt = {"source": urllib.parse.urlsplit(args.door).netloc, "mode": "migrated" if args.apply else "read_only",
               "created_at_utc": datetime.now(timezone.utc).isoformat(),
               "channels": summaries, "passed": all(row["verified"] for row in summaries)}
    if receipt["passed"]:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"migration stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
