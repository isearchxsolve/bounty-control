"""Agent-driven admission for the dispatch side: the agent reads, code verifies.

Why this exists (measured 2026-10-30, 122 discovery runs):

    CURRENT_ISSUER_OFFER_MISSING   11,840
    HARD_ISSUE_EVIDENCE_MISSING     2,306
    qualified                         209
    delivered                           0

One hardcoded rule refused 11,840 issues because it demanded the reward as parseable text in the
body. Most real bounties state it in a label, a platform link or plain words, so the rule refused
work the search had already found. That is hardcoded judgement, not intelligence.

The engine's discipline is the model to copy: never claim an outcome you cannot verify. So here
the agent decides, and every claim it makes is checked against the issue text before it is used.
A quote the agent invents does not survive that check, and an agent that cannot answer means the
issue is refused, not admitted. Refusing costs nothing; a false positive costs a claim.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional, Tuple

PROMPT = """You are reading one GitHub issue to decide whether it is work an engineer could \
deliver as a pull request, and whether money is attached to it.

Answer with ONE JSON object and nothing else:
{"is_code_task": true|false,
 "code_reason": "<short reason>",
 "has_stated_reward": true|false,
 "reward_quote": "<a sentence copied CHARACTER FOR CHARACTER from the text, showing the reward>",
 "scope_quote": "<a sentence copied CHARACTER FOR CHARACTER from the text, showing what to build>",
 "confidence": "high"|"medium"|"low"}

Rules you must follow:
- reward_quote and scope_quote MUST be copied exactly from the text below. Do not paraphrase,
  translate, shorten or repair them. If you cannot copy an exact sentence, use "".
- has_stated_reward is true only when the text itself names money, a bounty, a prize or a paid
  reward for this work. A label or a link alone is not a quote.
- is_code_task is false for: announcements, contests and hackathons, daily digests produced by a
  bot, marketing or content requests, design-only asks, and questions with no request to change.
"""

# Characters that a model may substitute for quotes when copying text back.
_QUOTE_MAP = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
              "\u2014": "-", "\u00a0": " "}


# Markdown escapes punctuation that a reader renders plainly. Measured on a live issue whose
# body held ``Budget: \$900`` (confirmed byte-exact with ``od -c``): a faithful quote of
# "Budget: $900" could never match, so two real bounties were refused for no reason.
_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!$|<>~\"'])")


def _normalise(text: str) -> str:
    """Whitespace, quote style, markdown escapes and case, so a faithful copy is not rejected."""
    for bad, good in _QUOTE_MAP.items():
        text = text.replace(bad, good)
    text = _MD_ESCAPE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_is_present(quote: str, issue_text: str, minimum: int = 12) -> bool:
    """True only if the quote literally occurs in the issue text.

    This is the whole guard against a hallucinated bounty: a model can compose a convincing
    reward sentence, but it cannot make that sentence appear in text it was given.
    """
    cleaned = _normalise(quote)
    if len(cleaned) < minimum:
        return False
    return cleaned in _normalise(issue_text)


def _parse(reply: str) -> Optional[dict]:
    if not isinstance(reply, str):
        return None
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return None
    try:
        document = json.loads(match.group(0))
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


# Reward text that points elsewhere instead of stating an amount. Measured case: a live title read
# "Bounty Seguro (Ver enlace)" (see link) and the model quoted the title as proof of payment.
LINK_ONLY_RE = re.compile(
    r"(ver enlace|see link|link in (the )?(issue|comments?|description)|details? (in|at|on) "
    r"(the )?link|more info (in|at) the link|via link)", re.I)

REPAIR_PROMPT = (
    "Your previous answer quoted text that does not appear in the issue. Copy one sentence "
    "EXACTLY as it appears, character for character, or answer has_stated_reward=false if the "
    "issue does not state a reward in its own words. Return the same JSON object shape."
)


def _reward_is_unprovable(quote: str, issue: dict) -> Optional[str]:
    """Reasons a verified quote still fails to prove payment. Empty string means acceptable."""
    normalised_quote = _normalise(quote)
    title = _normalise(issue.get("title") or "")
    if title and normalised_quote in title and len(title) <= len(normalised_quote) + 8:
        return "REWARD_IS_TITLE_ONLY"
    if LINK_ONLY_RE.search(quote):
        return "REWARD_IS_LINK_ONLY"
    return None


def _issue_text(issue: dict) -> str:
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    labels = " ".join(label.get("name", "") if isinstance(label, dict) else str(label)
                      for label in (issue.get("labels") or []))
    return f"{title}\n\n{body}\n\n{labels}"


def assess(issue: dict, ask: Callable[[str, str], Optional[str]], min_confidence: str = "medium",
           repairs: int = 1) -> dict:
    """Decide whether to admit an issue, using the agent for judgement and code for facts.

    ``ask(prompt, user_text)`` returns the model's raw reply, or None when the agent is
    unavailable. None is treated as a refusal: an unjudged issue is never admitted, because
    admitting on agent failure is exactly the false positive this guards against.
    """
    text = _issue_text(issue)
    if not text.strip():
        return {"admit": False, "reason": "EMPTY_ISSUE", "detail": "the issue carries no text"}

    reply = ask(PROMPT, text)
    if reply is None:
        return {"admit": False, "reason": "AGENT_UNAVAILABLE",
                "detail": "the scout could not judge this issue; refusing rather than guessing"}

    verdict = _parse(reply)
    if verdict is None:
        return {"admit": False, "reason": "AGENT_UNPARSEABLE",
                "detail": (reply or "")[:200]}

    confidence = str(verdict.get("confidence") or "low").lower()
    order = {"low": 0, "medium": 1, "high": 2}
    if order.get(confidence, 0) < order.get(min_confidence, 1):
        return {"admit": False, "reason": "LOW_CONFIDENCE", "detail": confidence,
                "agent": verdict}

    if verdict.get("is_code_task") is not True:
        return {"admit": False, "reason": "AGENT_NOT_A_CODE_TASK",
                "detail": str(verdict.get("code_reason") or "")[:200], "agent": verdict}

    if verdict.get("has_stated_reward") is not True:
        return {"admit": False, "reason": "AGENT_NO_STATED_REWARD",
                "detail": str(verdict.get("code_reason") or "")[:200], "agent": verdict}

    reward_quote = str(verdict.get("reward_quote") or "")
    # One repair round: a model that paraphrased can usually copy correctly when told its quote
    # was not found. Measured: two real bounties ($900, $3,000) were lost to paraphrase alone.
    attempts = 0
    while not quote_is_present(reward_quote, text) and attempts < repairs:
        attempts += 1
        repaired_reply = ask(PROMPT + "\n\n" + REPAIR_PROMPT, text)
        repaired = _parse(repaired_reply) if repaired_reply is not None else None
        if repaired is None:
            break
        verdict = repaired
        if repaired.get("has_stated_reward") is not True or repaired.get("is_code_task") is not True:
            return {"admit": False, "reason": "AGENT_WITHDREW_REWARD",
                    "detail": str(repaired.get("code_reason") or "")[:200], "agent": repaired}
        reward_quote = str(repaired.get("reward_quote") or "")

    if not quote_is_present(reward_quote, text):
        # The agent said there is money but could not show where, twice. A claim spent on a
        # hallucinated reward is the false positive this whole guard exists to prevent.
        return {"admit": False, "reason": "REWARD_QUOTE_NOT_FOUND",
                "detail": reward_quote[:200], "repairs": attempts, "agent": verdict}

    unprovable = _reward_is_unprovable(reward_quote, issue)
    if unprovable:
        return {"admit": False, "reason": unprovable, "detail": reward_quote[:200],
                "repairs": attempts, "agent": verdict}

    scope_quote = str(verdict.get("scope_quote") or "")
    scope_verified = quote_is_present(scope_quote, text)
    return {"admit": True, "reason": "ADMITTED", "confidence": confidence,
            "reward_quote": reward_quote, "scope_quote": scope_quote,
            "scope_verified": scope_verified, "agent": verdict}


def nim_asker(router) -> Callable[[str, str], Optional[str]]:
    """Adapt the NVIDIA router into the ``ask`` callable. Failure returns None (refuse)."""
    def ask(prompt: str, user_text: str) -> Optional[str]:
        ok, completion, _, error = router.chat_completion({
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": user_text[:12000]}],
            "temperature": 0.1, "max_tokens": 400,
            "chat_template_kwargs": {"enable_thinking": False},
        })
        if not ok:
            return None
        try:
            return completion["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
    return ask
