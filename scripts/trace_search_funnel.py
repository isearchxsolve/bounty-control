import subprocess
import json
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')

from autonomous_icu_pipeline import (
    non_engineering_dispatch_reason,
    is_nonsoftware_data_task,
    evaluate_custom_query_gates,
    _has_terminal_label,
    _has_payment_negation,
    _has_economic_scam_marker,
    parse_and_normalize_bounty,
    verify_genuine_icu_patient,
    detect_author_corridor,
    _has_platform_bounty_marker,
    _label_name,
    _has_direct_offer_language,
    MIN_CONSULTING_BOUND_USD,
    get_issue_fast
)

cmd = ["gh", "search", "issues", "commenter:algora-pbc", "--state", "open", "--limit", "5", "--json", "number,title,repository,url,labels,createdAt,updatedAt,commentsCount,authorAssociation,body,author"]
out = subprocess.check_output(cmd)
items = json.loads(out)

print(f"Tracing {len(items)} items from commenter:algora-pbc:")

for it in items:
    repo = it.get("repository", {}).get("nameWithOwner")
    number = it.get("number")
    title = it.get("title", "")
    body = it.get("body", "") or ""
    labels = it.get("labels", [])
    author = (it.get("author") or {}).get("login", "")
    comments_cnt = it.get("commentsCount", 0)

    print(f"\n--- Checking {repo}#{number}: {title} ---")
    
    task = {"repo": repo, "title": title, "body": body}
    agg_reason = non_engineering_dispatch_reason(task)
    if agg_reason:
        print(f"  DROPPED by non_engineering_dispatch_reason: {agg_reason}")
        continue
        
    author_object = it.get("author") or {}
    if author_object.get("is_bot") or str(author).startswith("app/"):
        print(f"  DROPPED because author is bot: {author}")
        continue
        
    gate_ok, gate_reason = evaluate_custom_query_gates(it)
    if not gate_ok:
        print(f"  DROPPED by evaluate_custom_query_gates: {gate_reason}")
        continue
        
    if _has_terminal_label(labels):
        print(f"  DROPPED by terminal label")
        continue
        
    full_text = f"{title} {body} {repo}".lower()
    if _has_payment_negation(full_text):
        print(f"  DROPPED by payment negation")
        continue
    if _has_economic_scam_marker(full_text):
        print(f"  DROPPED by economic scam marker")
        continue

    body_has_bounty, body_in_bounds, _, body_usd_val, body_reason = parse_and_normalize_bounty(f"{title} {body}")
    print(f"  Body bounty: has={body_has_bounty}, in_bounds={body_in_bounds}, val={body_usd_val}")
    
    query_str = "commenter:algora-pbc"
    query_is_platform = any(qm in query_str for qm in ("algora", "polar.sh", "opire", "bountycaster", "issuehunt", "gitcoin"))
    print(f"  query_is_platform: {query_is_platform}")
    
    need_comments = False
    if body_has_bounty:
        if body_usd_val is not None and body_usd_val < MIN_CONSULTING_BOUND_USD:
            print(f"  DROPPED body_usd_val < MIN_CONSULTING_BOUND_USD")
            continue
        if not body_in_bounds:
            print(f"  DROPPED body not in_bounds")
            continue
        is_icu_body, icu_body_reason = verify_genuine_icu_patient(
            title, body, [], labels, repo,
            author_assoc=it.get("authorAssociation", "NONE"),
            author=author,
            payer_assoc=it.get("payerAssociation", "NONE"),
            live_delivery_mode=True
        )
        print(f"  is_icu_body: {is_icu_body} ({icu_body_reason})")
        if is_icu_body:
            need_comments = False
        else:
            if comments_cnt == 0:
                print(f"  DROPPED comments_cnt == 0")
                continue
            need_comments = True
    else:
        if comments_cnt == 0:
            print(f"  DROPPED comments_cnt == 0 without body bounty")
            continue
        has_marker = (
            query_is_platform or
            _has_platform_bounty_marker(f"{title} {body}") or
            any(re.search(r"\b(?:bounty|bug\s+bounty|reward|funded|bountied)\b", _label_name(lbl), re.IGNORECASE) for lbl in (labels or [])) or
            bool(re.search(r"\[(?:bug\s+)?bounty(?:\s+[^\]]+)?\]", title or "", re.IGNORECASE)) or
            _has_direct_offer_language(f"{title} {body}")
        )
        print(f"  has_marker: {has_marker}")
        if not has_marker:
            print(f"  DROPPED no marker")
            continue
        need_comments = True
        
    print(f"  need_comments: {need_comments}")
    if need_comments and "author_comments" not in it:
        print(f"  Hydrating author comments via get_issue_fast...")
        up_data = get_issue_fast(repo, number)
        if up_data and up_data.get("state") == "OPEN":
            it["author_comments"] = up_data.get("author_comments", [])
            print(f"  Hydrated {len(it['author_comments'])} author/bot comments")
            
    total_text = f"{title} {body} " + " ".join(it.get("author_comments", []))
    has_any_bounty, any_in_bounds, raw_val, any_usd_val, any_reason = parse_and_normalize_bounty(total_text)
    print(f"  Total text bounty: has={has_any_bounty}, in_bounds={any_in_bounds}, raw={raw_val}, val={any_usd_val}, reason={any_reason}")
    
    if has_any_bounty:
        if any_usd_val is not None and any_usd_val < MIN_CONSULTING_BOUND_USD:
            print(f"  DROPPED any_usd_val < MIN_CONSULTING_BOUND_USD")
            continue
        if not any_in_bounds:
            print(f"  DROPPED any not in_bounds")
            continue
    else:
        print(f"  DROPPED no bounty in total text!")
        continue
        
    is_icu_check, icu_check_reason = verify_genuine_icu_patient(
        title, body, it.get("author_comments", []), labels, repo,
        author_assoc=it.get("authorAssociation", "NONE"),
        author=author,
        payer_assoc=it.get("payerAssociation", "NONE"),
        live_delivery_mode=True
    )
    print(f"  is_icu_check: {is_icu_check} ({icu_check_reason})")
    if not is_icu_check:
        print(f"  DROPPED by is_icu_check!")
        continue
        
    if author:
        corridor_name, _, _ = detect_author_corridor(author)
        print(f"  Corridor: {corridor_name}")
        if corridor_name in ("Excluded Regional Market", "Excluded Territory"):
            print(f"  DROPPED by corridor!")
            continue
            
    print(f"  >>> RETAINED! <<<")
