"""Exercise the SQLite relay over loopback using genuine saved fleet receipts."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import unittest
import uuid

import fleet_local_relay as relay


class LocalFleetRelayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent
        snapshot_path = Path(os.environ.get(
            "FLEET_RECOVERY_SNAPSHOT", root / "scratch/fleet_recovery_live_snapshot_20261026.json"
        ))
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        cls.records = {
            "BOUNTY_FLEET_QUEUE_V2": snapshot["queue"],
            "BOUNTY_FLEET_CLAIM": snapshot["claims"],
            "BOUNTY_FLEET_RESULT": snapshot["results"],
        }
        assert all(cls.records.values()), "Authentic fleet ledger receipts are required"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fleet-ledger-integration-")
        self.old = (relay.DB_PATH, relay.TOKEN, relay.ADMIN_TOKEN)
        relay.DB_PATH = Path(self.temp.name) / "fleet.sqlite3"
        relay.TOKEN = "loopback-test-token"
        relay.ADMIN_TOKEN = "loopback-test-admin"
        relay.initialize()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        self.server = ThreadingHTTPServer(("127.0.0.1", port), relay.Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        relay.DB_PATH, relay.TOKEN, relay.ADMIN_TOKEN = self.old
        self.temp.cleanup()

    def call(self, channel, offset=0, limit=500):
        query = urlencode({"token": relay.TOKEN, "channel": channel, "offset": offset, "limit": limit})
        request = Request(self.base + "/admin/export?" + query,
                          headers={"X-Fleet-Admin-Token": relay.ADMIN_TOKEN})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def import_receipts(self):
        for channel, orders in self.records.items():
            for offset in range(0, len(orders), relay.IMPORT_PAGE_SIZE):
                page = orders[offset:offset + relay.IMPORT_PAGE_SIZE]
                source_page = [dict(row, source_key=f"{channel}:{offset + i}") for i, row in enumerate(page)]
                request = Request(
                    f"{self.base}/admin/import?token={relay.TOKEN}",
                    data=json.dumps({"channel": channel, "orders": source_page}).encode(),
                    headers={"Content-Type": "application/json", "X-Fleet-Admin-Token": relay.ADMIN_TOKEN},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    self.assertTrue(json.load(response)["ok"])

    def test_genuine_receipts_import_in_order_and_survive_reopen(self):
        self.import_receipts()
        for channel, expected in self.records.items():
            result = self.call(channel, 0, 5000)
            self.assertEqual(result["count"], len(expected))
            self.assertEqual([(r["at"], r["text"]) for r in result["orders"]],
                             [(str(r["at"]), r["text"]) for r in expected])
            page = self.call(channel, 1, 3)
            self.assertEqual([r["text"] for r in page["orders"]], [r["text"] for r in expected[1:4]])
        with relay.connection() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_append_idempotency_and_authentication(self):
        self.import_receipts()
        channel = "BOUNTY_FLEET_RESULT"
        real = self.records[channel][0]
        key = "receipt-test-" + uuid.uuid4().hex
        for _ in range(2):
            request = Request(
                f"{self.base}/say?token={relay.TOKEN}",
                data=json.dumps({"body": channel, "text": real["text"], "at": real["at"]}).encode(),
                headers={"Content-Type": "application/json", "Idempotency-Key": key},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                self.assertTrue(json.load(response)["stored"])
        self.assertEqual(self.call(channel, 0, 5000)["count"], len(self.records[channel]) + 1)
        denied = Request(f"{self.base}/admin/export?token={relay.TOKEN}&channel={channel}")
        with self.assertRaises(HTTPError) as error:
            urlopen(denied, timeout=10)
        self.assertEqual(error.exception.code, 403)
        with urlopen(f"{self.base}/health?token={relay.TOKEN}", timeout=10) as response:
            self.assertTrue(json.load(response)["ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
