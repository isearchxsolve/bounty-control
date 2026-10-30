#!/usr/bin/env python3
"""liquidity_score.py - Rank bounty candidates by whether the payer can actually pay.

The pipeline had no liquidity dimension at all. Every occurrence of "funding" in the
codebase meant *bounty* funding (escrow attestations), never company funding, so the
only proxy for "can this party pay instantly" was a dollar figure a stranger typed into
an issue body. That is a claim, not a balance sheet.

This module scores the payer, not the offer, using signals already available from the
GitHub API. It is deliberately standalone: no network calls, no imports from the rest of
the pipeline, so it can be unit-tested and reused by any hunter.

Reference: docs/SILO_FOUNDER_TARGETING_SPEC.md
  layer 1 = open-source bounties (low liquidity, volunteer maintainers)
  layer 2 = large enterprise (real money, heavy friction)
  layer 3 = funded startups / small companies
  layer 4 = agentic / silo-founder (near-zero friction, founder feels the damage)

Target is layer 3-4. The old ranking put layer 1 on top.

Usage:
    from liquidity_score import liquidity_score, bleed_score, rank_key
    liquidity_score(candidate)   -> (score, reasons)
    bleed_score(candidate)       -> (score, reasons)
    python liquidity_score.py --self-test
"""
import argparse
import re
import sys

# --- weights -------------------------------------------------------------------
# Positive: evidence the payer is a real company with money and a live product.
LIQUIDITY_WEIGHTS = {
    "org-repo": 3,             # an Organization owns the repo: a company, not a person
    "pushed-7d": 3,            # shipped this week: a live product
    "pushed-30d": 1,           # shipped this month
    "owner-filed": 3,          # the decision-maker filed it themselves
    "company-scale": 2,        # ARR/MRR/volume stated: evidence of size
    "raise-language": 2,       # funding/raise language in the org or repo
    "stars-mid": 2,            # 50-5000 stars: a real product, not a farm, not a giant
    "merges-recent": 2,        # merged PRs in the last 90 days: the repo accepts work
    "security-contact": 1,     # SECURITY.md / security contact present
    "solo-founder": 2,         # agent-native / tiny-headcount signals
}
LIQUIDITY_PENALTIES = {
    "repo-flood": -3,          # same repo opening many issues: a farm
    "repo-inactive": -3,       # no push in 60+ days: not a live wound
    "no-merges-ever": -5,      # many PRs, zero merges: demonstrated non-payment
    "unchecked-owner": -1,     # we did not look, so we do not know
}

# --- bleed: is this a live wound? ----------------------------------------------
# The guides' issue preference: immediate tangible business impact, hard enough that few
# will demonstrate it cleanly. This scores the damage, not the difficulty.
BLEED_WEIGHTS = {
    "data loss": 4, "leak": 4, "breach": 4,
    "production": 3, "outage": 3, "incident": 3, "down": 3,
    "unauthorized": 3, "bypass": 3, "customers affected": 3,
    "losing": 2, "revenue": 2, "race condition": 2, "deadlock": 2,
    "memory leak": 1,
}
# A wound is live when it is bleeding AND the repo shipped recently AND nobody is on it.
BLEED_LIVE_MIN = 3
BLEED_FRESH_DAYS = 14

RAISE_RE = re.compile(
    r"\b(?:seed|pre-?seed|series\s+[a-e]|raised|funding round|backed by|"
    r"venture|vc-backed|ycombinator|yc\s+[sw]\d+|accelerator)\b", re.I)
# Solo-founder signals. Bare "agent-native" and "ai agents" are ubiquitous marketing
# words that describe APIs and products, not people, so they only count when founder or
# team framing sits next to them. Measured live 2026-10-29: the loose pattern gave a
# bounty-board census post +2 for "a genuinely agent-native API" and ranked it #1.
SOLO_RE = re.compile(
    r"\b(?:solo\s+founder|solo\s+dev|solo\s+developer|one-?person|tiny team|tiny headcount|"
    r"no team|indie hacker|bootstrapped|just me|only me)\b", re.I)
AGENT_RE = re.compile(r"\b(?:agent-?native|ai agents?|swarm of agents)\b", re.I)
FOUNDER_CONTEXT_RE = re.compile(
    r"\b(?:founder|co-?founder|team|company|startup|we are|i built|i run|my product)\b", re.I)


def _flags(candidate):
    return list(candidate.get("flags") or [])


def _text(candidate):
    parts = [candidate.get("title") or "", candidate.get("body") or "",
             candidate.get("repo") or "", candidate.get("signals") or ""]
    return " ".join(str(p) for p in parts)


def liquidity_score(candidate):
    """Score the payer's ability to pay. Returns (score, [reason, ...]).

    Reads only fields a hunter already collects. Missing fields are not penalised: a
    signal we did not measure is not evidence against the candidate.
    """
    score, reasons = 0, []
    flags = _flags(candidate)

    if candidate.get("owner_type") == "Organization":
        score += LIQUIDITY_WEIGHTS["org-repo"]
        reasons.append("+3 org-repo (a company, not a person)")

    pushed = candidate.get("repo_pushed_days")
    if isinstance(pushed, int):
        if pushed <= 7:
            score += LIQUIDITY_WEIGHTS["pushed-7d"]
            reasons.append(f"+3 pushed-7d ({pushed}d ago)")
        elif pushed <= 30:
            score += LIQUIDITY_WEIGHTS["pushed-30d"]
            reasons.append(f"+1 pushed-30d ({pushed}d ago)")

    if candidate.get("author_assoc") == "OWNER":
        score += LIQUIDITY_WEIGHTS["owner-filed"]
        reasons.append("+3 owner-filed (decision-maker)")

    if candidate.get("company_scale_usd"):
        score += LIQUIDITY_WEIGHTS["company-scale"]
        reasons.append(f"+2 company-scale ({candidate['company_scale_usd']:,.0f})")

    text = _text(candidate)
    if RAISE_RE.search(text):
        score += LIQUIDITY_WEIGHTS["raise-language"]
        reasons.append("+2 raise-language")
    # Solo or agent-native counts only with founder context nearby: the words alone
    # describe products too often to trust.
    solo = bool(SOLO_RE.search(text))
    if not solo and AGENT_RE.search(text) and FOUNDER_CONTEXT_RE.search(text):
        solo = True
    if solo:
        score += LIQUIDITY_WEIGHTS["solo-founder"]
        reasons.append("+2 solo-founder / agent-native")

    stars = candidate.get("stars")
    if isinstance(stars, int) and 50 <= stars <= 5000:
        score += LIQUIDITY_WEIGHTS["stars-mid"]
        reasons.append(f"+2 stars-mid ({stars})")

    if candidate.get("merges_recent"):
        score += LIQUIDITY_WEIGHTS["merges-recent"]
        reasons.append("+2 merges-recent")
    if candidate.get("security_contact"):
        score += LIQUIDITY_WEIGHTS["security-contact"]
        reasons.append("+1 security-contact")

    for flag, weight in LIQUIDITY_PENALTIES.items():
        hit = (flag == "no-merges-ever" and candidate.get("merges_ever") == 0
               and (candidate.get("prs_total") or 0) >= 10)
        if hit or flag in flags:
            score += weight
            reasons.append(f"{weight:+d} {flag}")

    return score, reasons


def bleed_score(candidate):
    """Score the damage. Returns (score, [reason, ...])."""
    text = _text(candidate).lower()
    score, reasons = 0, []
    for phrase, weight in BLEED_WEIGHTS.items():
        if phrase in text:
            score += weight
            reasons.append(f"+{weight} {phrase}")
    return score, reasons


def is_live_wound(candidate):
    """The operational definition: bleeding, freshly shipped, and unassigned.

    Returns (bool, reason). This is the gate the spec calls for -- a wound nobody is
    working on in a repo that shipped this fortnight.
    """
    bleed, _ = bleed_score(candidate)
    if bleed < BLEED_LIVE_MIN:
        return False, f"not bleeding (bleed={bleed} < {BLEED_LIVE_MIN})"
    pushed = candidate.get("repo_pushed_days")
    if not isinstance(pushed, int) or pushed > BLEED_FRESH_DAYS:
        return False, f"repo not fresh (pushed={pushed}d)"
    if candidate.get("assignee"):
        return False, "already assigned"
    return True, "live wound"


def rank_key(candidate):
    """Sort key: liquidity dominates, bleed breaks ties.

    Liquidity is doubled on purpose. A solvent payer with a moderate problem is worth
    more than an insolvent one with a dramatic problem, because the insolvent one cannot
    pay no matter how loud the problem is.
    """
    liq, _ = liquidity_score(candidate)
    bleed, _ = bleed_score(candidate)
    return (liq * 2 + bleed, liq, bleed)


def explain(candidate):
    """Human-readable breakdown, for the operator."""
    liq, lr = liquidity_score(candidate)
    bleed, br = bleed_score(candidate)
    live, why = is_live_wound(candidate)
    lines = [f"liquidity {liq}   bleed {bleed}   rank {rank_key(candidate)[0]}   live={live} ({why})"]
    lines += [f"    liq  {r}" for r in lr]
    lines += [f"    bleed {r}" for r in br]
    return "\n".join(lines)


def self_test():
    """A solvent founder must outrank a farm. This is the regression guard."""
    founder = {
        "repo": "acme/checkout-api", "title": "Production checkout is down, losing revenue",
        "body": "We are a seed-stage company, $40M ARR, this is costing us every minute.",
        "owner_type": "Organization", "author_assoc": "OWNER", "repo_pushed_days": 1,
        "stars": 420, "merges_recent": True, "security_contact": True,
        "company_scale_usd": 40_000_000, "flags": [], "assignee": None,
    }
    farm = {
        "repo": "awesome-agent-bounties", "title": "bounty $50 fix the typo",
        "body": "bounty available", "owner_type": "User", "author_assoc": "NONE",
        "repo_pushed_days": 2, "stars": 3, "flags": ["repo-flood"], "assignee": None,
    }
    dead = {
        "repo": "corp/legacy", "title": "data loss in production, customers affected",
        "body": "leak of customer data", "owner_type": "Organization",
        "author_assoc": "OWNER", "repo_pushed_days": 400, "flags": ["repo-inactive"],
    }

    lf, _ = liquidity_score(founder)
    la, _ = liquidity_score(farm)
    assert lf > la, (lf, la)
    assert rank_key(founder)[0] > rank_key(farm)[0]

    # the founder's wound is live; the farm's is not
    assert is_live_wound(founder)[0] is True
    assert is_live_wound(farm)[0] is False

    # a dramatic problem in a dead repo is not a live wound
    assert bleed_score(dead)[0] >= BLEED_LIVE_MIN
    assert is_live_wound(dead)[0] is False, "inactive repo must not be a live wound"

    # an assigned issue is not a live wound
    taken = dict(founder, assignee="someone")
    assert is_live_wound(taken)[0] is False

    # missing fields are not penalised: an unmeasured signal is not evidence against
    bare = {"repo": "x/y", "title": "bug", "body": "", "flags": []}
    assert liquidity_score(bare)[0] == 0, liquidity_score(bare)

    # "agent-native" describing an API is not a solo founder (measured live 2026-10-29)
    census = {"repo": "pursekeeper/api", "flags": [],
              "title": "Superteam Earn census",
              "body": "a genuine agent-native API (self-serve key, no KYC)"}
    assert liquidity_score(census)[0] == 0, liquidity_score(census)
    # but agent-native WITH founder framing is
    founder_agentic = {"repo": "acme/x", "flags": [],
                       "title": "Production down",
                       "body": "we are an agent-native startup, solo founder here"}
    assert liquidity_score(founder_agentic)[0] >= 2, liquidity_score(founder_agentic)

    # the multiplier bug that read "mrr" as million must not come back
    assert "no-merges-ever" in LIQUIDITY_PENALTIES
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    ap.print_help()


if __name__ == "__main__":
    main()
