"""Would the engine take a real, live, platform-funded ticket today?

Hydrates real open bounty issues and runs the production admission gate on each, printing
the named reason. Read-only: no dispatch, no branch, no PR.
"""
import json, os, sys
from urllib.parse import urlencode
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from actions_github import GitHub
from bounty_admission import admit, engineering_evidence, engineering_signal

QUERIES = [
    'is:issue is:open in:comments algora-pbc created:>2026-09-01',
    'is:issue is:open in:comments "polar-sh" created:>2026-09-01',
    'is:issue is:open in:comments "opire" created:>2026-08-01',
]

def main():
    token = open(r"D:/anonym/vault/github_token.txt", encoding="utf-8").read().strip()
    api = GitHub(token)
    seen, rows = set(), []
    for q in QUERIES:
        try:
            found = api.api("search/issues?" + urlencode({"q": q, "per_page": 12, "sort": "created", "order": "desc"}))
        except Exception as exc:
            print(f"SEARCH FAIL {q}: {type(exc).__name__} {exc}")
            continue
        for item in (found.get("items") or []):
            key = (item["repository_url"].split("/repos/")[-1], item["number"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(key)
    print(f"candidates: {len(rows)}")
    reasons, admitted = {}, []
    for repo, number in rows[:24]:
        try:
            ctx = api.issue_context(repo, number)
        except Exception as exc:
            reasons[f"HYDRATE_FAIL {type(exc).__name__}"] = reasons.get(f"HYDRATE_FAIL {type(exc).__name__}", 0) + 1
            continue
        proof, reason = admit(ctx)
        tag = "ADMITTED" if proof else reason
        if proof:
            admitted.append({"repo": repo, "issue": number, "amount": proof["funding"]["amount"],
                             "currency": proof["funding"]["currency"], "payer": proof["funding"]["payer"],
                             "title": ctx["issue"]["title"][:80]})
            print(f"  ADMITTED {repo}#{number} {proof['funding']['amount']} {proof['funding']['currency']} :: {ctx['issue']['title'][:70]}")
        else:
            reasons[tag] = reasons.get(tag, 0) + 1
            print(f"  {tag:34s} {repo}#{number} :: {ctx['issue']['title'][:60]}")
    print("\nreason histogram:")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"\nadmitted: {len(admitted)} of {len(rows[:24])}")
    json.dump({"admitted": admitted, "reasons": reasons}, open(r"D:/anonym/war-log/evidence/admission_live_probe.json", "w", encoding="utf-8"), indent=2)
    return 0

if __name__ == "__main__":
    sys.exit(main())
