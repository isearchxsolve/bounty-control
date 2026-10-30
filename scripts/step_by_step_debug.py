import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import run_cmd, parse_and_normalize_bounty, verify_genuine_icu_patient, detect_author_corridor, non_engineering_dispatch_reason, evaluate_custom_query_gates, _has_terminal_label, _has_payment_negation, _has_economic_scam_marker
import json
import re

cmd = ["gh", "search", "issues", "commenter:algora-pbc", "$100", "--state", "open", "--limit", "10", "--json", "number,title,repository,url,labels,createdAt,updatedAt,commentsCount,authorAssociation,body,author"]
out, err, code = run_cmd(cmd)
raw_items = json.loads(out)

# Find microg/GmsCore
target = None
for it in raw_items:
    if "microg" in str(it):
        target = it
        break

if not target:
    print("microg not in raw_items! Items were:")
    for it in raw_items:
        print(" ", it.get("repository_url") or it.get("repository"), it.get("number"), it.get("title"))
    sys.exit(0)

print("Found target:", target.get("title"))
# Step through exactly what search_issues does:
it = target
# 1. normalize
repo = None
if isinstance(it.get("repository"), dict):
    repo = it.get("repository", {}).get("nameWithOwner")
elif it.get("repository_url"):
    repo = "/".join(it["repository_url"].split("/")[-2:])

number = it.get("number")
title = it.get("title", "")
body = it.get("body", "") or ""
labels = it.get("labels", [])
author = (it.get("author") or {}).get("login", "")
comments_cnt = it.get("commentsCount", it.get("comments", 0))

print("Step 1: repo=", repo, "number=", number, "author=", author)
if not repo or not number:
    print("FAIL step 1: no repo/number")
    sys.exit(0)

task = {"repo": repo, "title": title, "body": body}
agg = non_engineering_dispatch_reason(task)
print("Step 2: agg_reason=", agg)
if agg:
    print("FAIL step 2")
    sys.exit(0)

gate_ok, gate_reason = evaluate_custom_query_gates(it)
print("Step 3: gate_ok=", gate_ok, gate_reason)
if not gate_ok:
    print("FAIL step 3")
    sys.exit(0)

body_has_bounty, body_in_bounds, _, body_usd_val, _ = parse_and_normalize_bounty(f"{title} {body}")
print(f"Step 4: body_bounty has={body_has_bounty}, in_bounds={body_in_bounds}, val={body_usd_val}")

is_icu_body, icu_body_reason = verify_genuine_icu_patient(
    title, body, [], labels, repo,
    author_assoc=it.get("author_association", "NONE"),
    author=author,
    payer_assoc=it.get("payerAssociation", "NONE"),
    live_delivery_mode=True
)
print(f"Step 5: is_icu_body={is_icu_body} ({icu_body_reason})")
