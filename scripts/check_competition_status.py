import sys
sys.path.append('scripts')
import autonomous_icu_pipeline as aip

candidates = [
    ('microg/GmsCore', 2843),
    ('gyroflow/gyroflow', 742),
    ('drizzle-team/drizzle-orm', 376),
    ('SCIBASE-AI/SCIBASE.AI', 20),
    ('SCIBASE-AI/SCIBASE.AI', 16),
    ('SCIBASE-AI/SCIBASE.AI', 18),
    ('SCIBASE-AI/SCIBASE.AI', 15),
    ('SCIBASE-AI/SCIBASE.AI', 19),
    ('SCIBASE-AI/SCIBASE.AI', 14),
    ('SCIBASE-AI/SCIBASE.AI', 13),
    ('claude-builders-bounty/claude-builders-bounty', 3),
    ('claude-builders-bounty/claude-builders-bounty', 1),
]

print("=== CHECKING COMPETITION FOR HIGH-TICKET CANDIDATES ===")
for repo, num in candidates:
    has_comp, comp_reason = aip.check_competing_prs_fail_closed(repo, num)
    up = aip.get_issue_fast(repo, num)
    task = {'repo': repo, 'number': num, 'title': up.get('title', '') if up else '', 'body': up.get('body', '') if up else ''}
    score = aip.score_hardness_and_competition(task)
    print(f"[{repo}#{num}] Hardness Score: {score} | Competing PR? {has_comp} | Status: {comp_reason}")
