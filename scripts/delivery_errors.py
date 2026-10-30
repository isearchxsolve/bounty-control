"""Typed delivery failures, shared by the worker and the Actions adapter.

Why this module exists: ``actions_delivery`` imports ``kaggle_engine_worker`` lazily
(``runtime()``) and the worker must never import the adapter back, so the exception
classes cannot live in either one if both must raise and catch them. Before this module
the worker could only raise a bare ``RuntimeError`` or ``FileNotFoundError`` and the
adapter's blanket handler stamped both ``FAILED_ENGINEER`` -- blaming the engineer for a
runner that died or an agent that finished without writing its report.

Nothing here imports another project module, so it is safe to import from anywhere.
"""
from __future__ import annotations

import re


class PreparationRace(RuntimeError):
    """The prepared baseline is still on the server's line of history, but upstream
    modified a file the plan will touch. Retryable: not an accusation, not a refusal.

    ``unknown`` marks the case where the compare payload could not prove disjointness at
    all (no ``files`` list). The overlap is then unknown, never empty, and the caller
    refuses closed while staying retryable.
    """

    def __init__(self, base, live_sha, overlap, unknown=False, ahead_by=0):
        self.base = base
        self.live_sha = live_sha
        self.overlap = overlap
        self.unknown = unknown
        # How far upstream actually moved. Carried so the failure record states the size of
        # the race instead of only its existence: "ahead_by 8" reads very differently from
        # "ahead_by 41" to whoever triages it.
        self.ahead_by = ahead_by
        detail = ("overlap unknown (compare payload carried no files)" if unknown
                  else "overlap=" + str(sorted(overlap)))
        super().__init__(
            "preparation race: base=" + str(base)[:12]
            + " live=" + str(live_sha)[:12] + " " + detail)


class ClineDeliverableMissing(RuntimeError):
    """The agent finished but produced no verification receipt at all.

    Distinct from an engineering failure: nothing was attempted, nothing was rejected.
    The diagnostic carries the elapsed time and the exit code by construction so the
    artefact explains itself without a log dig.
    """

    def __init__(self, path, elapsed=None, exit_code=None):
        self.path = str(path)
        self.elapsed = elapsed
        self.exit_code = exit_code
        message = "Cline delivered no report at " + self.path
        if elapsed is not None:
            try:
                message += " after " + format(float(elapsed), ".1f") + "s"
            except (TypeError, ValueError):
                message += " after " + str(elapsed) + "s"
        if exit_code is not None:
            message += " (exit " + str(exit_code) + ")"
        super().__init__(message)


class ClineDeliverableInvalid(RuntimeError):
    """A receipt exists but is unparseable, is still a skeleton, or violates the contract.

    ``reason`` preserves the actual violation verbatim (a JSON parse error, a bad SHA, a
    missing plan) instead of replacing it with a category name.
    """

    def __init__(self, path, reason):
        self.path = str(path)
        self.reason = str(reason)
        super().__init__("Cline deliverable invalid at " + self.path + ": " + self.reason)


class PreparationContractViolation(ClineDeliverableInvalid):
    """The agent reported a preparation that violates its own contract.

    Raised when the prepared worktree is not a clean, unchanged baseline, or when it is
    not the worktree the report names. Subclasses ``ClineDeliverableInvalid`` because it
    is a malformed deliverable, not an engineering verdict -- but it carries the offending
    paths so the artifact explains itself without a log dig. Before this class the same
    condition was a bare ``ValueError`` and landed as ``FAILED_ENGINEER`` (measured
    2026-10-29, run 40852325249).
    """

    def __init__(self, path, reason, paths=()):
        self.path = str(path)
        self.reason = str(reason)
        self.paths = [str(p) for p in (paths or ())]
        detail = self.reason
        if self.paths:
            detail += " (dirty: " + ", ".join(self.paths[:10]) + ")"
        super().__init__(path, detail)


class ClineBudgetExhausted(RuntimeError):
    """The run's own clock ran out while the agent was still working.

    A resource outcome, never an engineering verdict: no code was judged, the budget
    ended. Recorded separately so a board can tell "the agent failed" from "we did not
    give the agent long enough" -- a distinction the ledger could not make before, when
    this was a ``RuntimeError`` stamped ``FAILED_ENGINEER`` (run 40847696604).
    """

    def __init__(self, budget_seconds=None):
        self.budget_seconds = budget_seconds
        message = "CLINE_TOTAL_BUDGET_EXHAUSTED after preserving the current worktree"
        if budget_seconds is not None:
            message += " (budget " + str(budget_seconds) + "s)"
        super().__init__(message)


class RunnerShutdown(RuntimeError):
    """The Actions runner shut down mid-delivery (exit_143, shutdown signal).

    ``inferred`` is True when the log was unrecoverable and the classification came from
    the step-state signature, so an inference is never recorded as an observation.
    """

    def __init__(self, message=None, inferred=False):
        self.message = message
        self.inferred = bool(inferred)
        super().__init__(message or "Runner shutdown detected")


class InfrastructureFault(RuntimeError):
    """Infrastructure failure: disk, network, executable install, toolchain.

    ``subsystem`` must name the actual subsystem; a classification that cannot name one
    is not this class.
    """

    def __init__(self, subsystem, detail=""):
        self.subsystem = str(subsystem)
        self.detail = str(detail)
        super().__init__("Infrastructure fault in " + self.subsystem + ": " + self.detail)


PREPARATION_ACTIONS = ("retry", "reject", "blocked", "incomplete")

# ``blocked`` is what the live prompt and Cline actually emit for a refusal; ``reject`` is
# the blueprint's name for the same verdict. Both are accepted so a correct refusal can never
# be reclassified as a malformed deliverable.
REFUSAL_ACTIONS = ("reject", "blocked")


def validate_preparation(report, path):
    """Validate a preparation report before anything downstream reads it.

    Rules (F3):
      * the document must be a JSON object;
      * ``action`` must be ``retry``, a refusal (``reject``/``blocked``), or ``incomplete``;
      * ``incomplete`` means the write-early skeleton survived, i.e. Cline never
        reported, so it is refused here rather than being mistaken for a verdict;
      * ``base_sha`` must be a lowercase hex SHA (40 or 64 characters);
      * ``action == retry`` must carry a plan naming ``regression_plan.component``.

    A refusal legitimately carries no plan, so the plan rules apply only to ``retry``:
    demanding a plan from a refusal would convert every correct refusal into a
    malformed-deliverable failure.

    Raises ``ClineDeliverableInvalid`` on any violation.
    """
    if not isinstance(report, dict):
        raise ClineDeliverableInvalid(path, "not a JSON object")

    action = report.get("action")
    if action not in PREPARATION_ACTIONS:
        raise ClineDeliverableInvalid(path, "invalid action: " + repr(action))
    if action == "incomplete":
        raise ClineDeliverableInvalid(
            path, "action=incomplete: the preparation skeleton was never replaced, "
                  "so the agent finished without reporting")

    base_sha = report.get("base_sha", "")
    if (not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_sha)):
        raise ClineDeliverableInvalid(path, "invalid base_sha: " + repr(base_sha))

    if action == "retry":
        plan = report.get("plan")
        if not plan:
            raise ClineDeliverableInvalid(path, "retry action missing plan")
        regression = report.get("regression_plan")
        if not isinstance(regression, dict) or not regression.get("component"):
            raise ClineDeliverableInvalid(path, "regression_plan missing component")
    return report
