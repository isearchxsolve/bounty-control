import sqlite3
import os
import json
import sys

db_path = os.path.expanduser("~/.codex/thread_history_1.sqlite")
if not os.path.exists(db_path):
    print("Database not found.")
    sys.exit(0)

con = sqlite3.connect(db_path)
cur = con.cursor()

try:
    cur.execute("SELECT id, title, created_at, updated_at FROM threads ORDER BY updated_at DESC LIMIT 5;")
    threads = cur.fetchall()
    print("=== LATEST CODEX THREADS ===")
    for tid, title, cat, uat in threads:
        print(f"[{tid}] {title} (Updated: {uat})")
except Exception as e:
    print("Error querying threads:", e)

try:
    cur.execute("SELECT thread_id, role, content, created_at FROM messages ORDER BY id DESC LIMIT 6;")
    msgs = cur.fetchall()
    print("\n=== LATEST MESSAGES / ACTIONS ===")
    for tid, role, content, cat in msgs:
        content_preview = str(content)[:300].replace("\n", " ")
        print(f"[{cat}] {role}: {content_preview}...")
except Exception as e:
    print("Error querying messages:", e)
