"""How badly is the payer bleeding right now?

Baba's law, 2026-10-30: *"the claimant got no reply cause target issuer had no urgency..
no ugs in live production burning millions each second. thats why we target silo wounded
founders and startup"*.

The bounty boards proved it by the evidence: `microg/GmsCore` carries $17,889 across four
funded tickets, one of them open since 2018, and the claimant on Google Cast has waited
since April for a maintainer word. Nobody answered because nobody was on fire. A volunteer
project with an open ticket feels no cost per hour; a founder whose checkout is broken, or
whose client is threatening a contract, does.

So urgency is not a tiebreak. It predicts REPLY LATENCY, which is the funnel's binding
constraint - and it is measured from the payer's own words, not assumed.

Two honesty rules built in:

1. This scores a CLAIM, not proof. The issue text says "production is down"; we cannot see
   their production. It is therefore a targeting signal, never a funding signal - funding
   stays with :mod:`bounty_admission`, which demands an issuer-authored offer.
2. Age subtracts. A wound described a year ago is not bleeding today, so an old ticket must
   not outrank a fresh one on the strength of dramatic language it used long ago.

Run ``python urgency_score.py --self-test`` (13 checks) or
``python urgency_score.py --title ... --body ...``.
"""

from __future__ import annotations

import re
import sys

#: (weight, label, patterns). Patterns containing a space match as a substring; single
#: tokens match as whole tokens so that "p0" does not fire inside "p001".
SIGNALS = (
    (40, "production_is_down", (
        "production is down", "prod is down", "prod down", "site is down",
        "service is down", "system is down", "we are down", "currently down",
        "outage", "sev1", "sev-1", "sev 1", "total outage", "500s in production",
        "cannot serve requests", "nothing works",
    )),
    (35, "revenue_bleeding", (
        "losing revenue", "losing money", "losing customers", "costing us",
        "revenue loss", "we lose money", "burning money", "checkout is broken",
        "payments are failing", "cannot charge", "carts are failing",
        "blocking sales", "conversion drop", "churn", "refunding customers",
        "losing orders", "hemorrhaging",
    )),
    (30, "contract_or_sla_pressure", (
        "sla", "breach", "contract deadline", "client deadline", "customer deadline",
        "must ship by", "due tomorrow", "due today", "audit on", "audit next week",
        "regulatory deadline", "go live", "launch next week", "demo on",
    )),
    (30, "security_incident", (
        "data breach", "breached", "exploited in the wild", "actively exploited",
        "accounts compromised", "credentials leaked", "security incident",
        "rce", "privilege escalation", "cve-",
    )),
    (20, "escalation_language", (
        "urgent", "urgently", "asap", "blocker", "blocking release",
        "blocking our release", "critical", "right now", "today", "immediately",
        "p0", "p1", "must fix",
    )),
    (15, "growth_pressure", (
        "cannot onboard", "can not onboard", "signups failing", "we are growing fast",
        "scaling problems", "traffic spike", "launch week", "investors",
        "due diligence", "board meeting",
    )),
)

#: A payer saying it is not urgent is the single most useful negative signal there is.
CALM = (
    "no rush", "not urgent", "whenever you can", "whenever", "nice to have",
    "nice-to-have", "someday", "some day", "eventually", "low priority",
    "would be nice", "not a blocker", "no deadline", "at your convenience",
    "backlog", "take your time", "low urgency",
)

CALM_PENALTY = -30


def _hits(text, patterns):
    lowered = text.lower()
    found = []
    for pattern in patterns:
        if " " in pattern:
            if pattern in lowered:
                found.append(pattern)
        elif re.search(r"(?<![a-z0-9])" + re.escape(pattern) + r"(?![a-z0-9])", lowered):
            found.append(pattern)
    return found


def _text(candidate):
    labels = candidate.get("labels") or ()
    if isinstance(labels, str):
        labels = (labels,)
    parts = [str(candidate.get("title") or ""), str(candidate.get("body") or "")]
    parts.extend(str(label) for label in labels)
    return " ".join(parts)


def urgency_score(candidate):
    """Return ``(score, reasons)`` for how urgently the payer is bleeding.

    ``candidate`` accepts ``title``, ``body``, ``labels`` and optional ``age_days``. A
    missing ``age_days`` means unknown age, which is scored as no penalty: the dispatcher
    always supplies it, and an unknown must not be treated as fresh or as stale.
    """
    text = _text(candidate)
    score = 0
    reasons = []
    for weight, label, patterns in SIGNALS:
        found = _hits(text, patterns)
        if found:
            score += weight
            reasons.append("+" + str(weight) + " " + label + ": " + ", ".join(found[:3]))
    calm = _hits(text, CALM)
    if calm:
        score += CALM_PENALTY
        reasons.append(str(CALM_PENALTY) + " calm_payer: " + ", ".join(calm[:3]))
    age = candidate.get("age_days")
    if isinstance(age, int):
        if age > 365:
            score -= 25
            reasons.append("-25 stale_wound: older than a year")
        elif age > 180:
            score -= 10
            reasons.append("-10 stale_wound: older than six months")
    return score, reasons


def is_urgent(candidate, threshold=20):
    return urgency_score(candidate)[0] >= threshold


def explain(candidate):
    score, reasons = urgency_score(candidate)
    head = str(candidate.get("title") or "")[:60]
    return head + " -> " + str(score) + (" | " + "; ".join(reasons) if reasons else " | no signal")


def self_test():
    checks = []

    def check(name, condition):
        checks.append((name, bool(condition)))

    down = {"title": "Production is down, customers cannot check out",
            "body": "We are losing revenue every minute. Urgent."}
    check("production outage scores high", urgency_score(down)[0] >= 90)
    check("outage names its reasons", any("production_is_down" in r for r in urgency_score(down)[1]))

    calm = {"title": "Add dark mode", "body": "No rush, whenever you can, nice to have."}
    check("calm payer scores at or below zero", urgency_score(calm)[0] <= 0)
    check("calm payer is named", any("calm_payer" in r for r in urgency_score(calm)[1]))

    silent = {"title": "Support Google Cast", "body": "Is this planned?"}
    check("a volunteer wish is not urgent", urgency_score(silent)[0] < 20)

    stale = dict(down, age_days=800)
    check("a year-old wound is discounted", urgency_score(stale)[0] < urgency_score(down)[0])
    check("discount is bounded", urgency_score(stale)[0] > 0)

    fresh = dict(down, age_days=2)
    check("fresh wound keeps its score", urgency_score(fresh)[0] == urgency_score(down)[0])

    token = {"title": "Fix p0 regression", "body": ""}
    check("p0 is recognised", urgency_score(token)[0] >= 20)
    check("p0 does not fire inside p001", urgency_score({"title": "p001 build tag", "body": ""})[0] < 20)

    breach = {"title": "Security incident: accounts compromised", "body": "Data breach under investigation."}
    check("security incident scores", urgency_score(breach)[0] >= 60)

    label_only = {"title": "Ticket", "body": "", "labels": ["urgent", "production"]}
    check("labels count", urgency_score(label_only)[0] >= 20)

    check("explain is readable", "->" in explain(down))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("OK self-test: " + str(len(checks)) + "/" + str(len(checks)))
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    candidate = {}
    for flag, key in (("--title", "title"), ("--body", "body")):
        if flag in argv:
            candidate[key] = argv[argv.index(flag) + 1]
    if "--age-days" in argv:
        candidate["age_days"] = int(argv[argv.index("--age-days") + 1])
    if not candidate:
        print(__doc__)
        return 0
    print(explain(candidate))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
