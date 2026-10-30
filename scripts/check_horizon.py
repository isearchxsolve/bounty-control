import sqlite3
con = sqlite3.connect('../scratch/discovery-horizon.sqlite3')
tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', tables)
for t in tables:
    try:
        rows = con.execute(f'SELECT count(*) FROM {t[0]}').fetchone()[0]
        print(f'  {t[0]}: {rows} rows')
    except:
        pass
print()
print('Recent windows:')
for r in con.execute('SELECT id, query, status FROM windows ORDER BY id DESC LIMIT 20'):
    print(f'  {r}')