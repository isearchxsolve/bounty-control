"""Score a bounty query set on facts, so "is this set any good" is not an opinion.

Written 2026-11-06 after a widened roster reached main with defects that no self-report
mentioned: duplicate queries, queries matching pull requests instead of issues, freshness
dates hardcoded to a calendar day that rots, and only 1 of 5 lanes ever rendered to the
agent. Every one of those is measurable without a model in the loop.

Usage:
    python scripts/query_quality_audit.py [path/to/bounty_queries.json] [--today YYYY-MM-DD]

Exit codes: 0 = no defect found, 2 = defects found (the report names them), 1 = the audit
itself failed.

What fails here is only a fact: a duplicate, a missing ``is:`` qualifier, a date anchor that
has aged past the limit, or a rendered lane whose evidence-bearing queries are buried behind
vocabulary-only ones. The share of vocabulary-only queries is *reported*, not failed: the
founder lane is deliberately a mixed lane (platform surfaces plus prose veins), and only the
rendered order decides which of them spends the agent's first search slot.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys

# The lanes that are actually rendered into the agent brief. A query outside these lanes
# never reaches a searching agent in agent-door mode, however good it is.
RENDERED_LANES = ("founder",)

# An entity that can attest escrow. Only an attesting actor can produce a row the
# escrow-only door will admit.
ATTESTING = re.compile(r"(commenter:|in:comments )", re.I)
# An explicit money anchor in the issue text, not in a filter.
AMOUNT = re.compile(r"\$\s?\d")
# A venue filter: a label, an org, or a named bounty platform. These say "bounties live
# here", which is a real discovery surface but not evidence of escrow.
SURFACE = re.compile(r"(label:|org:|algora|polar|opire|bountyhub|issuehunt)", re.I)
DATE_FILTER = re.compile(r"(created|updated):>=(\d{4}-\d{2}-\d{2})")
IS_KIND = re.compile(r"is:(issue|pr)\b", re.I)
MAX_ANCHOR_AGE_DAYS = 45


def tier(query):
    """How much evidence a query can surface, best first. Facts, not preference."""
    if ATTESTING.search(query):
        return 0
    if AMOUNT.search(query):
        return 1
    if SURFACE.search(query):
        return 2
    return 3


def audit(document, today=None):
    today = today or date.today()
    findings = []
    stats = {"lanes": {}, "total": 0}

    lanes = {k: v for k, v in document.items() if isinstance(v, list)}
    for lane, queries in lanes.items():
        stats["lanes"][lane] = len(queries)
        stats["total"] += len(queries)

        seen, dupes = set(), []
        for q in queries:
            if q in seen:
                dupes.append(q)
            seen.add(q)
        if dupes:
            findings.append({"kind": "DUPLICATE_WITHIN_LANE", "lane": lane,
                             "count": len(dupes), "examples": dupes[:3]})

        no_kind = [q for q in queries if not IS_KIND.search(q)]
        if no_kind:
            findings.append({"kind": "NOT_ISSUE_QUALIFIED", "lane": lane,
                             "count": len(no_kind), "examples": no_kind[:3]})

        for q in queries:
            for field, stamp in DATE_FILTER.findall(q):
                try:
                    when = datetime.strptime(stamp, "%Y-%m-%d").date()
                except ValueError:
                    findings.append({"kind": "UNPARSEABLE_DATE", "lane": lane, "query": q})
                    continue
                age = (today - when).days
                if age > MAX_ANCHOR_AGE_DAYS:
                    findings.append({"kind": "STALE_DATE_ANCHOR", "lane": lane, "query": q,
                                     "anchor": stamp, "age_days": age,
                                     "limit_days": MAX_ANCHOR_AGE_DAYS})

    # Cross-lane repeats are reported, not failed: only the rendered lane is shown to an
    # agent, so a repeat that lives outside it costs nothing at the door.
    repeats = {}
    for lane, queries in lanes.items():
        others = set()
        for other, other_queries in lanes.items():
            if other != lane:
                others |= set(other_queries)
        shared = [q for q in queries if q in others]
        if shared:
            repeats[lane] = len(shared)
    stats["cross_lane_repeats"] = repeats

    for lane in RENDERED_LANES:
        queries = lanes.get(lane) or []
        if not queries:
            findings.append({"kind": "RENDERED_LANE_MISSING", "lane": lane})
            continue
        tiers = [tier(q) for q in queries]
        counts = {t: tiers.count(t) for t in range(4)}
        stats.setdefault("rendered", {})[lane] = {
            "queries": len(queries),
            "attesting_actor": counts[0],
            "amount_anchored": counts[1],
            "surface": counts[2],
            "vocabulary_only": counts[3],
            "vocabulary_only_share": round(counts[3] / float(len(queries)), 3),
        }
        # The lever the brief actually controls is order: the agent chooses how many of the
        # rendered queries to run, so a vocabulary-only query ahead of an evidence-bearing
        # one spends a slot that could have produced an admissible row.
        if counts[3]:
            evidence = [i for i, t in enumerate(tiers) if t < 3]
            if not evidence:
                findings.append({
                    "kind": "RENDERED_LANE_HAS_NO_EVIDENCE_QUERY", "lane": lane,
                    "detail": "every rendered query names no attesting actor, no amount and "
                              "no surface, so no search can produce an admissible row",
                })
            else:
                worst_evidence = max(evidence)
                first_weak = tiers.index(3)
                if first_weak < worst_evidence:
                    findings.append({
                        "kind": "RENDERED_ORDER_BURIES_EVIDENCE", "lane": lane,
                        "first_vocabulary_only_index": first_weak + 1,
                        "last_evidence_bearing_index": worst_evidence + 1,
                        "detail": "a query naming no actor, no amount and no surface is "
                                  "rendered before an evidence-bearing one",
                    })

    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "stats": stats, "findings": findings,
            "verdict": "DEFECTS" if findings else "CLEAN"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?",
                        default=str(Path(__file__).with_name("bounty_queries.json")))
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD) for anchor ageing")
    args = parser.parse_args(argv)
    try:
        document = json.loads(Path(args.path).read_text(encoding="utf-8"))
        today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    except (OSError, ValueError) as exc:
        print(json.dumps({"phase": "AUDIT_FAILED", "error": str(exc)[:300]}))
        return 1
    report = audit(document, today)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["verdict"] == "CLEAN" else 2


if __name__ == "__main__":
    sys.exit(main())
