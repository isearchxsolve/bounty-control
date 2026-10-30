import sys
import json
import subprocess
sys.stdout.reconfigure(encoding='utf-8')

from autonomous_icu_pipeline import (
    get_issue_fast,
    verify_genuine_icu_patient,
    score_hardness_and_competition,
    parse_and_normalize_bounty,
    detect_author_corridor
)

test_issues = [
    ("paraloom-labs/paraloom-core", 996),
    ("limitlessprojects/Go-Hybrid", 775),
    ("limitlessprojects/Go-Hybrid", 1822),
    ("Qortal/qortal", 122),
    ("patrickkellyyoung-ai/swarm-agora-mcp", 4),
    ("Feel-ix-343/markdown-oxide", 274),
]

print("--- EVALUATING CANDIDATES UNDER THE HARDNESS MOAT ---")
for repo, number in test_issues:
    data = get_issue_fast(repo, number)
    if not data:
        print(f"\n[{repo}#{number}] Failed to fetch data")
        continue
    title = data.get("title", "")
    body = data.get("body", "")
    labels = data.get("labels", [])
    author = data.get("author", "")
    assoc = data.get("authorAssociation", "NONE")
    comments = data.get("author_comments", [])
    payer_assoc = data.get("payerAssociation", "NONE")
    
    # 1. Parse Bounty
    full_text = f"{title} {body} {' '.join(comments)}"
    has_bounty, in_bounds, raw_val, usd_val, reason = parse_and_normalize_bounty(full_text)
    
    # 2. Hardness Score
    it = {
        "title": title,
        "body": body,
        "labels": labels,
        "commentsCount": data.get("commentsCount", len(comments)),
        "author": author,
        "repository": {"nameWithOwner": repo}
    }
    hardness_score = score_hardness_and_competition(it)
    
    # 3. ICU Patient Verification
    is_icu, icu_reason = verify_genuine_icu_patient(
        title, body, comments, labels, repo,
        author_assoc=assoc, author=author,
        payer_assoc=payer_assoc, live_delivery_mode=True
    )
    
    print(f"\n[{repo}#{number}] {title}")
    print(f"  Author: {author} ({assoc}) | Comments: {len(comments)}")
    print(f"  Bounty: has={has_bounty}, in_bounds={in_bounds}, raw='{raw_val}', usd={usd_val}")
    print(f"  Hardness Score: {hardness_score}")
    print(f"  ICU Qualified: {is_icu} -> {icu_reason}")
