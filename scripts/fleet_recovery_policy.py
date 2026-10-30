"""Shared, pure recovery rules for the laptop dispatcher and cloud workers."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

MAX_EXECUTION_ATTEMPTS = 3
RECOVERY_RELEASE = '2026-10-26-discovery-repair-r9'
CLAIM_LEASE_SECONDS = 30 * 60
CLAIM_HEARTBEAT_SECONDS = 60
FLEET_LEASE_CHANNEL = 'BOUNTY_FLEET_LEASE'
RETRY_DELAYS_SECONDS = (5 * 60, 15 * 60)


def non_engineering_dispatch_reason(task: dict) -> str:
    """Exclude actual archive records and program budgets before any claim."""
    title = str(task.get('title') or '')
    body = str(task.get('body') or '')
    repo = str(task.get('repo') or '')
    if re.search(r'(?:^|/)gh-disc-[a-z0-9_.-]+(?:\s|$)', repo, re.I) or re.search(
        r'\[\s*nex\s+agent\s*\]|\b(?:github|gh)\s+discussion\s+mirror\b|'
        r'\b(?:discussion[-_ ]mirror|discussion[-_ ]honeypot|mirror[-_ ]honeypot)\b',
        title + '\n' + body, re.I,
    ):
        return 'bot/discussion mirror, not the original funded issue'
    if re.search(r'\b(?:daily|weekly|monthly|tech|news|ai)\s+(?:news\s+)?(?:digest|summary|roundup|recap|newsletter|briefing)\b', title, re.I):
        return 'dated news archive or periodic digest; quoted opportunities are not this issue\'s bounty'
    if re.search(r'^hacker\s+news\s+daily\b', title, re.I) and re.search(
        r'\b20\d{2}[-/]\d{2}[-/]\d{2}\b', title
    ):
        return 'dated news archive; quoted opportunities are not this issue\'s bounty'
    if re.search(r'(?:^|/)(?:hackernews|hacker-news|news)[-_]daily(?:$|[-_])', repo, re.I):
        return 'news archive repository, not an authoritative engineering bounty'
    if re.search(r'(?:^|/)bounty[-_](?:crawl|scout|watcher|bot|plaza|arcade)(?:$|[-_])', repo, re.I):
        return 'bounty discovery aggregator, not the original funded issue'
    if re.search(r'\bannual\s+bounty\s+budget\b', body, re.I) and re.search(
        r'\b(?:stand\s+up|set\s*up|managed)\b.{0,100}\b(?:program|vdp)\b|'
        r'\b(?:program|vdp)\b.{0,100}\bset\s*up\b', title + '\n' + body, re.I
    ):
        return 'program operating budget, not a reward for implementing this issue'
    if re.search(r'@platform-config|\bplatform_instructions\b', body, re.I) and re.search(
        r'\b(?:pre-session\s+instructions|paste\s+everything\s+verbatim|complete\s+pre-session)\b', body, re.I
    ):
        return 'submission demands disclosure of private agent instructions'
    if re.search(r'<!DOCTYPE\s+html|<html(?:\s+lang=[^>]+)?>|<head>[\s\S]*?<body', body, re.I):
        if not re.search(r'https?://[^\s)]+(?:algora\.io|polar\.sh|gitcoin\.co|opire\.dev)', body, re.I):
            return 'raw HTML source code dump or prototype template; embedded mock amounts are not authoritative bounty funding'
    if re.search(
        r'\b(?:share\s+the\s+whitepaper|announce\s+the\s+.*(?:project|whitepaper|token|network\s+launch)|'
        r'post\s+on\s+forums|online\s+forums|cryptography\s+communities|social\s+media\s+campaign|'
        r'telegram\s+group|discord\s+moderation|community\s+management|marketing\s+campaign|'
        r'promote\s+on|write\s+an\s+article\s+about|gather\s+and\s+analyze\s+community\s+feedback|'
        r'establish\s+communication\s+channels|create\s+basic\s+tutorials\s+and\s+guides)\b',
        title + '\n' + body,
        re.I
    ):
        return 'marketing, whitepaper sharing, or community outreach task, not a software engineering issue'
    if re.search(
        r'\b(?:illuminati|brotherhood|freemason|occult|sorcery|spell\s+caster|'
        r'lottery|lotto|fortune|inheritance|recovery\s+agent|whatsapp\s+us\s+on\s+\+?\d+|'
        r'call\s+(?:dr|pastor|prophet))\b',
        title + '\n' + body,
        re.I
    ):
        return 'occult, brotherhood, lottery, or fee-advance scam, not a software engineering issue'
    if re.search(
        r'\b(?:debate\s+\d+|crossroads|discussion\s+issue|opinion|personal\s+advice|'
        r'philosophical|dilemma|life\s+choice)\b',
        title + '\n' + body,
        re.I
    ):
        return 'philosophical debate, life advice, or non-software discussion thread'
    if re.search(
        r'\b(?:agile\s+training|training\s+for|workshop|seminar|course|curriculum|'
        r'syllabus|classroom|lecture|internship\s+cohort|coaching\s+session)\b',
        title + '\n' + body,
        re.I
    ):
        return 'educational training, workshop, or curriculum issue, not a software engineering issue'
    if re.search(r'(?:^|/)(?:floodissues|spam[-_]repo|test[-_]issues|test[-_]flood)(?:$|[-_])', repo, re.I) or re.search(
        r'^\s*(?:polls?|vote\s+here|test\s+issue)\s*$', title, re.I
    ):
        return 'issue flooding or poll repository, not an authoritative engineering codebase'
    if re.search(
        r'\b(?:legal\s+&\s+business\s+foundation|incorporat(?:e|ion)|llc|ein|d-u-n-s|'
        r'business\s+registration|bank\s+account\s+opening)\b',
        title + '\n' + body,
        re.I
    ):
        return 'administrative or legal business entity setup, not software engineering'
    return ''

_HARD_FAILURE = re.compile(
    r"security violation|assessment safety gate|unsafe relative path|"
    r"FAILED_NO_TEST_VERIFICATION|no native test commands|"
    r"competing (?:pull request|pr)|open (?:pull request|pr) already|"
    r"PR exists|receipt failed|HTTP\s*404|repository not found|"
    r"not a software|non-software|speculative|roadmap|bot/discussion mirror|"
    r"raw HTML source code dump|empty repository",
    re.IGNORECASE,
)
_PERMANENT_FAILURE = re.compile(
    _HARD_FAILURE.pattern + r'|re-authenticate your Cline account|Cline provider readback failed',
    re.IGNORECASE,
)
_TRANSIENT_FAILURE = re.compile(
    r"timed?\s*out|timeout|network|connection (?:reset|refused|aborted)|"
    r"temporary failure|temporarily unavailable|name resolution|"
    r"HTTP(?:\s+Error)?\s*(?:401|408|429|500|502|503|504)\b|rate.?limit|"
    r"key exhaustion|no ready .*key|model is unavailable|"
    r"model unavailable|claim lease lost|ledger .*unavailable|"
    r"Git add verified files failed.*pathspec ['\"]ackage-lock\.json['\"] did not match any files|"
    r"Unable to read Cline-modified file tests/regression/: \[Errno 21\] Is a directory",
    re.IGNORECASE,
)


def is_retryable_failure(reason: str) -> bool:
    """Unknown and deterministic failures remain closed."""
    return bool(_TRANSIENT_FAILURE.search(reason or "")) and not bool(
        _PERMANENT_FAILURE.search(reason or "")
    )


def is_repaired_infrastructure_failure(reason: str) -> bool:
    """Only the controller faults repaired in this release may be authorized."""
    return not _HARD_FAILURE.search(reason or '') and bool(re.search(
        r're-authenticate your Cline account|CLINE_TOTAL_BUDGET_EXHAUSTED|'
        r'Cline execution failed.*Command timed out after (?:900|2400|3600|14400) seconds',
        reason or '', re.IGNORECASE,
    ))


def is_nonsoftware_data_task(task: dict) -> bool:
    # These paid collection tasks require authentic account data, not code.
    return bool(re.search(
        r"\bbanking\s+transcripts?\s*,\s*\$\d+(?:\.\d+)?\s+each\b",
        str(task.get("title") or ""), re.IGNORECASE,
    ))


def task_reference(task: dict) -> str:
    return f"{task.get('repo', '')}#{task.get('issue_number', '')}"


def event_reference(text: str) -> str:
    matches = re.findall(r"\sfor\s+([^/\s]+/[^#\s]+)#(\d+)\b", text)
    if matches:
        return f"{matches[-1][0]}#{matches[-1][1]}"
    # Historical claims omitted the repository; their real task IDs encode it.
    match = re.search(r"\bBT-\d+-([^_\s]+)_(\S+)-(\d+)(?:\s|$)", text)
    return f"{match[1]}/{match[2]}#{match[3]}" if match else ""


def event_number(text: str, field: str, default: float = 0) -> float:
    match = re.search(r"\b" + re.escape(field) + r"=(\d+(?:\.\d+)?)\b", text)
    return float(match[1]) if match else default


def event_run(text: str) -> str:
    match = re.search(r"\brun=([a-zA-Z0-9_-]+)\b", text)
    return match[1] if match else ""


def _timestamp(row: dict) -> float:
    value = float(row.get("at", 0))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Fleet receipt has no valid timestamp; recovery blocked")
    return value


def matching_events(task: dict, rows: list[dict]) -> list[dict]:
    ref = task_reference(task)
    task_id = str(task.get("task_id") or "")
    selected = []
    for row in rows:
        text = str(row.get("text") or "")
        if event_reference(text) == ref or (
            task_id and re.search(r"\b" + re.escape(task_id) + r"(?:\s|$)", text)
        ):
            _timestamp(row)
            selected.append(row)
    return sorted(selected, key=_timestamp)


def current_claim(task: dict, rows: list[dict]) -> tuple[dict | None, float]:
    events = matching_events(task, rows)
    claims = [r for r in events if str(r.get("text", "")).startswith("CLAIMED ")]
    if not claims:
        return None, 0
    claim = claims[-1]
    run = event_run(claim["text"])
    lease = event_number(claim["text"], "lease_until", _timestamp(claim) + CLAIM_LEASE_SECONDS)
    # Only the latest claimant's heartbeats may extend ownership.
    if run:
        for row in events:
            if row["text"].startswith("HEARTBEAT ") and event_run(row["text"]) == run:
                lease = max(lease, event_number(row["text"], "lease_until"))
    return claim, lease


@dataclass(frozen=True)
class RecoveryDecision:
    allowed: bool
    reason: str
    attempt: int
    retry_at: float = 0
    authorized: bool = False


def recovery_decision(
    task: dict, claim_rows: list[dict], result_rows: list[dict], now: float | None = None,
) -> RecoveryDecision:
    now = time.time() if now is None else now
    if not task.get("task_id") or not task.get("repo") or not task.get("issue_number"):
        return RecoveryDecision(False, "invalid task", 0)
    if is_nonsoftware_data_task(task):
        return RecoveryDecision(False, "non-software data collection", 0)
    claims = matching_events(task, claim_rows)
    results = matching_events(task, result_rows)
    results = [r for r in results if re.match(r"^(?:SUCCESS|FAILED|SKIPPED)\b", r["text"])]
    initial_claims = [r for r in claims if r["text"].startswith("CLAIMED ")]
    failures = [r for r in results if r["text"].startswith("FAILED ")]
    explicit = [int(event_number(r["text"], "attempt")) for r in claims + results]
    # Heartbeats and repeated reads never consume attempts.
    identities = {event_run(r["text"]) or (r["at"], r["text"]) for r in initial_claims}
    used = max(len(identities), len(failures), max(explicit, default=0))
    next_attempt = used + 1
    # A trusted operator can authorize one additional infrastructure-repair
    # run, scoped to this exact release and issue. Total attempts never reset.
    authorized = used >= MAX_EXECUTION_ATTEMPTS and any(
        row['text'].startswith('RECOVERY_AUTHORIZED ')
        and re.search(r'\brelease=' + re.escape(RECOVERY_RELEASE) + r'(?:\s|$)', row['text'])
        and event_number(row['text'], 'attempt_limit') == MAX_EXECUTION_ATTEMPTS + 1
        for row in claims
    )
    # A controller may revalidate one previously undiscovered product workspace.
    # This authorizes rediscovery only: the worker must still execute the real
    # baseline, tests, lint, ownership, and publication gates. Historical test
    # failures and security/competition exclusions cannot use this authorization.
    native_marker = re.compile(
        r'verification plan:\s*FAILED_NO_TEST_VERIFICATION:\s*'
        r'no native test commands were discovered for the worktree\.', re.I,
    )
    pin_marker = re.compile(
        r'untouched upstream baseline:\s*Bootstrap command failed:\s*'
        r'cargo check --manifest-path [A-Za-z0-9_.-]+/Cargo\.toml --workspace.*?'
        r'failed to run custom build command for [`\']hyb', re.I | re.S,
    )
    native_limit = 0
    has_pin_failure = any(pin_marker.search(row['text']) for row in failures)
    if failures and all((native_marker.search(row['text']) or pin_marker.search(row['text'])) and not _PERMANENT_FAILURE.search(
        native_marker.sub('', pin_marker.sub('', row['text']))
    ) for row in failures):
        for row in claims:
            text = row['text']
            cap = int(event_number(text, 'attempt_limit'))
            if (text.startswith('RECOVERY_AUTHORIZED ')
                    and re.search(r'\brelease=' + re.escape(RECOVERY_RELEASE) + r'(?:\s|$)', text)
                    and ((not has_pin_failure and re.search(r'\brepair=nested-rust-workspace(?:\s|$)', text))
                         or (has_pin_failure and re.search(r'\brepair=pinned-rust-toolchain(?:\s|$)', text)
                             and re.search(r'\btoolchain=\d+\.\d+\.\d+(?:\s|$)', text)))
                    and re.search(r'\bmanifest=[A-Za-z0-9_-][A-Za-z0-9_.-]*/Cargo\.toml(?:\s|$)', text)
                    and 1 <= cap <= MAX_EXECUTION_ATTEMPTS
                    and _timestamp(row) > max(_timestamp(failure) for failure in failures)):
                native_limit = max(native_limit, cap)
    if any(r["text"].startswith("SUCCESS ") or re.search(r"PR exists", r["text"], re.I) for r in results):
        return RecoveryDecision(False, "already delivered or PR exists", used)
    if any(r["text"].startswith("SKIPPED ") for r in results):
        return RecoveryDecision(False, "excluded task", used)
    if any(not is_retryable_failure(r["text"]) and not (
        authorized and is_repaired_infrastructure_failure(r['text'])
    ) and not (native_limit and (native_marker.search(r['text']) or pin_marker.search(r['text']))) for r in failures):
        return RecoveryDecision(False, "permanent or unclassified failure", used)
    attempt_limit = native_limit or (MAX_EXECUTION_ATTEMPTS + int(authorized))
    authorized = authorized or bool(native_limit)
    claim, lease_until = current_claim(task, claims)
    last_result_at = _timestamp(results[-1]) if results else 0
    unfinished = claim is not None and _timestamp(claim) > last_result_at
    if unfinished and lease_until > now:
        return RecoveryDecision(False, "active claim lease", used, lease_until, authorized)
    if used >= attempt_limit:
        return RecoveryDecision(False, "attempt limit reached", used, authorized=authorized)
    if unfinished:
        return RecoveryDecision(True, "authorized infrastructure retry" if authorized else "expired claim lease", next_attempt, authorized=authorized)
    if failures:
        retry_at = _timestamp(failures[-1]) + RETRY_DELAYS_SECONDS[min(max(used - 1, 0), 1)]
        reason = "temporary failure cooldown" if now < retry_at else ("authorized infrastructure retry" if authorized else "temporary failure retry")
        return RecoveryDecision(now >= retry_at, reason, next_attempt, retry_at, authorized)
    return RecoveryDecision(True, "new task", 1)
