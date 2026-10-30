import sys
sys.path.append('scripts')
import autonomous_icu_pipeline as aip
import json

queries = [
    '--commenter algora-pbc',
    'opire.dev',
    'polar.sh',
    'bounty "$100"',
    'bounty "$250"',
    'bounty "$500"',
    '"will pay" "$100"',
    '"will pay" "$500"',
]

print("=== SEARCHING FOR UNCONTESTED, HIGH-TICKET CANDIDATE BOUNTIES ===")
uncontested = []
for q in queries:
    items = aip.search_issues(q, limit=20)
    for it in items:
        repo = it.get('repository', {}).get('nameWithOwner')
        num = it.get('number')
        title = it.get('title', '')
        if not repo or not num:
            continue
        has_comp, comp_reason = aip.check_competing_prs_fail_closed(repo, num)
        if not has_comp and "Competing open PR" not in comp_reason:
            print(f"  ★ UNCONTESTED CANDIDATE: [{repo}#{num}] {title[:70]}")
            uncontested.append((repo, num, title, comp_reason))
        else:
            print(f"  [COMPETED] [{repo}#{num}]: {comp_reason[:60]}")

print(f"\nTOTAL UNCONTESTED HIGH-TICKET CANDIDATES FOUND: {len(uncontested)}")
for r, n, t, c in uncontested:
    print(f"  - {r}#{n}: {t} ({c})")
