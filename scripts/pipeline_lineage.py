"""Receipt lineage: the facts a task must carry unchanged from the door to delivery.

A pipeline can lose provenance in a way no per-stage test can see: each hop is correct on its
own, and the row quietly stops naming the task, or the issue, or the revision of the bytes that
were admitted. The receipt is not a log line -- it is the durable row, so a test that re-reads the
row after every hop and compares it with the door's own verdict is measuring the pipeline rather
than the stages.

Only facts and gates live here (Baba Law 85): which fields constitute identity, and whether the
production evidence gate still accepts the row. No hop's meaning is interpreted.
"""
from pipeline_evidence import require_evidence

# The fields that make the proof attributable. ``source_revision`` is the digest of the exact
# issue and comment bytes the door read; ``task_id`` is the identity those bytes belong to.
LINEAGE_FIELDS = ("task_id", "repo", "issue_number", "proof_task_id", "source_revision")


def lineage(record):
    """The identity and provenance facts a durable row carries at this hop."""
    admission = (record or {}).get("admission") or {}
    code = admission.get("code_evidence") or {}
    return {"task_id": (record or {}).get("task_id"),
            "repo": (record or {}).get("repo"),
            "issue_number": (record or {}).get("issue_number"),
            "proof_task_id": admission.get("task_id"),
            "source_revision": admission.get("source_revision"),
            "code_sha": code.get("sha"),
            "status": (record or {}).get("status")}


def assert_lineage_preserved(case, record, expected, hop):
    """Every hop must still name the task, the issue and the admitted source revision.

    ``expected`` is the door's own lineage. A hop that rewrites the task identity, the origin, or
    the source revision is not a later stage of the same transaction: it is a different one, and
    the durable row must never be allowed to describe it as a continuation.
    """
    actual = lineage(record)
    for field in LINEAGE_FIELDS:
        case.assertEqual(actual[field], expected[field],
                         hop + " changed " + field + " in transit; the receipt no longer "
                         "belongs to the transaction the door admitted")
    return actual


def assert_gate_refuses(case, record, context, needle):
    """The real evidence gate must refuse a durable row that was rewritten under it.

    The store itself is only a compare-and-swap over bytes: it will happily persist a tampered
    admission. The gate is what makes that transition impossible to act on, so the assertion is
    made against ``require_evidence`` -- the function the claim and publish phases both call.
    """
    with case.assertRaises(ValueError) as caught:
        require_evidence(record, context)
    case.assertIn(needle, str(caught.exception))
    return caught.exception
