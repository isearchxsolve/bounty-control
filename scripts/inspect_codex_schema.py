import sqlite3
import os

db_path = os.path.expanduser("~/.codex/thread_history_1.sqlite")
con = sqlite3.connect(db_path)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables in thread_history_1.sqlite:", cur.fetchall())

db_logs = os.path.expanduser("~/.codex/logs_2.sqlite")
if os.path.exists(db_logs):
    con2 = sqlite3.connect(db_logs)
    cur2 = con2.cursor()
    cur2.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("Tables in logs_2.sqlite:", cur2.fetchall())
