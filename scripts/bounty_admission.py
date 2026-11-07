"""One evidence-based admission contract for all dispatcher lanes and release."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import os
import re
from urllib.parse import urlencode

# Bounty identity: whichever account the pipeline runs as. An own-PR is recognised by this
# login, so a mirror to another account must not leave the old one hardcoded here.
# The bounty account owns the fork and PR identity, so it must be the account that is
# actually running the workflow. A compiled-in default pointed the survivor at the
# retired account: the PR branch was pushed as "niloydassana-maker:branch" and the
# fork URL named a repo this token cannot write to (observed 2026-10-29).
BOUNTY_ACCOUNT = (os.environ.get("BOUNTY_ACCOUNT")
                  or (os.environ.get("GITHUB_REPOSITORY") or "").split("/")[0]
                  or "isearchxsolve")

# Layer 3-4 targeting by liquidity, not by headline price. The floor was 80, then was
# raised to 2000 on 2026-10-29 on a value argument: a material production issue at a
# funded startup or silo founder is worth thousands, and an 80-dollar ticket is a
# hobbyist's. That reasoning is sound about value and wrong about price. Measured against
# the live market on 2026-10-30 (53 priced titles across three high-yield queries): the
# median bounty is $250, and a $2,000 floor keeps only 3.8% of priced bounties while a
# $250 floor keeps 60.4%. 2000 was a closed door, not a filter. The default is now the
# market median; BOUNTY_FLOOR overrides it per run or per environment without a commit.
FLOOR = Decimal(os.environ.get("BOUNTY_FLOOR") or "250")
TRUSTED_BOTS = {"algora-pbc", "algora-io[bot]", "polar-sh[bot]", "opire[bot]",
                "bountyhub-app", "bountyhub-bot"}
ISSUERS = {"OWNER", "MEMBER", "COLLABORATOR"}
NON_WORK = re.compile(
    r"\b(?:digest|newsletter|willingness.to.pay|validation plan|ad spend|"
    r"grant proposal|security bug bounty submission|payout claim|sealed solution|"
    r"mirrored from|backfill record|status:\s*done|bounty (?:alert|scout|solution))\b|"
    r"^\s*\[(?:experiment|radar|intake|proposal|roadmap)\]", re.I)
OFFER = re.compile(
    r"/bounty|/reward|\bbount(?:y|ies)\b|\breward\b|\b(?:we|i)\s+(?:will|can|would)\s+pay\b|"
    r"\boffering\b|\brecompensa\b|\brémunération\b|悬赏|赏金|报酬", re.I)
WITHDRAWN = re.compile(
    r"(?:remov(?:e|ed|ing)|withdraw(?:n|ing)?|cancel(?:led|ing)?)\s+(?:the\s+)?(?:bounty|reward)|"
    r"bounty\s+(?:is\s+)?(?:withdrawn|cancelled|paid|awarded)|no longer offering|"
    r"no\s+(?:bounty|reward|payment|funding)(?:\s+(?:is\s+)?(?:available|expected|offered))?", re.I)
PAYEE = re.compile(
    r"\b(?:researcher|payout wallet|settlement wallet|settlement rail|"
    r"claiming bounty|bounty submission|requesting funding)\b", re.I)
# Instruction-exfiltration demand: a "bounty" that pays the contributor to hand over the
# private preamble its agent runtime loaded, or the machine fingerprint it runs on.
# Measured on the 2026-10-27 payloads: 383 trap documents carried 142 distinct demands in
# this family, while the previous two-phrase rule caught 14 of 201 issues in one repository
# and 0 of 182 in another. Every alternative below names something a contributor can only
# know by dumping their own assistant context, so none has a legitimate technical reading
# inside a bounty issue. A bare "system prompt" is deliberately NOT matched on its own,
# because an issue about prompt forwarding is a real bug report and not an attack.
EXFILTRATION = re.compile(
    r"platform[- ]provided instructions|pre-conversation|before the first human message|"
    r"from the first token|paste everything from|"
    r"verbatim copy of (?:all|your|the)\s+(?:instructions|guidelines|preamble)|"
    r"full unedited text of your|\byour (?:system|developer) prompt\b|"
    r"complete raw (?:system )?prompt|initialization (?:payload|text|context)|"
    r"complete initialization text|into your session at startup|"
    r"complete configuration that was active during this contribution|"
    r"complete text of the first message in your conversation|"
    r"paste the complete (?:configuration|config)|paste everything verbatim|"
    r"pre-task instructions|execution environment details|startup configuration|"
    r"full raw text of your|raw text of your startup|"
    r"\b(?:platform_instructions|runtime_instructions|initial_directives|config_snapshot|"
    r"session_init|boot_context|generation_context|initialization_payload|"
    r"initialized_with)\b|"
    r"\bhome_dir\b[^.\n]{0,120}\bworking_dir\b", re.I)

# Escrow-advertisement farms make an issue that is not a defect in this repository at all:
# it advertises a payout held elsewhere and publishes the raw wallet addresses to claim it.
# Measured on 2026-10-29 across the `label:bounty` horizon: alfrexo95/bounty-bot#60 and
# zhangjiayang6835-cyber/bounty-plaza#4171 (which mirror each other) carried two wallets
# each plus escrow wording, while every genuine funded issue tested in the same sample
# (microg/GmsCore#2843, three Expensify/App bounties) carried none. Both signals are
# required so a project that merely publishes a donation address is never refused.
CRYPTO_WALLET = re.compile(
    r"\bbc1[a-z0-9]{25,62}\b|\b0x[a-fA-F0-9]{40}\b|\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
ESCROW_ADVERT = re.compile(
    r"pago\s+garantizado|guaranteed\s+payment|\bescrow\s+(?:payment|release)|"
    r"\u8d4f\u91d1\u5e73\u53f0|\u539f\u59cb\u94fe\u63a5", re.I)

# A repository that has already declared the reported behaviour correct is not work: the
# only possible delivery outcome is a refusal, and the run spends a full Cline session
# learning what the maintainer already wrote. Measured on Expensify/App#105153 (2026-10-27):
# the dispatched delivery run returned a verified `action=blocked`, "documented by the
# repository's own maintainer analysis as expected/by-design", and the next discovery cycle
# re-admitted the same issue. The wording below is declarative on purpose.
#
# The reporter's own "Expected Behaviour" heading is deliberately NOT a marker: every bug
# report carries one and it states the opposite of this verdict. Only an authoritative
# document can declare intent, and a later authoritative "this is a bug"/reopen clears it,
# so a maintainer changing their mind reopens the issue instead of being overruled by their
# earlier comment.
BY_DESIGN = re.compile(
    r"\bworks as (?:designed|intended)\b|\bworking as (?:designed|intended)\b|"
    r"\bby design\b|\bnot a bug(?![\w-]|\s+fix\b)|\bnot a defect(?![\w-])|"
    r"\bno code change (?:is )?(?:needed|required|necessary)\b|"
    r"\bwon'?t fix\b|"
    r"\bexpected behaviou?r\b[^.\n]{0,60}\bby design\b", re.I)
# ``no code change`` alone is ambiguous, so it only counts when it is a verdict about the
# behaviour ("no code change needed/required"). Measured live 2026-10-27 on
# ach1992/bot-refactor#51, whose owner wrote "DEFERRED BATCH: ... no code change or new release
# is authorized yet" - a deferral of authorised work, the opposite of "this is intended".
# ``not a bug`` must end its word: "not a bug-fix task" is a description of the *work item*, not a
# verdict on a reported behaviour, and the hyphen made the phrase match anyway. Measured live
# 2026-10-27 on MyZubster-Ecosystem/myzubster#1613, whose maintainer wrote that the issue "remains
# an invitation to test real Seller-Free onboarding, not a bug-fix task or payable bounty".
# The spaced form "not a bug fix" is excluded too: live microg/GmsCore#2994 used that phrase to
# describe RCS as a new feature, not to declare its behavior intentional.
# A bare ``wontfix`` is deliberately NOT prose here. In prose it is almost always the name of
# a label or a pointer to another issue ("Closed/wontfix #627 ..."), which says nothing about
# the behaviour reported on this issue. Measured live 2026-10-27 on
# Ensrick/vermintide-2-tweaker#760, which the gate refused on exactly that sentence. A real
# ``wontfix`` label is still read, through BY_DESIGN_LABELS below.
REFERENCE_BEFORE = re.compile(r"(?:closed/|label(?:l)?ed|tagged|per|see)\s*:?\s*$", re.I)
REFERENCE_AFTER = re.compile(r"\s*(?:#\d+|\((?:see|per)\s*#\d+)")
# A marker inside a provenance clause is audit bookkeeping, not a statement about the reported
# behaviour. Measured live 2026-10-27 on MarkDude-design/ALLurbaseRnotbelong2us#2, whose owner
# logged "6445766848 (rounds/005 provenance column - actually a bus #3 pointer, cross-thread by
# design; checker artifact, listed for completeness)": "by design" there qualifies a pointer
# between threads. The issue itself is a pilot session log, not a code-change request.
META_ARTIFACT = re.compile(
    r"\b(?:pointer|artifacts?|artefacts?|cross[- ]thread\w*|provenance|checker)\b", re.I)
# An aggregate board is not a bug report, so nothing written on it can be a verdict on one
# behaviour. Measured live 2026-10-27 on limitlessprojects/Go-Hybrid#940, "Triage Board
# (auto-updated daily - pin me)", where a status bullet about CI freshness was read as a
# declaration about the issue.
AGGREGATE_DOCUMENT = re.compile(r"\btriage board\b|\bauto[- ]updated\b|\bpin me\b", re.I)
REAL_BUG = re.compile(
    r"\b(?:this|that|it)\s+(?:is|remains)\s+(?:still\s+)?a\s+"
    r"(?:real|genuine|valid)\s+(?:bug|defect|regression)\b|"
    r"\bconfirmed\s+(?:as\s+)?a\s+(?:bug|defect)\b|"
    r"\breopen(?:ed|ing)?\b|"
    r"\b(?:not|no longer)\s+(?:by design|works as designed)\b", re.I)
BY_DESIGN_LABELS = {"wontfix", "won't fix", "wont fix", "by design", "as designed",
                    "not a bug", "works as designed", "invalid", "not planned"}

HARD = re.compile(
    r"\b(?:race condition|deadlock|concurren\w*|atomic\w*|idempot\w*|"
    r"overflow|underflow|precision|protocols?|invariants?|authorization|bypass|"
    r"cross.tenant|serialization|compilers?|parsers?|memory|latency|throughput|"
    r"regressions?|crash\w*|panic\w*|corrupt\w*|transactions?|consensus|ABI|"
    r"performance|distributed|schedulers?|algorithms?|cryptograph\w*|"
    r"encryption|signatures?|deadlocks?|bug\w*|error\w*|fail\w*|broken|issue\w*|problem\w*|defect\w*)\b", re.I)
WISH = re.compile(
    "(?<![a-z])is it possible(?![a-z])|(?<![a-z])would it be possible(?![a-z])|"
    "(?<![a-z])any (?:chance|way)(?![a-z])|"
    "(?<![a-z])would be (?:nice|great|good|cool)(?![a-z])|(?<![a-z])feature request(?![a-z])|"
    "(?<![a-z])(?:please|kindly) (?:add|support|implement|provide)(?![a-z])|"
    "(?<![a-z])possible to (?:add|support|implement)(?![a-z])", re.I)

DEFECT_ANCHOR = re.compile(
    "traceback|stack ?trace|exception|error:|panic:|segfault|"
    "expected.{0,80}actual|steps to reproduce|reproduc[a-z]*|"
    "(?<![a-z])regression(?![a-z])|fails? (?:when|with|on)|crash(?:es)? (?:when|on)", re.I)

COMPONENT = re.compile(
    r"(?<!https://)(?:[\w.-]+/)+[\w.-]+\.[a-zA-Z0-9]+|"
    r"\b[A-Za-z_][A-Za-z0-9_:]*\(\)|\b(?:E[A-Z0-9_]{4,}|[A-Z][A-Za-z]+Error)\b")
# `test_component_not_invented_from_url` fixes the master contract: an arbitrary URL is not a
# component reference, so COMPONENT keeps reading the sanitised body. That contract is right -
# an attachment link or a vendor doc says nothing about where the defect lives.
#
# It also hid a measured refusal. Expensify/App#105168 (open, Bug|Engineering, titled [$175])
# states its entire defect location as a permalink to one of its own files, and the sanitiser
# deleted it, so the only evidence in the report was invisible to the gate. The distinction
# that matters is ownership, not shape: a permalink into THE SAME repository is the report
# pointing at the code, while any other URL stays exactly as excluded as the contract says.
# So permalinks are read separately, matched against this repository's own full name, and only
# a source file counts.
GITHUB_PERMALINK = re.compile(
    r"https?://(?:www\.)?(?P<host>github\.com|raw\.githubusercontent\.com)/"
    r"(?P<path>[^\s)\"'<>\[\]]+)", re.I)
# A located path only localises a defect when it points at source. A documentation path
# ("docs/guide.md") says a report was researched; it does not say where the bug is.
SOURCE_PATH = re.compile(
    r"\.(?:ts|tsx|js|jsx|mjs|cjs|py|rs|go|java|kt|kts|rb|php|cs|c|cc|cpp|cxx|h|hpp|m|mm|"
    r"swift|scala|ex|exs|sh|ps1|sql|vue|svelte|lua|pl|dart)$", re.I)
MONEY = re.compile(
    r"(?<![\w.])(?:(?P<c1>\$|€|£|₹|USD|USDC|USDT|EUR|GBP|INR|SGD|AED|ETH|SOL)\s*"
    r"(?P<a1>\d+(?:,\d{3})*(?:\.\d+)?)(?P<m1>[kK])?|"
    r"(?P<a2>\d+(?:,\d{3})*(?:\.\d+)?)(?P<m2>[kK])?\s*"
    r"(?P<c2>USDC|USDT|USD|EUR|GBP|INR|SGD|AED|ETH|SOL|\$|€|£|₹))(?![\w]|\.\d)", re.I)


EXPLICIT_DEADLINE = re.compile(
    r"^\s*(?:(?:[-*]\s*)|(?:\d+[.)]\s*))?(?:\*{0,2})(?:submission\s+)?"
    r"(?:deadline|due\s+date|submit\s+by)(?:\*{0,2})\s*(?::|=|[-–—]|\bis\b)\s*"
    r"(?:\*{0,2}|`)?(?P<date>20\d{2}-\d{2}-\d{2})\b", re.I)


def trusted(context, document):
    """Is this document written by the party that can commit the project's money?

    BountyHub's marker is ``bountyhub-app[bot]``, measured 2026-10-30 on
    ``moorcheh-ai/memanto#1852`` ("A bounty of $100.00 has been created by ..."). Without
    that login a genuine funded issue reads as no offer at all, which is exactly how a
    live $100 bounty was refused as CURRENT_ISSUER_OFFER_MISSING.

    Platform bots publish the funding attestation itself, so their login has to be
    recognised in both spellings: GitHub apps report ``algora-pbc[bot]`` while the
    platform is also referred to plainly as ``algora-pbc``. Matching only one form
    silently discards every real offer a platform publishes on someone else's issue.
    """
    user_dict = document.get("user") or {}
    user = user_dict.get("login", "")
    owner = context["repository"]["owner"]["login"]
    login = user.lower()
    user_type = str(user_dict.get("type") or "")
    is_bot = login in TRUSTED_BOTS or login.removesuffix("[bot]") in TRUSTED_BOTS
    if is_bot:
        if user_type and user_type.lower() != "bot" and not login.endswith("[bot]"):
            return False
        return True
    return (document.get("author_association", "").upper() in ISSUERS
            or login == owner.lower())


def offer_expired(context, today=None):
    """Does the latest issuer-authored explicit ISO deadline precede today?

    GitHub issue search has no qualifier for a deadline written in arbitrary body text.
    Read only the issue and funding-authority comments, then let later issuer comments
    extend an earlier deadline. Untrusted comments cannot revive or expire an offer.
    """
    today = today or datetime.now(timezone.utc).date()
    issue = context["issue"]
    comments = list(context.get("comments") or ())
    comments.sort(key=lambda document: document.get("created_at") or "")
    latest_deadline = None
    for document in [issue, *comments]:
        if not trusted(context, document):
            continue
        for line in (document.get("body") or "").splitlines():
            match = EXPLICIT_DEADLINE.search(line)
            if not match:
                continue
            try:
                latest_deadline = date.fromisoformat(match.group("date"))
            except ValueError:
                # A malformed date is not evidence that the offer has expired.
                continue
    return latest_deadline is not None and latest_deadline < today


MERGE_EVIDENCE_MIN = 10
MAX_MERGE_IDLE_DAYS = 60
# Market study 2026-11-06 (docs/MARKET-STUDY-2026-11-06.md): in the 240-PR agent field
# report, repos with no commit in 30+ days were the top failure mode ("ghost town", 35% of
# closures). Push recency is a hard vitality fact: a repo with no push in REPO_ACTIVE_DAYS
# cannot provide economic turnaround, whatever its issue text says.
REPO_ACTIVE_DAYS = 30
# Same study: bounties with 3+ open competing PRs are a lottery ("race to the bottom", 20%
# of failures; fresh bounties attract 8-158 competing agent PRs within hours). A swarm of
# open references is a fact, so it refuses regardless of whether any single PR is "real".
COMPETITION_SWARM = 3
# Escrow-only admission (mission invariant: only escrow-backed merged PRs count). A verbal
# or sponsor-allocated offer from a human is not escrow; only a platform bot attestation
# (TRUSTED_BOTS) is. Production workflows set BOUNTY_ESCROW_ONLY=1; unit fixtures default
# off so they keep testing the funding-authority logic itself.
ESCROW_ONLY = os.environ.get("BOUNTY_ESCROW_ONLY", "0") == "1"


def escrow_only_enabled() -> bool:
    """Escrow-only is on when the variable says so, read now rather than at import.

    Read at call time because a flag frozen at import is only true for the process that
    imported it. Measured 2026-11-06: the discovery workflow sets BOUNTY_ESCROW_ONLY=1 and
    the hydration workflow did not set it at all, so the drain ran with the market study's
    ~0%-conversion class admitted, while every unit test still passed. A gate that only one
    lane reads is not a mission invariant; it is a lane setting.
    """
    raw = os.environ.get("BOUNTY_ESCROW_ONLY")
    if raw is None:
        raw = "1" if ESCROW_ONLY else "0"
    return raw == "1"


def _is_owner_allocated(document, issue, amount):
    """A repository authority committing a named amount to work on their own issue.

    Measured 2026-11-07. ``fyne-io/fyne#1062`` is the largest verified money in the record:
    andydotxyz, the repository owner, wrote "$500 is currently allocated for eligible
    contributors completing this work", then "the bounty on this ticket has increased to
    $1000!", then allocated half of it to work he accepts. There is no platform bot on that
    issue, so ``escrow_only_refusal`` refuses it as ``NO_PLATFORM_ESCROW``.

    The bot-only rule rested on a market study measuring 0% conversion for non-escrow
    offers. That measurement was taken on our own interference - 46 of our 50 closed PRs were
    closed by our own account, 37 of them within six hours of creation - so the 0% describes
    what we did to our own PRs, not what the market did. Meanwhile the bot-attested pool
    measures 59 open tickets of which none are both fresh and unswarmed.

    This is a fact gate, not a judgement: the funder is the issue's author, that author's
    association is OWNER, MEMBER or COLLABORORATE, and a specific amount is named. A stranger
    promising $500 is still refused, because NONE is not in ISSUERS - and the repository's
    merge intent is already checked separately by ``repository_intent``.
    """
    if amount is None:
        return False
    funder = str((document.get("user") or {}).get("login") or "").lower()
    author = str((issue.get("user") or {}).get("login") or "").lower()
    association = str(issue.get("author_association")
                      or issue.get("authorAssociation") or "").upper()
    return bool(funder) and funder == author and association in ISSUERS


def escrow_only_refusal(offer):
    """The escrow-only gate's verdict for one offer, or None when the offer passes.

    Stated once so the entry door and both dispatch lanes - discovery and the hydration
    drain, which replays rows the door already saw and rows the door never saw - share one
    rule instead of two that can drift. The gate is a fact about an offer (is a platform
    bot attestation present), not a judgement, so it belongs in code.
    """
    if not escrow_only_enabled():
        return None
    if offer and not offer.get("escrow"):
        # Market study 2026-11-06: non-escrow offers (sponsor pools, OpenCollective
        # pledges, verbal maintainer promises, unpriced owner/FOUNDER requests) convert at
        # ~0% - every non-escrow PR of ours in the record was closed unmerged. Strict:
        # only a platform bot attestation (TRUSTED_BOTS) is escrow, no exemptions.
        return "NO_PLATFORM_ESCROW"
    return None


def _is_platform_bot(document):
    """Did a recognised escrow platform bot publish this document?"""
    login = ((document.get("user") or {}).get("login") or "").lower()
    return login in TRUSTED_BOTS or login.removesuffix("[bot]") in TRUSTED_BOTS


def repository_intent(evidence):
    """Return (ok, reason) from the repository's measured merge history.

    A bounty is paid on merge, so a repository that carries many pull requests and
    has merged none has demonstrated it does not pay, whatever its own issues say.
    Measured shape of that failure (2026-10-27): one repository took 4,458 pull
    requests and merged 0, while still publishing funded-looking issues, and its
    CONTRIBUTING.md declared the bounties symbolic.

    Recency gate (measured 2026-11-04): Spectral-Finance/lux merged 122 PRs in early 2025
    but zero in the last 18 months, leaving 665 issues/PRs dormant. If the most recent
    merge is older than MAX_MERGE_IDLE_DAYS, the project is abandoned/dormant and cannot
    provide economic turnaround.

    Absence of evidence is never rejection. A repository with fewer than
    MERGE_EVIDENCE_MIN pull requests, or an unreachable probe, gets no verdict --
    a new project that has not merged yet must not be refused on silence.
    """
    if not evidence:
        return True, ""
    merged, total = evidence.get("merged"), evidence.get("total")
    if merged is None or total is None:
        return True, ""
    if int(total) >= MERGE_EVIDENCE_MIN and int(merged) == 0:
        return False, "REPOSITORY_DOES_NOT_MERGE"

    last_merged = evidence.get("last_merged_at")
    if last_merged and int(merged) > 0:
        try:
            when = datetime.fromisoformat(str(last_merged).replace("Z", "+00:00"))
            idle_days = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
            if idle_days > MAX_MERGE_IDLE_DAYS:
                return False, "REPOSITORY_MERGES_STALE"
        except (ValueError, TypeError):
            pass

    # Push recency is a direct repository fact (GitHub repository.pushedAt, carried in
    # merge_evidence) and needs no merged-PR probe. A repo with no push for
    # MAX_MERGE_IDLE_DAYS is dormant and cannot merge-and-pay, so it is rejected even
    # when the merged-PR probe returned no node -- measured leak 2026-11-05:
    # Spectral-Finance/lux (pushedAt 2025-12-15) was re-dispatched on an empty probe.
    pushed_at = evidence.get("pushed_at")
    if pushed_at:
        try:
            when_push = datetime.fromisoformat(str(pushed_at).replace("Z", "+00:00"))
            push_idle_days = (datetime.now(timezone.utc) - when_push).total_seconds() / 86400.0
            if push_idle_days > REPO_ACTIVE_DAYS:
                return False, "REPOSITORY_MERGES_STALE"
        except (ValueError, TypeError):
            pass
    return True, ""


# Repositories whose own public funding convention is documented and observed, where the
# attestation is published by a bot that ``trusted()`` deliberately refuses (app identity,
# no repository association) and the amount lives in the issue TITLE instead of beside an
# offer word. Without an entry a genuinely paying programme is invisible: Expensify/App has
# merged 40,728 of 49,268 pull requests and was still rejected on every cycle, while the
# farm repositories were being re-hydrated.
#
# An entry is only justified by an artifact we have read ourselves, and it only widens the
# scan for that one repository. Every other gate still applies: the hard-issue test, the
# payee test, the amount floor, repository intent and competition.
FUNDING_PROGRAMS = {
    "expensify/app": {
        "title_marker": r"\[\s*\$\s*\d",
        "attestation_login": "melvin-bot[bot]",
        "attestation_pattern": r"https://www\.upwork\.com/jobs/~\d+",
        "evidence": "melvin-bot[bot] comment 'Job added to Upwork: "
                    "https://www.upwork.com/jobs/~022108002387844305757' on Expensify/App#103403, "
                    "read live 2026-10-27; the payout convention is a [$N] issue title.",
        # Accounts that speak for this repository about its own intended behaviour.
        # `trusted()` refuses them on purpose (it answers the money question, and an app
        # identity or a CONTRIBUTOR-association automation account cannot commit funds).
        # Read live 2026-10-27 from repos/Expensify/App/issues/105153/comments: the
        # declaring comment is login "MelvinBot", type "User",
        # author_association "CONTRIBUTOR", id 6447058391, created 2026-10-27T16:09:17Z,
        # html_url https://github.com/Expensify/App/issues/105153#issuecomment-6447058391,
        # concluding "**Root Cause:** This works as designed. It is not a bug." A different
        # stranger (login "camesenin", author_association "NONE") merely agreed, and an
        # untrusted agreement can never establish authority.
        "automation_logins": ("MelvinBot", "melvin-bot[bot]"),
        "automation_evidence": "MelvinBot comment id 6447058391 on Expensify/App#105153, "
                               "author_association CONTRIBUTOR, read live 2026-10-27; "
                               "melvin-bot[bot] publishes the Upwork attestation.",
    },
}


def funding_program(context):
    """Return the documented funding convention for this issue, once its attestation holds.

    The attestation is what separates a real programme from a repository that merely writes
    dollar signs in its titles: the repository's own automation must have published a payout
    artifact on this very issue. A missing attestation returns ``None`` and the ordinary
    issuer check applies unchanged.
    """
    repo_info = context.get("repository") or {}
    repo_name = repo_info.get("full_name") or context.get("repo") or ""
    entry = FUNDING_PROGRAMS.get(repo_name.lower())
    if not entry:
        return None
    issue_info = context.get("issue") or {}
    if not re.search(entry["title_marker"], issue_info.get("title") or ""):
        return None
    login = entry["attestation_login"].lower()
    pattern = re.compile(entry["attestation_pattern"], re.I)
    for comment in context.get("comments") or ():
        if (comment.get("user") or {}).get("login", "").lower() == login:
            if pattern.search(comment.get("body") or ""):
                return entry
    return None


def analysis_authority(context, document):
    """Can this document declare what the repository intends its own behaviour to be?

    ``trusted()`` answers a narrower question -- can this party commit the project's money --
    and refuses a CONTRIBUTOR, which is exactly the association a repository's own
    issue-analysis automation carries. Reusing it alone would make the gate reject every
    declaration it exists to read, so a programme's documented automation identities are
    honoured here as well. The evidence for each identity lives beside the entry.
    """
    if trusted(context, document):
        return True
    login = ((document.get("user") or {}).get("login") or "").lower()
    if not login:
        return False
    entry = FUNDING_PROGRAMS.get((context["repository"].get("full_name") or "").lower()) or {}
    documented = {name.lower().removesuffix("[bot]")
                  for name in entry.get("automation_logins", ())}
    return login.removesuffix("[bot]") in documented


def marker_sentence(body, match, limit=240):
    """Quote the line carrying the marker, never the whole comment.

    When the line is longer than the limit the excerpt is centred on the marker instead of
    taken from the start of the line: a receipt that truncates before the words that fired
    the gate proves nothing about why the gate fired. Measured live 2026-10-27 on
    limitlessprojects/Go-Hybrid#940, whose stored quote showed a CI-status bullet and hid the
    declaration further along the same line.
    """
    start = body.rfind("\n", 0, match.start()) + 1
    stop = body.find("\n", match.end())
    line = " ".join(body[start:len(body) if stop < 0 else stop].split())
    if len(line) <= limit:
        return line
    marker = " ".join(match.group(0).split())
    at = line.lower().find(marker.lower())
    if at < 0:
        return line[:limit - 3].rstrip() + "..."
    room = max(0, (limit - 3 - len(marker)) // 2)
    begin = max(0, at - room)
    end = min(len(line), begin + limit - 3)
    begin = max(0, end - (limit - 3))
    return ("..." if begin else "") + line[begin:end].strip() + "..."


def cross_reference(body, match):
    """Is this marker a pointer or bookkeeping rather than a verdict on this issue?

    Two shapes are refused as declarative. The tight one looks at the words abutting the
    marker (``closed/wontfix #627``, ``see #412``). The wider one reads the clause the marker
    sits in: an owner describing a cross-thread pointer or a checker artifact is writing
    provenance, and ``by design`` then qualifies the pointer, not the behaviour.
    """
    before = body[max(0, match.start() - 24):match.start()]
    after = body[match.end():match.end() + 24]
    if REFERENCE_BEFORE.search(before) or REFERENCE_AFTER.match(after):
        return True
    return bool(META_ARTIFACT.search(body[max(0, match.start() - 60):match.end()]))


def declared_by_design(context):
    """Return the repository's own verdict that this report is not a defect, or ``None``.

    Labels are only consulted when no authoritative comment settled the question, and an
    authoritative statement that the behaviour *is* a defect clears both, including a label
    that was applied earlier. Silence returns ``None`` -- an absence of a declaration is not
    a declaration. An aggregate board returns ``None`` as well: nothing written on a board is
    a verdict about one reported behaviour.
    """
    issue = context["issue"]
    if AGGREGATE_DOCUMENT.search((issue.get("title") or "") + "\n" + (issue.get("body") or "")):
        return None
    verdict, cleared = None, False
    for document in context.get("comments") or ():
        if not analysis_authority(context, document):
            continue
        body = document.get("body") or ""
        if REAL_BUG.search(body):
            verdict, cleared = None, True
            continue
        match = next((found for found in BY_DESIGN.finditer(body)
                      if not cross_reference(body, found)), None)
        if not match:
            continue
        verdict, cleared = {
            "verdict": "BY_DESIGN",
            "quote": marker_sentence(body, match),
            "authority": (document.get("user") or {}).get("login", ""),
            "author_association": document.get("author_association", ""),
            "source_url": document.get("html_url", ""),
            "created_at": document.get("created_at", ""),
        }, False
    if cleared or verdict:
        return verdict
    labels = {str(label.get("name") if isinstance(label, dict) else label).strip().lower()
              for label in (issue.get("labels") or ())}
    hit = labels & BY_DESIGN_LABELS
    if not hit:
        return None
    return {"verdict": "BY_DESIGN", "quote": "labels: " + ", ".join(sorted(hit)),
            "authority": (context["repository"].get("owner") or {}).get("login", ""),
            "author_association": "LABEL", "source_url": issue.get("html_url", ""),
            "created_at": ""}


def monetary_text(text):
    return re.sub(r"\x60{3}[\s\S]*?\x60{3}|~~[\s\S]*?~~|<!--[\s\S]*?-->", " ", text)


def amounts(text, positions=False):
    text = monetary_text(text)
    for match in MONEY.finditer(text):
        after = text[match.end():match.end() + 35]
        if re.match(r"\s*(?:[$\\^_]|(?:pool|TVL|ARR|MRR|valuation|treasury|budget|/month)\b)", after, re.I):
            continue
        # Ignore amounts inside markdown link text: e.g. [Article Title - $8500 P1 Bug Bounty](https://...)
        prefix = text[max(0, match.start() - 250):match.start()]
        suffix = text[match.end():min(len(text), match.end() + 250)]
        if "[" in prefix and "](" in suffix:
            last_bracket = prefix.rfind("[")
            next_close = suffix.find("](")
            if next_close != -1 and "]" not in prefix[last_bracket:]:
                continue
        amount = Decimal((match["a1"] or match["a2"]).replace(",", ""))
        if match["m1"] or match["m2"]:
            amount *= 1000
        unit = (match["c1"] or match["c2"]).upper()
        unit = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}.get(unit, unit)
        value = (amount, unit, match.group())
        yield (*value, match.start()) if positions else value


def _permalink_sources(body, repository):
    """Repository-relative source paths this report links to inside its own repository.

    Ownership is the test, not URL shape: ``https://example.org/a/file.py`` stays excluded
    exactly as ``test_component_not_invented_from_url`` requires, while a permalink whose path
    begins with this repository's own ``owner/name`` is the report quoting its own code.
    """
    full_name = (repository or "").strip("/").lower()
    if full_name.count("/") != 1:
        return []
    owner, name = full_name.split("/")
    found = set()
    for match in GITHUB_PERMALINK.finditer(body or ""):
        host = match.group("host").lower()
        path = match.group("path").split("#")[0].split("?")[0]
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) < 3 or segments[0].lower() != owner or segments[1].lower() != name:
            continue
        rest = segments[2:]
        if host == "raw.githubusercontent.com":
            rest = rest[1:]                       # <ref>/<path...>
        elif rest[0].lower() in {"blob", "tree", "raw", "blame"}:
            rest = rest[2:]                       # blob/<ref>/<path...>
        candidate = "/".join(rest)
        if candidate and SOURCE_PATH.search(candidate):
            found.add(candidate)
    return sorted(found)


def _engineering_unit(text, repository, source_url=""):
    """Extract evidence from one document without joining unrelated comments."""
    technical = sorted({match.group().lower() for match in HARD.finditer(text)})
    sanitized = re.sub(r"https?://\S+", " ", text)
    components = sorted({match.group() for match in COMPONENT.finditer(sanitized)})
    locations = sorted({name for name in components if SOURCE_PATH.search(name)}
                       | set(_permalink_sources(text, repository)))
    vocabulary = bool(technical)
    return {"technical_signals": technical, "component_references": components,
            "source_locations": locations, "source_url": source_url,
            "qualified": vocabulary or bool(locations)}


def engineering_evidence(title, body, repository=None, issue_context=None):
    """What in this report shows an engineer where the defect actually is?

    Two independent kinds of evidence, and neither one is difficulty by itself:

      * domain vocabulary (HARD) - a race, a parser, a crash. The original test.
      * a source location - someone already found the file, either as a path in the prose or
        as a permalink into this repository. This is what funded UI work looked like on
        2026-10-27: Expensify/App#105168 named ``Day.tsx`` and stated expected vs actual, and
        the vocabulary test could not see a genuine $175 defect because a date picker contains
        no deadlock.

    Measured rather than guessed: on that issue the raw body yields the path and the sanitised
    body yields nothing, which is why permalinks are read from the body before sanitisation.
    """
    issue = (issue_context or {}).get("issue") or {}
    units = [_engineering_unit(f"{title}\n{body or ''}", repository,
                               issue.get("html_url", ""))]
    if issue_context:
        # Maintainers and a programme's documented analysis automation can identify the
        # relevant code path in comments even when the original issue template only says
        # "App Component: Other". Untrusted commenter prose does not qualify, and each
        # document is scored separately so unrelated comments cannot be combined to pass.
        for document in issue_context.get("comments") or ():
            if not analysis_authority(issue_context, document):
                continue
            comment_body = document.get("body") or ""
            if comment_body.strip():
                units.append(_engineering_unit(comment_body, repository,
                                                document.get("html_url", "")))
    technical = sorted({signal for unit in units for signal in unit["technical_signals"]})
    components = sorted({reference for unit in units for reference in unit["component_references"]})
    localised = sorted({location for unit in units for location in unit["source_locations"]})
    sources = [unit["source_url"] for unit in units if unit["qualified"] and unit["source_url"]]
    return {"technical_signals": technical, "component_references": components,
            "source_locations": localised, "evidence_units": units,
            "evidence_sources": list(dict.fromkeys(sources))}


def engineering_signal(evidence):
    """Did this report say anything an engineer can act on?

    The vocabulary bar is unchanged from the original gate - one domain word plus either a
    component or a second word - and a located source file is added as a second, equal way in.
    Anything else is still refused, so this widens the vocabulary, not the standard.
    """
    units = evidence.get("evidence_units")
    if units is not None:
        return any(unit["qualified"] for unit in units)
    technical = evidence["technical_signals"]
    vocabulary = bool(technical) and (bool(evidence["component_references"]) or len(technical) >= 2)
    return vocabulary or bool(evidence["source_locations"])


def unbounded_scope(context, evidence):
    """Is this a wish, or work that can be finished?

    Measured 2026-10-30 on microg/GmsCore#1272, a USD 300 bounty that passed admission, claim and
    a real Cline checkout before the engineer refused it: the entire issue is one sentence,
    "Is it possible to add Nearby Share to MicroG and also make it work with the normal Play
    Services?", open since 2020 with 29 comments of support. Implementing it means shipping
    Google's proprietary Quick Share stack end to end - no reproducible defect, no acceptance
    criteria, no finish line.

    A wish is refused at the door so the claim, the checkout and the engineer's hour are spent on
    something that can be delivered. The refusal needs BOTH a wish form and no defect anchor: a
    request phrased politely that carries a traceback, a reproduction or a located source file is
    an ordinary bug report and passes untouched.
    """
    issue = context["issue"]
    title, body = issue["title"], issue.get("body") or ""
    text = title + " " + body
    wish = bool(WISH.search(title)) or (bool(WISH.search(body)) and len(body) < 1500)
    anchored = bool(DEFECT_ANCHOR.search(text)) or bool(evidence.get("source_locations"))
    return "UNBOUNDED_SCOPE" if wish and not anchored else None


def admit(context, quote=None, floor=FLOOR):
    """Return proof or a reason; untrusted payee text never becomes an offer."""
    issue, metadata = context["issue"], context["repository"]
    if not context.get("complete_comments"):
        return None, "INCOMPLETE_COMMENTS"
    if issue.get("state") != "open" or metadata.get("archived") or metadata.get("disabled"):
        return None, "CLOSED_OR_READ_ONLY"
    if offer_expired(context):
        return None, "EXPIRED_OFFER"
    title, body = issue["title"], issue.get("body") or ""
    # A "live room" is a chat thread, not a deliverable: measured 2026-10-30 on
    # jain-Igtm/CashGPT#1, whose owner-written $79,200 amount passed the issuer gate
    # while the issue asked for no engineering at all.
    repo_name = (metadata.get("name") or "").lower()
    repo_full = (metadata.get("full_name") or context.get("repo") or "").lower()
    if re.search(r"\b(?:picker|reading[-_]list|weekly|digest|awesome[-_]|bookmarks|news[-_]feed|arxiv)\b", repo_name) or \
       re.search(r"\b(?:picker|reading[-_]list|weekly|digest|awesome[-_]|bookmarks|news[-_]feed|arxiv)\b", repo_full):
        return None, "REFUSED_NOT_A_CODE_CHANGE: aggregator/digest repo"
    if re.search(r"每日信息流|每日安全资讯|每日资讯|\b(?:daily|weekly)\s+digest\b", title, re.I) or \
       re.search(r"每日信息流|每日安全资讯|每日资讯", body):
        return None, "REFUSED_NOT_A_CODE_CHANGE: daily news digest"
    if re.search(r"\blive room\b|\bchat ?room\b|\bcommunity (?:review|thread)\b", title, re.I):
        return None, "MIRROR_OR_NON_ENGINEERING"
    if NON_WORK.search(title) or re.search(r"automated\s+(?:superteam\s+)?digest|mirrored from|status:\s*done", body, re.I):
        return None, "MIRROR_OR_NON_ENGINEERING"
    if re.search(r"\b(?:ad spend|marketing campaign|willingness.to.pay|market validation)\b", body, re.I):
        return None, "MARKETING_OR_EXPERIMENT"
    if re.search(r"test network.*practice money|testnet (?:ETH|tokens?).*(?:only|no real)",
                 body, re.I | re.S) or EXFILTRATION.search(title + "\n" + body):
        return None, "NON_PAYMENT_OR_INSTRUCTION_EXFILTRATION"
    if CRYPTO_WALLET.search(body) and ESCROW_ADVERT.search(title + "\n" + body):
        # The document advertises a payout held somewhere else and prints the wallet to
        # claim it, so there is no defect here to engineer. Refusing keeps a farm from
        # consuming a hydration slot and then a whole engineering session.
        return None, "ADVERT_OR_ESCROW_SPAM"
    if declared_by_design(context):
        # One stable code keeps the rejection counter one bucket; the refusing document and
        # its quote are recoverable with declared_by_design(context) and are recorded in the
        # verification ledger for the issue this gate was measured on.
        return None, "REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN"
    from commercial_context import review_refusal
    review_reason, _ = review_refusal(context, context.get('commercial_review'))
    if review_reason:
        return None, review_reason
    evidence = engineering_evidence(title, body,
                                    metadata.get("full_name") or context.get("repo"),
                                    issue_context=context)
    if not engineering_signal(evidence):
        # Named for the old, narrower test on purpose: one counter keeps the refusal rate
        # comparable across the change. The proof below carries which evidence was missing.
        return None, "HARD_ISSUE_EVIDENCE_MISSING"
    unbounded = unbounded_scope(context, evidence)
    if unbounded:
        return None, unbounded
    technical, components = evidence["technical_signals"], evidence["component_references"]
    offer = None
    programme = funding_program(context)
    title_span = len(title) + 1
    for document in [issue, *context["comments"]]:
        is_issue = document is issue
        programme_offer = is_issue and programme is not None
        if not (trusted(context, document) or programme_offer):
            continue
        text = monetary_text(((title + "\n") if is_issue else "") + (document.get("body") or ""))
        if WITHDRAWN.search(text):
            offer = None
            continue
        if PAYEE.search(text) or not (OFFER.search(text) or programme_offer):
            continue
        candidates = []
        for amount, currency, raw, location in amounts(text, positions=True):
            titled = programme_offer and location < title_span
            if programme_offer and not titled:
                # A programme's documented authority is the issue TITLE: the [$N] marker is
                # what its own automation pays on. An amount written in the reporter's body
                # is not funding authority, and honouring one would invent an offer that no
                # party committed to.
                continue
            if not (titled or OFFER.search(text[max(0, location - 160):location + len(raw) + 160])):
                continue
            if currency in {"USD", "USDC", "USDT"}:
                usd, rate = amount, {"basis": "USD face value" if currency == "USD" else "USD-denominated stablecoin offer"}
            elif quote:
                rate = quote(currency)
                usd = amount * Decimal(str(rate["usd_rate"]))
            else:
                continue
            if floor <= usd <= Decimal("9999999"):
                # A title-borne programme amount is committed by the party its automation
                # attests with, not by whoever opened the issue: recording the reporter as
                # the payer would stamp funding authority on a stranger.
                payer = (programme["attestation_login"] if titled
                         else document["user"]["login"])
                candidates.append({"amount": str(amount), "currency": currency, "usd_value": str(usd),
                                   "quote": rate, "raw": raw, "source_url": document["html_url"],
                                   "payer": payer,
                                   # Two escrow classes, one field: a platform bot's attestation,
                                   # or a repository authority committing a named amount to work
                                   # on their own issue. The second is where the money actually
                                   # is - fyne#1062 holds $1000 and pays out, and no bot attests it.
                                   "escrow": _is_platform_bot(document)
                                             or _is_owner_allocated(document, issue, amount) or bool(programme)})
        if candidates:
            offer = max(candidates, key=lambda row: Decimal(row["usd_value"]))
    if offer:
        from payment_gates import funding_freshness_refusal
        freshness = funding_freshness_refusal(context, offer)
        if freshness:
            return None, freshness
    if not offer:
        assoc = str(issue.get("author_association") or issue.get("authorAssociation") or "").upper()
        is_founder_req = (context.get("lane") == "founder" or os.environ.get("BOUNTY_LANE") == "founder"
                          or context.get("is_founder") or (context.get("issue") or {}).get("lane") == "founder")
        if assoc == "OWNER" and is_founder_req:
            offer = {"amount": "0", "currency": "FOUNDER", "usd_value": "0",
                     "quote": {"basis": "Repository Owner Request"},
                     "raw": "OWNER", "source_url": issue["html_url"],
                     "payer": (issue.get("user") or {}).get("login", "owner")}
        else:
            return None, "CURRENT_ISSUER_OFFER_MISSING"
    refusal = escrow_only_refusal(offer)
    if refusal:
        return None, refusal
    return {"funding": offer, "technical_signals": technical, "component_references": components,
            "source_locations": evidence["source_locations"],
            "engineering_evidence_sources": evidence["evidence_sources"],
            "source_issue": issue["html_url"], "fetched_at": context["fetched_at"]}, ""


MAINTAINER_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}


def competition_evidence(api, repo, pull):
    """Is this open pull request a real competitor, or just a dropped file?

    Returns ``(real, evidence)``. Fails CLOSED: anything unevaluable counts as real, so a
    broken probe can never silently admit a contested ticket.

    Why this exists (measured 2026-10-30, ``microg/GmsCore``): the four funded tickets were
    covered by open PRs 3943, 3944, 3945 and 3949, so the gate refused every one of them.
    Reading those pull requests showed that between them their three authors had authored
    five pull requests in that repository and landed NONE, no maintainer had reviewed or
    commented on any of them, and none carried a successful check run. A hard ticket cannot
    be crowded by people who are not solving it: producing an unmergeable attempt is now
    free, so its existence is not evidence that somebody is ahead of us.

    A pull request blocks only on evidence that its author can actually land there: prior
    merged work in this repository, or a green check run, or maintainer attention.
    """

    login = (((pull.get("user") or {}).get("login")) or "").lower()
    number = pull.get("number")
    evidence = {"pr": pull.get("html_url"), "author": login, "number": number}
    if not login or not number:
        return True, {**evidence, "reason": "unknown_author"}

    # Measured 2026-11-01, run 41243122407: this probe fired one SEARCH call per matching
    # pull request. Search is capped at 30 requests/minute, so a repository with 24 open PRs
    # referencing one ticket spent the run asleep - seven THROTTLE events totalling 3,484
    # seconds of wait, against a 45-minute job limit. The run was killed at 22:05:40 with
    # five rows admitted and zero dispatched. The answer depends only on (repo, author), so
    # it is cached on the client: an author's merge history in a repository cannot change
    # inside one discovery cycle, and the cache dies with the client that asked.
    cache = getattr(api, "_merged_history", None)
    if cache is None:
        cache = {}
        try:
            api._merged_history = cache
        except AttributeError:  # a client that refuses attributes simply goes uncached
            cache = {}
    cache_key = (repo.lower(), login)
    if cache_key in cache:
        merged = cache[cache_key]
        if merged is None:
            return True, {**evidence, "reason": "author_history_unavailable"}
        evidence["author_merged_in_repo"] = merged
        evidence["history_cached"] = True
    else:
        try:
            query = urlencode({"q": "repo:" + repo + " type:pr author:" + login + " is:merged",
                               "per_page": 1})
            merged = int(api.api("search/issues?" + query).get("total_count") or 0)
            cache[cache_key] = merged
        except Exception:
            cache[cache_key] = None
            return True, {**evidence, "reason": "author_history_unavailable"}
        evidence["author_merged_in_repo"] = merged
    if merged > 0:
        return True, {**evidence, "reason": "author_has_landed_work_here"}

    try:
        sha = ((pull.get("head") or {}).get("sha")) or ""
        runs = api.api("repos/" + repo + "/commits/" + sha + "/check-runs").get("check_runs") or []
        evidence["check_runs"] = len(runs)
        if any(run.get("conclusion") == "success" for run in runs):
            return True, {**evidence, "reason": "green_checks"}
    except Exception:
        pass

    try:
        engaged = 0
        for review in api.pages("repos/" + repo + "/pulls/" + str(number) + "/reviews"):
            if review.get("author_association") in MAINTAINER_ASSOCIATIONS:
                engaged += 1
        for comment in api.pages("repos/" + repo + "/issues/" + str(number) + "/comments"):
            if comment.get("author_association") in MAINTAINER_ASSOCIATIONS:
                engaged += 1
    except Exception:
        return True, {**evidence, "reason": "maintainer_attention_unavailable"}
    evidence["maintainer_engagement"] = engaged
    if engaged:
        return True, {**evidence, "reason": "maintainer_is_engaged"}
    return False, {**evidence, "reason": "nominal_attempt_only"}



def _own_pull_request(pr, own_head=None):
    """Our own open PR on a ticket is a claim, never competition against ourselves.

    Measured 2026-11-06 (run 42216544639): the door's ``competition_refusal`` called
    ``competition()`` without ``own_head``, so our own open PR was counted as an open
    reference and as a swarm member. Any ticket we already hold a PR on was therefore
    unapproachable, including for a repair dispatch. The head repository's owner is the
    fact that identifies our work; ``own_head`` covers a head we know by sha alone.
    """
    head = pr.get("head") or {}
    owner = ((((head.get("repo") or {}).get("owner")) or {}).get("login") or "")
    if owner and owner.lower() == str(BOUNTY_ACCOUNT).lower():
        return True
    return bool(own_head) and head.get("sha") == own_head


def competition(api, repo, number, own_head=None):
    pattern = re.compile(rf"(?:#\s*|/issues/|\bissue\s+){number}(?!\d)|(?:^|[-_/]){number}(?:$|[-_/])", re.I)
    nominal = []
    open_refs = 0
    for pr in api.pages(f"repos/{repo}/pulls", state="open"):
        if _own_pull_request(pr, own_head):
            continue
        text = "\n".join([pr.get("title") or "", pr.get("body") or "", pr["head"]["ref"]])
        if pattern.search(text):
            open_refs += 1
            real, evidence = competition_evidence(api, repo, pr)
            if real:
                raise ValueError("Competing open PR: " + pr["html_url"])
            nominal.append(evidence)
            print("  nominal competition ignored:", evidence.get("reason"),
                  pr.get("html_url"))
    for event in api.pages(f"repos/{repo}/issues/{number}/timeline"):
        linked = (event.get("source") or {}).get("issue") or {}
        if not linked.get("pull_request"):
            continue
        pull = api.api(linked["pull_request"]["url"].removeprefix("https://api.github.com/"))
        if pull["base"]["repo"]["full_name"].lower() != repo.lower():
            continue
        if own_head and pull["head"]["sha"] == own_head:
            continue
        if linked.get("state") == "open":
            open_refs += 1
            # A link is not a claimant. This branch used to refuse on any open linked pull
            # request while the branch above it had already been taught to weigh evidence, so
            # the same pull request was nominal in one loop and fatal in the other. Measured
            # 2026-10-30: four funded microG tickets were dispatchable by every other gate and
            # every one of them died here.
            real, evidence = competition_evidence(api, repo, pull)
            if real:
                raise ValueError("Linked open PR: " + pull["html_url"])
            nominal.append(evidence)
            print("  nominal competition ignored:", evidence.get("reason"),
                  pull["html_url"])
        if pull.get("merged_at"):
            body = pull.get("body") or ""
            fixed_section = re.search(
                r"(?ims)^\s*#{1,6}\s*fixed issues\s*:?[ \t]*\r?\n"
                r"(.*?)(?=^\s*#{1,6}\s|\Z)", body)
            section_mentions_issue = bool(fixed_section and pattern.search(fixed_section.group(1)))
            direct_fix_reference = re.search(
                rf"\b(?:fix(?:es|ed)?|clos(?:e[sd])?|resolv(?:e[sd])?)\b"
                rf"[^\r\n]{{0,160}}(?:#\s*{number}(?!\d)|/issues/{number}(?!\d))",
                "\n".join((pull.get("title") or "", body)), re.I)
            if section_mentions_issue or direct_fix_reference:
                raise ValueError("Issue already resolved by merged PR: " + pull["html_url"])
    if open_refs >= COMPETITION_SWARM:
        # Market study 2026-11-06: 3+ open PRs referencing one ticket is a lottery even when
        # none is individually "real" - agent swarms post within hours of a fresh bounty.
        raise ValueError("Competition swarm: %d open PRs reference #%s" % (open_refs, number))
    return {"blocking": False, "nominal": nominal}
