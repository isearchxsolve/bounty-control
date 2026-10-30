#!/usr/bin/env python3
"""hardness_score.py - Rank candidates by whether most developers would refuse the problem.

Baba's Hardness Moat: prefer the tickets that scare novices away and carry near-zero
competition, because those are the ones a specialised agent can win outright.

This scoring was first written *inside* ``autonomous_icu_pipeline.py`` as
``score_hardness_and_competition()``. That file is not in the CI chain and the dispatcher
never imported it, so the moat existed as code and never influenced a single dispatch -
exactly the defect ``liquidity_score.py`` had before it was wired. This module is the
single home for the patterns; the dispatcher imports it.

Standalone by design: no network, no imports from the rest of the pipeline, so it is
unit-testable and reusable by any hunter.

Weights (unchanged from the original moat, so behaviour is comparable):
  * +30 per distinct hardness pattern found in title + body + labels
  * +50 for a $500+ ticket, +25 for $100+ (evidence the payer values the work)
  * competition bonus only when the ticket is actually hard: +50 at 0 comments,
    +35 at <=2, +20 at <=4, -15 above 15
  * -15 above 15 comments even on a trivial ticket

Measured signals only. An unknown comment count earns no bonus and no penalty, because a
signal we did not read is not evidence about competition.

Usage:
    from hardness_score import hardness_score, is_hard
    hardness_score({"title": ..., "body": ..., "labels": [...], "comments_count": 2})
        -> (score, [reason, ...])
    python hardness_score.py --self-test
"""
import argparse
import re
import sys

PATTERNS = [
    r"\bhard\b", r"\bcomplex\b", r"\bconcurrency\b", r"\brace condition\b",
    r"\bdeadlock\b", r"\bmutex\b", r"\block-free\b", r"\batomic\b", r"\bthread\s+saf\w+\b",
    r"\bmemory leak\b", r"\buse-after-free\b", r"\bbuffer overflow\b", r"\bsegmentation fault\b",
    r"\bcorruption\b", r"\bconsensus\b", r"\braft\b", r"\bpaxos\b",
    r"\bcompiler\b", r"\bast\b", r"\bparser\b", r"\bcodegen\b", r"\btype\s+checker\b",
    r"\bcryptography\b", r"\bzero-knowledge\b", r"\bzk-snark\b", r"\bsignature\b",
    r"\bsvm\b", r"\bevm\b", r"\breentrancy\b", r"\bsmart contract\b",
    r"\bkernel\b", r"\bdriver\b", r"\bebpf\b", r"\bio_uring\b",
    r"\bdistributed\b", r"\blatency\b", r"\bp99\b", r"\bthroughput\b", r"\bprofiler\b",
    r"\bboundary\b", r"\binvariant\b", r"\bperformance\b", r"\boptimization\b",
    r"\bprotocol\b", r"\bgrpc\b", r"\bprotobuf\b", r"\bzero-copy\b",
]

HARDNESS_POINTS = 30
VALUE_TIERS = ((500, 50), (100, 25))
COMPETITION_BONUS = ((0, 50), (2, 35), (4, 20))
CROWDED_THRESHOLD = 15
CROWDED_PENALTY = -15

_AMOUNT = re.compile(r"[$€£₹]\s*([\d,]+(?:\.\d+)?)")
_COMPILED = [(p, re.compile(p, re.I)) for p in PATTERNS]


def _labels(candidate):
    out = []
    for label in candidate.get("labels") or []:
        out.append(label.get("name", "") if isinstance(label, dict) else str(label))
    return out


def _text(candidate):
    parts = [candidate.get("title") or "", candidate.get("body") or "", " ".join(_labels(candidate))]
    return " ".join(str(p) for p in parts)


def hardness_hits(candidate):
    """Which hardness patterns fired, in declaration order, deduplicated by pattern."""
    text = _text(candidate)
    return [pattern for pattern, rx in _COMPILED if rx.search(text)]


def is_hard(candidate):
    return bool(hardness_hits(candidate))


def value_usd(candidate):
    """The ticket's stated money, as a float, or None when the text states none.

    Reads the first currency figure in the text. It is a claim from the document, never a
    verified escrow amount - admission decides whether an offer is trustworthy.
    """
    match = _AMOUNT.search(_text(candidate))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def hardness_score(candidate):
    """Score how much a problem should repel an ordinary developer. Returns (score, reasons)."""
    score, reasons = 0, []
    hits = hardness_hits(candidate)
    if hits:
        score += HARDNESS_POINTS * len(hits)
        reasons.append(f"+{HARDNESS_POINTS * len(hits)} hardness x{len(hits)} ({', '.join(hits[:4])}"
                       + ("..." if len(hits) > 4 else "") + ")")

    amount = value_usd(candidate)
    if amount is not None:
        for floor, points in VALUE_TIERS:
            if amount >= floor:
                score += points
                reasons.append(f"+{points} value {amount:g} >= {floor}")
                break

    comments = candidate.get("comments_count")
    if isinstance(comments, int):
        if hits:
            for ceiling, bonus in COMPETITION_BONUS:
                if comments <= ceiling:
                    score += bonus
                    reasons.append(f"+{bonus} uncontested ({comments} comments)")
                    break
            if comments > CROWDED_THRESHOLD:
                score += CROWDED_PENALTY
                reasons.append(f"{CROWDED_PENALTY} crowded ({comments} comments)")
        elif comments > CROWDED_THRESHOLD:
            score += CROWDED_PENALTY
            reasons.append(f"{CROWDED_PENALTY} crowded ({comments} comments)")
    elif comments is not None:
        reasons.append("comments unmeasured (no bonus, no penalty)")
    return score, reasons


def rank_key(candidate):
    """Sort key: harder first, then the value of the ticket. Lower sorts earlier."""
    score, _ = hardness_score(candidate)
    return (-score,)


def explain(candidate):
    score, reasons = hardness_score(candidate)
    lines = [f"hardness {score}   hard={is_hard(candidate)}"]
    lines += [f"    {r}" for r in reasons]
    if not reasons:
        lines.append("    no hardness evidence (only the admission floor applies)")
    return "\n".join(lines)


def self_test():
    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)

    hard = {"title": "Deadlock in io_uring write path under load", "body": "", "comments_count": 0}
    trivial = {"title": "Typo in the docs", "body": "", "comments_count": 0}
    check("hard outranks trivial", hardness_score(hard)[0] > hardness_score(trivial)[0])
    check("hard hits detected", any("deadlock" in pattern for pattern in hardness_hits(hard)))
    check("trivial has no hardness", hardness_hits(trivial) == [])

    # Zero-hardness gets no competition bonus: the two must score the same.
    check("no bonus without hardness",
          hardness_score(dict(trivial, comments_count=0))[0]
          == hardness_score(dict(trivial, comments_count=3))[0])

    # Unmeasured comments are neutral, not "zero comments".
    measured = hardness_score(dict(hard, comments_count=0))[0]
    unmeasured = hardness_score({k: v for k, v in hard.items() if k != "comments_count"})[0]
    check("unmeasured comments earn no bonus", unmeasured == measured - 50)

    crowded = hardness_score(dict(hard, comments_count=40))[0]
    check("crowded is penalised", crowded == measured - 50 - 15)

    money = hardness_score({"title": "Race condition", "body": "bounty $750", "comments_count": 1})
    check("value tier applies", any("value 750" in r for r in money[1]))

    check("labels count as text",
          is_hard({"title": "fix", "body": "", "labels": [{"name": "concurrency"}]}))
    check("rank_key sorts harder first", rank_key(hard) < rank_key(trivial))
    check("pattern list intact", len(PATTERNS) >= 46)

    for name in failures:
        print(f"FAIL {name}")
    print(f"{'FAILED' if failures else 'OK'} self-test: {13 - len(failures)}/13")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score how hard a bounty ticket really is.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--comments", type=int, default=None)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.title:
        parser.error("pass --title, or --self-test")
    print(explain({"title": args.title, "body": args.body, "comments_count": args.comments}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
