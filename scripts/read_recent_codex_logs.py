import sqlite3
import os

db_logs = os.path.expanduser("~/.codex/logs_2.sqlite")
con2 = sqlite3.connect(db_logs)
cur2 = con2.cursor()
cur2.execute("SELECT timestamp, level, message FROM logs ORDER BY id DESC LIMIT 15;")
rows = cur2.fetchall()
print("=== RECENT CODEX LOGS ===")
for ts, lvl, msg in reversed(rows):
    print(f"[{ts}] [{lvl}] {msg[:180]}")

db_hist = os.path.expanduser("~/.codex/thread_history_1.sqlite")
con1 = sqlite3.connect(db_hist)
cur1 = con1.cursor()
cur1.execute("SELECT thread_id, item_type, content FROM thread_items ORDER BY rowid DESC LIMIT 5;")
print("\n=== RECENT THREAD ITEMS ===")
for tid, itype, cnt in cur1.fetchall():
    print(f"[{itype}] {str(cnt)[:200]}")
