"""Byte-level provenance gates shared by discovery, claims and publication."""
import hashlib
import json

from actions_github import task_id


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


# These fields move whenever anyone merely comments (the counter, the last-activity stamp
# and the reaction tally) or the issue is closed. Measured 2026-11-06: hashing the whole
# issue object meant every passing comment invalidated every deferred admission, so the
# hydration lane re-deferred the same rows forever and only a fresh agent pass could move
# them - the backlog could not drain. Content that a decision rests on (title, body,
# labels) stays in the hash; "is it still open" is a separate gate with its own message.
VOLATILE_ISSUE_FIELDS = frozenset({"updated_at", "comments", "reactions",
                                   "state", "state_reason", "closed_at"})
VOLATILE_COMMENT_FIELDS = frozenset({"updated_at", "reactions", "node_id"})


def _issue_projection(issue):
    return {k: v for k, v in (issue or {}).items() if k not in VOLATILE_ISSUE_FIELDS}


def _comment_projection(comment):
    comment = comment or {}
    return {k: v for k, v in comment.items() if k not in VOLATILE_COMMENT_FIELDS}


def _quoted_source(context, funding):
    """The exact document the funding amount was read from, looked up live."""
    url = str(funding.get("source_url") or "")
    if not url:
        return None
    for comment in context.get("comments") or []:
        if (comment or {}).get("html_url") == url:
            return comment
    issue = context.get("issue") or {}
    return issue if issue.get("html_url") == url else None


def source_revision(context, proof=None):
    """Revision of the evidence a decision was made from.

    With a proof that quotes a funding document, the revision covers the issue's
    decision-bearing fields and only that quoted document: a new unrelated comment (agent
    swarms post constantly on bounty tickets) no longer invalidates an admission, while an
    edit or deletion of the quoted attestation still does. Without a resolvable quotation -
    no proof, or a proof carrying an amount but no source_url - every comment is covered,
    which is the stricter contract, because there is no document to prove unchanged.
    """
    funding = ((proof or {}).get("funding") or {})
    if funding:
        quoted = _quoted_source(context, funding)
        if quoted is not None:
            return digest({"issue": _issue_projection(context.get("issue")),
                           "quoted": _comment_projection(quoted)})
        if funding.get("source_url"):
            # The attestation itself is gone. That is not noise; it invalidates the proof.
            return digest({"missing_source": funding.get("source_url"),
                           "issue": _issue_projection(context.get("issue"))})
        # A proof that carries an amount but no source_url quoted nothing, so there is no
        # document to narrow to. Falling through to the full-comment revision is the only
        # honest option: measured by test_source_change_requires_agent_reconsideration,
        # narrowing here produced a revision that could not see "Funding withdrawn".
    return digest({"issue": _issue_projection(context.get("issue")),
                   "comments": [_comment_projection(c) for c in context.get("comments") or []]})


def bind_proof(proof, context):
    return {**proof, "task_id": task_id(context["repo"], context["issue_number"]),
            "source_revision": source_revision(context, proof)}


def legacy_source_revision(context):
    """The pre-2026-11-06 revision: the whole issue object and every comment.

    Kept only to recognise admissions bound before the quoted-evidence contract, so the
    existing backlog can drain without weakening the gate. If the bytes are unchanged,
    this function reproduces the stored value exactly - which is proof that nothing moved,
    not a bypass. Any real edit or deletion changes this digest too and is still refused.
    """
    return digest({"issue": context["issue"], "comments": context["comments"]})


def require_evidence(source, context=None):
    if source.get("sovereign_admission") is not True:
        raise ValueError("Sovereign admission evidence missing")
    proof, competition = source.get("admission"), source.get("competition")
    if not isinstance(proof, dict) or not proof:
        raise ValueError("Admission proof missing")
    if not isinstance(competition, dict) or competition.get("blocking") is not False:
        raise ValueError("Competition evidence missing or blocking")
    if competition.get("verified") is False or str(competition.get("verdict", "")).startswith("unverified"):
        raise ValueError("Competition observation unavailable")
    if context is not None:
        identity = task_id(context["repo"], context["issue_number"])
        if proof.get("task_id") != identity:
            raise ValueError("Admission task identity mismatch")
        bound = proof.get("source_revision")
        if bound != source_revision(context, proof) and bound != legacy_source_revision(context):
            raise ValueError("Admission source changed; agent reconsideration required")
        if context["issue"].get("state", "").lower() != "open":
            raise ValueError("Admitted issue is no longer open")
        if not context.get("complete_comments"):
            raise ValueError("Admission source comments incomplete")
        if context.get("repository", {}).get("archived") or context.get("repository", {}).get("disabled"):
            raise ValueError("Repository is unavailable")
    return proof, competition
