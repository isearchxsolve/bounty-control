#!/usr/bin/env python3
"""outreach_report.py - Build a founder-facing report that contains only what we can prove.

Replaces the keyword-selected templates in mass_attack_engine.py, which had two defects:

1. They appended a payment-rails block (bank account, IFSC, UPI handle, crypto wallet) to
   every public issue comment. Both target guides say the opposite in nearly the same
   words: "Zero fluff, zero speculation, zero padding" (Silo Guide 3.3) and "small teams
   have less patience for noise" (Startup Guide 4). A wallet address in a public thread
   reads as spam and repels exactly the operator we want.

2. They asserted work that had not been done: "We have reproduced this failure and
   verified the restorative hotfix on our private branch, achieving a 100% clean
   simulation." No such reproduction existed. Posting that is manufactured evidence, and
   it is the single fastest way to lose a technical founder who checks.

This module refuses to build a report without real evidence. The structure follows
Startup Guide 5 (report emphasis for small teams):

    1. One-sentence summary with clear business impact
    2. Who is affected and how (account type, data, money, operations)
    3. Minimal reproducible steps
    4. Proof (only what is necessary)
    5. Suggested direction for fix (short, practical)
    6. Extra technical detail only after the above

Usage:
    from outreach_report import build_report, MissingEvidence
    build_report(impact=..., affected=..., steps=[...], proof=[...], fix=...)
"""
import re

# Anything that looks like a payment coordinate must never reach a public comment.
# This is a guard, not a formatter: if a caller passes rails in, we refuse.
_RAILS_RE = re.compile(
    r"(?:\b(?:upi|neft|imps|ifsc|swift|iban)\b|"
    # account number in either word order: "account 55505593812" / "55505593812 account"
    r"\baccount\b[^\n]{0,12}\d{9,18}|\d{9,18}\s*(?:account|a/c)|"
    r"[A-Z]{4}0[A-Z0-9]{6}|"                      # IFSC shape
    r"@ok(?:hdfc|icici|axis|sbi)bank|"            # UPI handle shape
    r"\b(?:usdc|usdt)\b|"
    r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b)",          # base58 wallet shape
    re.I,
)

MAX_STEPS = 8
MAX_PROOF = 5


class MissingEvidence(ValueError):
    """Raised when a report would have to assert something we cannot show."""


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _require(value, name):
    if not _clean(value):
        raise MissingEvidence(
            f"{name} is required. A report we cannot fill in is not a report; "
            f"do not post a template in its place."
        )
    return _clean(value)


def _guard_rails(text):
    hit = _RAILS_RE.search(text)
    if hit:
        raise MissingEvidence(
            f"payment coordinates found in report body ({hit.group(0)!r}). "
            f"Payment terms belong in a private channel after the founder replies, "
            f"never in a public issue comment."
        )


def build_report(impact, affected, steps, proof, fix, detail=None, repo=None):
    """Build the six-part report. Raises MissingEvidence if anything is unproven.

    impact  : one sentence, business impact first. Required.
    affected: who is affected and how. Required.
    steps   : list of deterministic reproduction steps. At least one required.
    proof   : list of concrete evidence items (command output, status code, trace).
              At least one required.
    fix     : short suggested direction. Required.
    detail  : optional extra technical detail, appended last.
    """
    impact = _require(impact, "impact")
    affected = _require(affected, "affected")
    fix = _require(fix, "fix")

    steps = [_clean(s) for s in (steps or []) if _clean(s)]
    if not steps:
        raise MissingEvidence("at least one reproduction step is required")
    steps = steps[:MAX_STEPS]

    proof = [_clean(p) for p in (proof or []) if _clean(p)]
    if not proof:
        raise MissingEvidence(
            "at least one proof item is required. Without proof the report is an "
            "assertion, and an assertion is what the guides say gets filtered hardest."
        )
    proof = proof[:MAX_PROOF]

    lines = []
    lines.append(f"**{impact}**")
    lines.append("")
    lines.append(f"**Who is affected:** {affected}")
    lines.append("")
    lines.append("**Steps to reproduce**")
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("**Proof**")
    for item in proof:
        lines.append(f"- {item}")
    lines.append("")
    lines.append(f"**Suggested direction:** {fix}")

    if detail and _clean(detail):
        lines.append("")
        lines.append("**Technical detail**")
        lines.append(_clean(detail))

    body = "\n".join(lines)
    _guard_rails(body)
    return body


def self_test():
    ok = build_report(
        impact="Checkout fails for every returning customer, so paid traffic converts at zero.",
        affected="All customers with a saved card; roughly every repeat purchase.",
        steps=["Open /checkout with a saved card", "Submit payment", "Observe 500"],
        proof=["Response: 500 from POST /api/charge", "Stack: TypeError at charge.ts:88"],
        fix="Guard the null card token before the charge call.",
    )
    assert ok.startswith("**Checkout fails"), ok[:40]
    assert "Suggested direction" in ok

    # every one of these must be refused
    for kwargs, label in [
        (dict(impact="x", affected="y", steps=["a"], proof=[], fix="z"), "no proof"),
        (dict(impact="x", affected="y", steps=[], proof=["p"], fix="z"), "no steps"),
        (dict(impact="", affected="y", steps=["a"], proof=["p"], fix="z"), "no impact"),
        (dict(impact="x", affected="y", steps=["a"], proof=["p"], fix=""), "no fix"),
    ]:
        try:
            build_report(**kwargs)
        except MissingEvidence:
            pass
        else:
            raise AssertionError(f"should have refused: {label}")

    # payment rails must never survive into a public body
    for rails in [
        "IFSC KKBK00065993",
        "pay to isearch.xsolve-3@okhdfcbank",
        "wallet 2qi849TBq72XMpsp8PjR4YfegDEzc7BRFZaarwQ2tKgL",
        "account 55505593812",
    ]:
        try:
            build_report(impact="x", affected="y", steps=["a"], proof=[rails], fix="z")
        except MissingEvidence:
            pass
        else:
            raise AssertionError(f"rails leaked: {rails}")

    print("self-test OK")


if __name__ == "__main__":
    self_test()
