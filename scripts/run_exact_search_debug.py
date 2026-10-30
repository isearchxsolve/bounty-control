import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import (
    run_cmd, parse_and_normalize_bounty, verify_genuine_icu_patient,
    detect_author_corridor, non_engineering_dispatch_reason,
    is_nonsoftware_data_task, evaluate_custom_query_gates,
    _has_terminal_label, _has_payment_negation, _has_economic_scam_marker,
    _label_name, _has_platform_bounty_marker, _has_direct_offer_language,
    get_issue_fast, MIN_LIVE_DISPATCH_BOUNTY_USD, DISCOVERY_HORIZON
)
import json
import shlex
import re

query = 'commenter:algora-pbc "$100"'
limit = 10
sort_by = "created"
order = "desc"

parts = shlex.split(query) if query.lstrip().startswith('--') or any(c in query for c in (':', '$')) else [query]
clean_parts = [p for p in parts if not p.startswith("state:")]
cmd = ["gh", "search", "issues"] + clean_parts + ["--state", "open", "--archived=false", "--visibility", "public", "--sort", sort_by, "--order", order, "--limit", str(limit), "--json", "number,title,repository,url,labels,createdAt,updatedAt,commentsCount,authorAssociation,body,author"]

api_source_query = " ".join(str(part) for part in clean_parts)
search_query = " ".join(part for part in (api_source_query, "is:issue is:open is:public archived:false -label:type/experiment") if part)
cmd.extend(["--internal-search-query", search_query])

out, err, code = run_cmd(cmd, timeout=75)
raw_items = json.loads(out)
print(f"Loaded {len(raw_items)} raw items from run_cmd")

filtered_items = []
for it in raw_items:
    if not isinstance(it.get("repository"), dict):
        repo_name = None
        if it.get("repository_url"):
            repo_name = "/".join(it["repository_url"].split("/")[-2:])
        elif it.get("html_url"):
            m = re.match(r"https?://github\.com/([^/]+/[^/]+)/", it["html_url"])
            if m:
                repo_name = m.group(1)
        it["repository"] = {"nameWithOwner": repo_name} if repo_name else {}

    if "commentsCount" not in it:
        it["commentsCount"] = it.get("comments", 0)
    if "authorAssociation" not in it:
        it["authorAssociation"] = it.get("author_association", "NONE")
    if "author" not in it:
        it["author"] = it.get("user") or {}
    if "createdAt" not in it:
        it["createdAt"] = it.get("created_at", "")

    repo = it.get("repository", {}).get("nameWithOwner")
    number = it.get("number")
    title = it.get("title", "")
    body = it.get("body", "") or ""
    labels = it.get("labels", [])
    _author_assoc = (it.get("authorAssociation") or "NONE").upper()
    author = (it.get("author") or {}).get("login", "")

    print(f"\nChecking [{repo}#{number}] {title}")
    if not repo or not number:
        print("  -> Dropped: missing repo or number")
        continue

    task = {"repo": repo, "title": title, "body": body}
    agg_reason = non_engineering_dispatch_reason(task)
    if agg_reason:
        print(f"  -> Dropped by non_engineering: {agg_reason}")
        continue

    gate_ok, gate_reason = evaluate_custom_query_gates(it)
    if not gate_ok:
        print(f"  -> Dropped by gate: {gate_reason}")
        continue

    comments_cnt = it.get("commentsCount", 0)
    body_has_bounty, body_in_bounds, _, body_usd_val, _ = parse_and_normalize_bounty(f"{title} {body}")
    print(f"  body_has_bounty={body_has_bounty}, val={body_usd_val}, comments_cnt={comments_cnt}")

    need_comments = False
    if body_has_bounty:
        if body_usd_val is not None and body_usd_val < MIN_LIVE_DISPATCH_BOUNTY_USD:
            print(f"  -> Dropped: body_usd_val={body_usd_val} < {MIN_LIVE_DISPATCH_BOUNTY_USD}")
            continue
        need_comments = True
    else:
        if comments_cnt == 0:
            print("  -> Dropped: comments_cnt == 0 without body bounty")
            continue
        need_comments = True

    if need_comments and "author_comments" not in it:
        print("  -> Hydrating comments via get_issue_fast...")
        up_data = get_issue_fast(repo, number)
        if up_data and up_data.get("state") == "OPEN":
            it["author_comments"] = up_data.get("author_comments", [])
            it["authorAssociation"] = up_data.get("authorAssociation", it.get("authorAssociation", "NONE"))
            it["payerAssociation"] = up_data.get("payerAssociation", "NONE")
            it["labels"] = up_data.get("labels", labels)
            it["body"] = up_data.get("body", body)
            body, labels = it["body"], it["labels"]
            print(f"  -> Hydrated {len(it['author_comments'])} comments")

    total_text = f"{title} {body} " + " ".join(it.get("author_comments", []))
    has_any_bounty, any_in_bounds, _, any_usd_val, any_reason = parse_and_normalize_bounty(total_text)
    print(f"  total_text bounty: has={has_any_bounty}, val={any_usd_val}, reason={any_reason}")

    if has_any_bounty:
        if any_usd_val is not None and any_usd_val < MIN_LIVE_DISPATCH_BOUNTY_USD:
            print(f"  -> Dropped: any_usd_val={any_usd_val} < {MIN_LIVE_DISPATCH_BOUNTY_USD}")
            continue
        if not any_in_bounds:
            print("  -> Dropped: not in bounds")
            continue
    else:
        print("  -> Dropped: no bounty amount found")
        continue

    is_icu_check, icu_reason = verify_genuine_icu_patient(
        title, body, it.get("author_comments", []), labels, repo,
        author_assoc=it.get("authorAssociation", "NONE"),
        author=author,
        payer_assoc=it.get("payerAssociation", "NONE"),
        live_delivery_mode=True,
    )
    print(f"  ICU Qualified: {is_icu_check} ({icu_reason})")
    if not is_icu_check:
        continue

    filtered_items.append(it)
    print("  >>> RETAINED! <<<")

print(f"\nFinal retained items: {len(filtered_items)}")
