import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import (
    search_issues, get_issue_fast, parse_and_normalize_bounty,
    verify_genuine_icu_patient, MIN_LIVE_DISPATCH_BOUNTY_USD,
    detect_author_corridor, evaluate_custom_query_gates,
    non_engineering_dispatch_reason, _has_terminal_label,
    _has_payment_negation, _has_economic_scam_marker
)
import subprocess
import json

cmd = ["gh", "search", "issues", "bounty in:title", "--state", "open", "--limit", "10", "--json", "number,title,repository,url,labels,createdAt,updatedAt,commentsCount,authorAssociation,body,author"]
out = subprocess.check_output(cmd)
items = json.loads(out)

print(f"Inspecting {len(items)} items from 'bounty in:title':")
for it in items:
    repo = it.get("repository", {}).get("nameWithOwner")
    number = it.get("number")
    title = it.get("title", "")
    body = it.get("body", "") or ""
    labels = it.get("labels", [])
    author = (it.get("author") or {}).get("login", "")
    comments_cnt = it.get("commentsCount", 0)

    print(f"\n[{repo}#{number}] {title}")
    
    # 1. Non-engineering
    task = {"repo": repo, "title": title, "body": body}
    agg = non_engineering_dispatch_reason(task)
    if agg:
        print(f"  -> Filtered by non_engineering: {agg}")
        continue

    # 2. Custom gates
    gate_ok, gate_reason = evaluate_custom_query_gates(it)
    if not gate_ok:
        print(f"  -> Filtered by custom query gate: {gate_reason}")
        continue

    # 3. Body bounty
    has_b, in_b, raw_b, usd_b, reason_b = parse_and_normalize_bounty(f"{title} {body}")
    print(f"  Body bounty: has={has_b}, raw={raw_b}, usd={usd_b}")
    
    # Comments hydration
    if comments_cnt > 0 and "author_comments" not in it:
        up = get_issue_fast(repo, number)
        if up:
            it["author_comments"] = up.get("author_comments", [])
            print(f"  Hydrated {len(it['author_comments'])} comments")
            
    total_text = f"{title} {body} " + " ".join(it.get("author_comments", []))
    has_tot, in_tot, raw_tot, usd_tot, reason_tot = parse_and_normalize_bounty(total_text)
    print(f"  Total bounty: has={has_tot}, raw={raw_tot}, usd={usd_tot}")
    
    if has_tot:
        if usd_tot is not None and usd_tot < MIN_LIVE_DISPATCH_BOUNTY_USD:
            print(f"  -> Filtered because usd={usd_tot} < floor $50")
            continue
    else:
        print("  -> Filtered because no bounty amount found")
        continue
        
    is_icu, icu_reason = verify_genuine_icu_patient(
        title, body, it.get("author_comments", []), labels, repo,
        author_assoc=it.get("authorAssociation", "NONE"),
        author=author,
        payer_assoc=it.get("payerAssociation", "NONE"),
        live_delivery_mode=True
    )
    print(f"  ICU Qualified: {is_icu} ({icu_reason})")
