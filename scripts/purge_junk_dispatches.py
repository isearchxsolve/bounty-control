import sqlite3

conn = sqlite3.connect('scratch/icu_pipeline.db')
cursor = conn.cursor()

targets = [
    'DrAndrew1/illuminati666',
    'ianrhett/crowntable',
    'UoMResearchIT/Training',
    'OmniBlocks/Boxy-gh',
    'GMDevinity/FloodIssues',
    'nhra168/chainlink',
    'teamleaderleo/bot-observatory',
    'softwary/ClaudeYourWayToTheTop',
    'urzz/repo_for_report',
    'gdtagency/facebook-agency-account-for-rent'
]

placeholders = ','.join('?' for _ in targets)
cursor.execute(f"""
    UPDATE deliveries 
    SET status = 'REJECTED_SECURITY',
        reason = 'Baba Hardness Moat: non-engineering / scam / debate / non-software issue rejected'
    WHERE repo IN ({placeholders})
""", targets)

conn.commit()
print(f"Purged {cursor.rowcount} records from database.")
