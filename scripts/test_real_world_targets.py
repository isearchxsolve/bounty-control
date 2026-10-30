import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import (
    get_issue_fast, parse_and_normalize_bounty, verify_genuine_icu_patient,
    score_hardness_and_competition, detect_author_corridor
)
import json

targets = [
    ("commaai/opendbc", 1175),
    ("microg/GmsCore", 2843),
    ("gyroflow/gyroflow", 742),
    ("drizzle-team/drizzle-orm", 376),
    ("Thinkmill/keystatic", 340),
    ("paraloom-labs/paraloom-core", 996),
    ("claude-builders-bounty/claude-builders-bounty", 1),
]

print("=== EVALUATING HIGH-TICKET REAL WORLD BOUNTIES ===")
for repo, num in targets:
    it = get_issue_fast(repo, num)
    if not it:
        print(f"[{repo}#{num}] Not found")
        continue
    title = it.get("title", "")
    body = it.get("body", "")
    labels = it.get("labels", [])
    author = it.get("author", "")
    assoc = it.get("authorAssociation", "NONE")
    comments = it.get("author_comments", [])
    payer_assoc = it.get("payerAssociation", "NONE")
    
    total_text = f"{title} {body} {' '.join(comments)}"
    has_b, in_b, raw_b, usd_b, reason_b = parse_and_normalize_bounty(total_text)
    
    it_score = {
        "title": title, "body": body, "labels": labels,
        "commentsCount": it.get("commentsCount", len(comments)),
        "repository": {"nameWithOwner": repo}
    }
    hardness = score_hardness_and_competition(it_score)
    
    is_icu, icu_reason = verify_genuine_icu_patient(
        title, body, comments, labels, repo,
        author_assoc=assoc, author=author,
        payer_assoc=payer_assoc, live_delivery_mode=True
    )
    print(f"\n[{repo}#{num}] {title}")
    print(f"  Author: {author} ({assoc}) | Comments: {len(comments)}")
    print(f"  Bounty: raw='{raw_b}', usd={usd_b} | Reason: {reason_b}")
    print(f"  Hardness Score: {hardness}")
    print(f"  ICU Status: {is_icu} -> {icu_reason}")
