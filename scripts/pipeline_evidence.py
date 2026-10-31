"""Byte-level provenance gates shared by discovery, claims and publication."""
import hashlib
import json

from actions_github import task_id


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def source_revision(context):
    # Branch head and fetch time are deliberately excluded: this is issue evidence,
    # not the engineering baseline. All issue/comment edits participate in the hash.
    return digest({"issue": context["issue"], "comments": context["comments"]})


def bind_proof(proof, context):
    return {**proof, "task_id": task_id(context["repo"], context["issue_number"]),
            "source_revision": source_revision(context)}


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
        if proof.get("source_revision") != source_revision(context):
            raise ValueError("Admission source changed; agent reconsideration required")
        if context["issue"].get("state", "").lower() != "open":
            raise ValueError("Admitted issue is no longer open")
        if not context.get("complete_comments"):
            raise ValueError("Admission source comments incomplete")
        if context.get("repository", {}).get("archived") or context.get("repository", {}).get("disabled"):
            raise ValueError("Repository is unavailable")
    return proof, competition
