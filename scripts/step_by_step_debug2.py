import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import run_cmd, parse_and_normalize_bounty, verify_genuine_icu_patient, detect_author_corridor, non_engineering_dispatch_reason, evaluate_custom_query_gates, get_issue_fast, MIN_LIVE_DISPATCH_BOUNTY_USD
import json

cmd = ["gh", "search", "issues", "commenter:algora-pbc", "$100", "--state", "open", "--limit", "10", "--json", "number,title,repository,url,labels,createdAt,updatedAt,commentsCount,authorAssociation,body,author"]
out, err, code = run_cmd(cmd)
raw_items = json.loads(out)

target = None
for it in raw_items:
    if "microg" in str(it):
        target = it
        break

it = target
repo = "/".join(it["repository_url"].split("/")[-2:])
number = it.get("number")
title = it.get("title", "")
body = it.get("body", "") or ""
labels = it.get("labels", [])
author = (it.get("author") or {}).get("login", "")
comments_cnt = it.get("commentsCount", it.get("comments", 0))

# Hydrate comments
up_data = get_issue_fast(repo, number)
if up_data and up_data.get("state") == "OPEN":
    it["author_comments"] = up_data.get("author_comments", [])
    it["authorAssociation"] = up_data.get("authorAssociation", it.get("authorAssociation", "NONE"))
    it["payerAssociation"] = up_data.get("payerAssociation", "NONE")
    it["labels"] = up_data.get("labels", labels)
    it["body"] = up_data.get("body", body)
    body, labels = it["body"], it["labels"]

total_text = f"{title} {body} " + " ".join(it.get("author_comments", []))
has_any_bounty, any_in_bounds, _, any_usd_val, any_reason = parse_and_normalize_bounty(total_text)
print(f"Step 6: Total bounty has={has_any_bounty}, any_usd_val={any_usd_val}, reason={any_reason}")

if has_any_bounty:
    if any_usd_val is not None and any_usd_val < MIN_LIVE_DISPATCH_BOUNTY_USD:
        print("FAIL step 6: below floor")
        sys.exit(0)
    if not any_in_bounds:
        print("FAIL step 6: not in bounds")
        sys.exit(0)
else:
    print("FAIL step 6: no bounty")
    sys.exit(0)

is_icu_check, icu_reason = verify_genuine_icu_patient(
    title,
    body,
    it.get("author_comments", []),
    labels,
    repo,
    author_assoc=it.get("authorAssociation", "NONE"),
    author=author,
    payer_assoc=it.get("payerAssociation", "NONE"),
    live_delivery_mode=True,
)
print(f"Step 7: is_icu_check={is_icu_check} ({icu_reason})")
if not is_icu_check:
    print("FAIL step 7: ICU check failed")
    sys.exit(0)

corridor_name, _, _ = detect_author_corridor(author)
print(f"Step 8: Corridor={corridor_name}")
if corridor_name in ("Excluded Regional Market", "Excluded Territory"):
    print("FAIL step 8: Corridor excluded")
    sys.exit(0)

print("SUCCESS: RETAINED!")
