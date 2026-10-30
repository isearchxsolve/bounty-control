#!/usr/bin/env python3
"""Durable loopback fleet ledger for relay requests proxied by son-relay.js."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

HOST = "127.0.0.1"
PORT = int(os.environ.get("FLEET_RELAY_PORT", "8779"))
TOKEN = os.environ.get("FLEET_RELAY_TOKEN", "GOLD24")
DB_PATH = Path(os.environ.get("FLEET_RELAY_DB", r"D:\anonym\war-log\fleet-ledger.sqlite3"))
ADMIN_TOKEN_FILE = Path(os.environ.get("FLEET_RELAY_ADMIN_TOKEN_FILE", r"D:\anonym\vault\fleet_relay_admin_token.txt"))
try:
    ADMIN_TOKEN = ADMIN_TOKEN_FILE.read_text(encoding="utf-8").strip()
except OSError:
    ADMIN_TOKEN = ""
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_PAGE_SIZE = 5000
IMPORT_PAGE_SIZE = 500
FLEET_CHANNELS = {
    "BOUNTY_FLEET_QUEUE_V2",
    "BOUNTY_FLEET_CLAIM",
    "BOUNTY_FLEET_LEASE",
    "BOUNTY_FLEET_RESULT",
    "BOUNTY_FLEET_EXECUTION",
    "ENGINE_REGISTRATION",
}
_SCHEMA_LOCK = threading.Lock()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


@contextmanager
def connection():
    db = connect()
    try:
        yield db
    finally:
        db.close()


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _SCHEMA_LOCK, connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS fleet_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                text TEXT NOT NULL,
                at TEXT NOT NULL,
                idempotency_key TEXT,
                source_key TEXT UNIQUE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS fleet_events_channel_seq ON fleet_events(channel,seq)")
        db.execute("CREATE INDEX IF NOT EXISTS fleet_events_idempotency ON fleet_events(channel,idempotency_key)")


def _count(channel: str) -> int:
    with connection() as db:
        return int(db.execute("SELECT COUNT(*) FROM fleet_events WHERE channel=?", (channel,)).fetchone()[0])


def _read(channel: str, limit: int, offset: int) -> list[dict]:
    safe_limit = max(1, min(limit, MAX_PAGE_SIZE))
    safe_offset = max(0, offset)
    with connection() as db:
        rows = db.execute(
            "SELECT at,text FROM fleet_events WHERE channel=? ORDER BY seq DESC LIMIT ? OFFSET ?",
            (channel, safe_limit, safe_offset),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]


def _read_page(channel: str, limit: int, offset: int) -> list[dict]:
    """Read a stable oldest-to-newest page for one-time ledger migration."""
    safe_limit = max(1, min(limit, IMPORT_PAGE_SIZE))
    safe_offset = max(0, offset)
    with connection() as db:
        rows = db.execute(
            "SELECT at,text FROM fleet_events WHERE channel=? ORDER BY seq ASC LIMIT ? OFFSET ?",
            (channel, safe_limit, safe_offset),
        ).fetchall()
        return [dict(row) for row in rows]


class Handler(BaseHTTPRequestHandler):
    server_version = "FleetLedger/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Tokens and full issue payloads are never copied into the access log.
        print(f"[fleet-relay] {self.command} {urlsplit(self.path).path} {args[1] if len(args)>1 else ''}", flush=True)

    def reply(self, status: int, value: dict) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def query(self) -> tuple[dict[str, list[str]], str]:
        parsed = urlsplit(self.path)
        values = parse_qs(parsed.query, keep_blank_values=True)
        token = values.get("token", [""])[0]
        if token != TOKEN:
            self.reply(401, {"ok": False, "err": "unauthorized"})
            return values, ""
        return values, parsed.path

    def admin_authorized(self) -> bool:
        presented = self.headers.get("X-Fleet-Admin-Token", "")
        return bool(ADMIN_TOKEN) and hmac.compare_digest(presented, ADMIN_TOKEN)

    def do_GET(self):
        values, path = self.query()
        if not path:
            return
        if path in ("/health", "/fleet/health"):
            try:
                with connection() as db:
                    db.execute("SELECT 1").fetchone()
                return self.reply(200, {"ok": True, "service": "fleet-local-ledger", "storage": "sqlite", "ready": True})
            except sqlite3.Error:
                return self.reply(503, {"ok": False, "service": "fleet-local-ledger", "ready": False})
        if path == "/admin/export":
            if not self.admin_authorized():
                return self.reply(403, {"ok": False, "err": "admin_auth_required"})
            channel = values.get("channel", [""])[0]
            if channel not in FLEET_CHANNELS:
                return self.reply(400, {"ok": False, "err": "unknown_fleet_channel"})
            try:
                limit = max(1, min(int(values.get("limit", [str(IMPORT_PAGE_SIZE)])[0]), IMPORT_PAGE_SIZE))
                offset = max(0, int(values.get("offset", ["0"])[0]))
                orders = _read_page(channel, limit, offset)
                for index, row in enumerate(orders, start=offset):
                    row["source_key"] = f"{channel}:{index}"
                return self.reply(200, {"ok": True, "channel": channel, "orders": orders,
                                        "count": _count(channel), "next_offset": offset + len(orders)})
            except (ValueError, sqlite3.Error):
                return self.reply(400, {"ok": False, "err": "invalid_export_request"})
        if path != "/say":
            return self.reply(404, {"ok": False, "err": "not_found"})
        channel = values.get("body", [""])[0]
        if channel not in FLEET_CHANNELS:
            return self.reply(400, {"ok": False, "err": "unknown_fleet_channel"})
        try:
            limit = int(values.get("limit", ["20"])[0])
            offset = int(values.get("offset", ["0"])[0])
            orders = _read(channel, limit, offset)
            return self.reply(200, {"orders": orders, "count": _count(channel)})
        except (ValueError, sqlite3.Error):
            return self.reply(400, {"ok": False, "err": "invalid_read_request"})

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                self.reply(413, {"ok": False, "err": "invalid_body_size"})
                return None
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("object required")
            return value
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self.reply(400, {"ok": False, "err": "invalid_json"})
            return None

    def do_POST(self):
        values, path = self.query()
        if not path:
            return
        if path not in ("/say", "/admin/import"):
            return self.reply(404, {"ok": False, "err": "not_found"})
        payload = self._read_json()
        if payload is None:
            return
        if path == "/say":
            channel, text = payload.get("body"), payload.get("text")
            if not isinstance(channel, str) or channel not in FLEET_CHANNELS or not isinstance(text, str) or not text or len(text.encode("utf-8")) > 1000000:
                return self.reply(400, {"ok": False, "err": "invalid_ledger_event"})
            if channel == "BOUNTY_FLEET_QUEUE_V2":
                try:
                    task = json.loads(text)
                except ValueError:
                    return self.reply(400, {"ok": False, "stored": False, "err": "invalid_fleet_task_json"})
                if not isinstance(task, dict) or not all(task.get(key) for key in ("task_id", "repo", "issue_number")):
                    return self.reply(400, {"ok": False, "stored": False, "err": "invalid_fleet_task"})
            idem = self.headers.get("Idempotency-Key", "")[:160] or None
            at = payload.get("at", time.time())
            encoded_at = str(at)
            try:
                with connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if idem:
                        row = db.execute(
                            "SELECT seq,text,at FROM fleet_events WHERE channel=? AND idempotency_key=?",
                            (channel, idem),
                        ).fetchone()
                    else:
                        row = None
                    if row:
                        if row["text"] != text or row["at"] != encoded_at:
                            db.rollback()
                            return self.reply(409, {"ok": False, "stored": False, "err": "idempotency_conflict"})
                        seq = int(row[0])
                    else:
                        cursor = db.execute(
                            "INSERT INTO fleet_events(channel,text,at,idempotency_key) VALUES(?,?,?,?)",
                            (channel, text, encoded_at, idem),
                        )
                        seq = int(cursor.lastrowid)
                    db.commit()
                return self.reply(200, {"ok": True, "stored": True, "delivered_to": channel,
                                        "seq": seq, "queued": _count(channel),
                                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
            except sqlite3.Error:
                return self.reply(503, {"ok": False, "stored": False, "err": "ledger_write_failed"})
        if not self.admin_authorized():
            return self.reply(403, {"ok": False, "err": "admin_auth_required"})
        channel = payload.get("channel")
        rows = payload.get("orders")
        if not isinstance(channel, str) or channel not in FLEET_CHANNELS or not isinstance(rows, list) or len(rows) > IMPORT_PAGE_SIZE:
            return self.reply(400, {"ok": False, "err": "invalid_import_page"})
        try:
            with connection() as db:
                db.execute("BEGIN IMMEDIATE")
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get("text"), str) or "at" not in row:
                        raise ValueError("invalid source receipt")
                    source_key = row.get("source_key")
                    if not isinstance(source_key, str) or not source_key.startswith(channel + ":"):
                        raise ValueError("source key required")
                    db.execute(
                        "INSERT OR IGNORE INTO fleet_events(channel,text,at,source_key) VALUES(?,?,?,?)",
                        (channel, row["text"], str(row["at"]), source_key),
                    )
                db.commit()
            return self.reply(200, {"ok": True, "imported": len(rows), "count": _count(channel)})
        except (sqlite3.Error, ValueError):
            return self.reply(400, {"ok": False, "err": "import_page_rejected"})

    def do_HEAD(self):
        return self.reply(405, {"ok": False, "err": "method_not_allowed"})


def main():
    initialize()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Fleet SQLite ledger ready on {HOST}:{PORT}; database={DB_PATH}", flush=True)
    server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
