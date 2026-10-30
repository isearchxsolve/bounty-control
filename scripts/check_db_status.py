import sqlite3

con = sqlite3.connect('scratch/icu_pipeline.db')
cur = con.cursor()
print('Total rows:', cur.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0])
print('Status counts:')
for row in cur.execute('SELECT status, count(*) FROM deliveries GROUP BY status'):
    print(' ', row)
print('\nDISPATCHED_TO_KAGGLE:')
for row in cur.execute("SELECT repo, issue_number, status, pr_url, delivered_at FROM deliveries WHERE status = 'DISPATCHED_TO_KAGGLE'"):
    print(' ', row)
