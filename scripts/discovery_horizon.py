"""Persistent creation-time partitions for GitHub's 1,000-result search ceiling."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class Horizon:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=30)
        con.execute('CREATE TABLE IF NOT EXISTS windows ('
                    'id INTEGER PRIMARY KEY, query TEXT, lo INTEGER, hi INTEGER, '
                    'status TEXT DEFAULT "pending")')
        return con

    def window(self, query, now=None):
        now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
        with closing(self.connect()) as con, con:
            row = con.execute('SELECT id, lo, hi FROM windows WHERE query=? '
                              'AND status="pending" ORDER BY id LIMIT 1', (query,)).fetchone()
            if row:
                return row
            # Start a new sweep only after every previous partition was visited.
            lo = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
            cursor = con.execute('INSERT INTO windows(query,lo,hi) VALUES (?,?,?)', (query, lo, now))
            return cursor.lastrowid, lo, now

    @staticmethod
    def qualifier(window):
        def stamp(epoch):
            return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return f'{stamp(window[1])}..{stamp(window[2])}'

    def complete(self, query, window, returned, limit, *, saturated=None):
        ident, lo, hi = window
        capped = returned >= limit if saturated is None else saturated
        with closing(self.connect()) as con, con:
            status = 'split' if capped and lo < hi else 'saturated' if capped else 'complete'
            changed = con.execute('UPDATE windows SET status=? WHERE id=? AND status="pending"',
                                  (status, ident)).rowcount
            if changed and status == 'split':
                middle = (lo + hi) // 2
                con.executemany('INSERT INTO windows(query,lo,hi) VALUES (?,?,?)',
                                [(query, lo, middle), (query, middle + 1, hi)])
        return status
