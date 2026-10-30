"""F4: a failure taxonomy, so machine death is never recorded as engineer failure.

Measured need. Of 14 Cline-step failures in the ledger, 6 were ``RUNNER_SHUTDOWN``
(``exit_143`` plus "The runner has received a shutdown signal"), 3 ``PREPARATION_BLOCKED``,
2 ``BASELINE_MISMATCH``, 2 ``FILENOTFOUND_PREP`` and 1 ``JOB_CANCELLED``: **zero genuine
engineering failures**. A single ``except Exception`` stamped every one of them
``FAILED_ENGINEER``, so a killed runner read exactly like a bad patch, and the counter that
is supposed to measure engineering quality measured the weather instead.

What this suite pins:

* each failure class lands in its own status, and the record carries the fields that make
  the class diagnosable (``overlap``/``ahead_by`` for a race, ``inferred`` for a shutdown
  guessed from step state, ``subsystem`` for an infrastructure fault);
* ``FAILED_ENGINEER`` is **narrowed, not deleted** -- a bare exception must still land there,
  or the taxonomy has only renamed the problem;
* every emitted status keeps ``retry_eligible()``'s contract: ``FAILED_*`` retryable,
  ``REJECTED_*`` terminal;
* the emittable status set is derived from the pipeline's own source and compared with the
  documented set, so a new status cannot be introduced behind the documentation's back.

The statuses under test are read from the real ``main()`` handler, which is invoked with the
phase body replaced by a raise, and from the real ``reject_preparation()``; nothing here
restates the mapping table.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_delivery  # noqa: E402  (path must be set first)
from actions_dispatch import retry_eligible  # noqa: E402
from actions_release import validate_plan_contract  # noqa: E402
from delivery_errors import (  # noqa: E402
    ClineBudgetExhausted,
    ClineDeliverableInvalid,
    ClineDeliverableMissing,
    InfrastructureFault,
    PreparationContractViolation,
    PreparationRace,
    RunnerShutdown,
)

# The documented taxonomy (blueprint F4, "Target semantics"). A status that is not in this
# set is either undocumented or a typo; test 8 decides which by reading the source.
DOCUMENTED = {
    "REJECTED_PREPARATION",
    "FAILED_DELIVERABLE_MISSING",
    "FAILED_PREPARATION_RACE",
    "FAILED_RUNNER_SHUTDOWN",
    "FAILED_INFRASTRUCTURE",
    "FAILED_BUDGET_EXHAUSTED",
    "FAILED_ENGINEER",
}

BASE = "3d4d2703da39e9903e9789484b838bd5a0930207"
LIVE = "89356c08cea3db0b6b54792d9329d09a87cc85fa"


class FailureRecordTests(unittest.TestCase):
    """The status the pipeline records, taken from the real ``main()`` handler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifacts = Path(self.tmp.name) / "fleet-artifacts"
        self.artifacts.mkdir()
        env = mock.patch.dict(os.environ, {"FLEET_ARTIFACT_DIR": str(self.artifacts)})
        env.start()
        self.addCleanup(env.stop)
        # ``reject_preparation`` writes Actions outputs and a job summary; both are no-ops
        # without their env vars, but pinning them empty proves the test does not depend on
        # an accidental value in the developer's shell.
        for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
            os.environ.pop(name, None)

    def failure_record(self, failure):
        """Run the engineer phase with its body replaced by ``raise failure``."""
        def boom():
            raise failure

        with mock.patch.object(actions_delivery, "engineer", boom), \
                mock.patch.object(sys, "argv", ["actions_delivery.py", "engineer"]):
            with self.assertRaises(type(failure)):
                actions_delivery.main()
        return json.loads(
            (self.artifacts / "engineer-failure.json").read_text(encoding="utf-8"))

    # -- 1 -------------------------------------------------------------------------
    def test_1_a_verified_refusal_stays_terminal_and_is_not_a_failure_record(self):
        """``PreparationBlocked`` -> ``REJECTED_PREPARATION``, terminal, no failure file.

        The refusal path is owned by ``test_preparation_terminal.py`` (which covers the
        publish job staying unarmed, the summary line and the Actions output). What F4 adds
        is the boundary: a refusal must never be written as a ``*-failure.json`` record, or
        the taxonomy would start counting correct verdicts as faults again.
        """
        class Blocked(RuntimeError):
            report = {"action": "blocked", "reason": "the behaviour is by design",
                      "worktree": "/tmp/w", "base_sha": BASE, "default_branch": "main",
                      "sources": []}

            def __str__(self):
                return "preparation blocked: the behaviour is by design"

        actions_delivery.reject_preparation(Blocked(), {"task_id": "t-1"}, "o/r", 7)
        result = json.loads(
            (self.artifacts / "engineering-result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "REJECTED_PREPARATION")
        self.assertEqual(result["evidence"]["action"], "blocked")
        self.assertFalse((self.artifacts / "engineer-failure.json").exists(),
                         "a refusal is a verdict, not a failure record")
        self.assertFalse(retry_eligible(result), "a refusal must never be re-dispatched")

    # -- 2 -------------------------------------------------------------------------
    def test_2_a_missing_deliverable_is_retryable_and_never_an_engineer_failure(self):
        record = self.failure_record(
            ClineDeliverableMissing("x/preparation.json", elapsed=3331.4, exit_code=0))
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertEqual(record["kind"], "deliverable_missing")
        self.assertTrue(retry_eligible(record))
        self.assertEqual(record["elapsed"], 3331.4)
        self.assertEqual(record["exit_code"], 0)

    def test_2b_a_malformed_receipt_shares_the_deliverable_status_with_its_reason(self):
        """F4 closes the deliverable set at Missing plus Invalid: no invented status."""
        record = self.failure_record(
            ClineDeliverableInvalid("x/preparation.json", "action=incomplete: never replaced"))
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertEqual(record["kind"], "deliverable_invalid")
        self.assertTrue(retry_eligible(record))
        self.assertIn("incomplete", record["reason"])

    def test_2c_a_dirty_baseline_is_a_malformed_deliverable_with_its_paths(self):
        """A preparation-contract violation, never an engineer failure.

        Measured 2026-10-29 (run 40852325249): the agent left the worktree dirty, the
        condition was a bare ``ValueError``, and the ledger recorded ``FAILED_ENGINEER``
        for code that was never judged. It now shares the deliverable status and names the
        offending paths.
        """
        record = self.failure_record(PreparationContractViolation(
            "x/preparation.json",
            "Cline preparation must leave a clean, unchanged upstream baseline",
            paths=["tests/unit/useMarkAsReadTest.ts"]))
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertEqual(record["kind"], "deliverable_invalid")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertIn("clean", record["reason"])
        self.assertIn("useMarkAsReadTest.ts", record["reason"],
                      "the dirty path has to be in the record, not only in a log")
        self.assertTrue(retry_eligible(record))

    def test_2d_a_missing_native_plan_phase_is_a_deliverable_violation(self):
        """``validate_plan_contract`` raises typed, so it can never read as FAILED_ENGINEER.

        Measured 2026-10-29 (``isearchxsolve/bounty-proof#1``, attempt 2): the agent's plan
        carried no ``builds`` phase, the bare ``ValueError`` reached the blanket handler, and
        the ledger recorded ``FAILED_ENGINEER`` -- the same complaint as the dirty-baseline
        case in test_2c, on a different condition. The exception is produced by the real
        validator here, not constructed by hand, so the test fails if the raise ever reverts.
        """
        incomplete = SimpleNamespace(builds=[], baseline_tests=[["native", "test"]],
                                     final_tests=[["native", "test"]],
                                     linters=[["native", "lint"]])
        with self.assertRaises(PreparationContractViolation) as raised:
            validate_plan_contract(incomplete, "artifacts/preparation.json")
        # The ledger classification is decided by the type, so assert the type first, then
        # drive the real ``main()`` handler with the same exception the validator produced.
        self.assertIsInstance(raised.exception, ClineDeliverableInvalid)
        self.assertIn("builds", raised.exception.reason)
        self.assertIn("preparation.json", raised.exception.path)
        record = self.failure_record(raised.exception)
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertEqual(record["kind"], "deliverable_invalid")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertTrue(retry_eligible(record))

    # -- 3 -------------------------------------------------------------------------
    def test_3_a_race_carries_the_overlap_and_how_far_upstream_moved(self):
        """The record must state the size of the race, not only that one happened.

        ``ahead_by`` 41 is the measured Expensify-style displacement; an empty-overlap race
        is still retryable and still states how far the branch had moved.
        """
        record = self.failure_record(
            PreparationRace(BASE, LIVE, ["internal/painter/atlas.go"], ahead_by=41))
        self.assertEqual(record["status"], "FAILED_PREPARATION_RACE")
        self.assertEqual(record["kind"], "preparation_race")
        self.assertTrue(retry_eligible(record))
        self.assertEqual(record["overlap"], ["internal/painter/atlas.go"])
        self.assertEqual(record["ahead_by"], 41)
        self.assertEqual(record["base"], BASE)
        self.assertEqual(record["live_sha"], LIVE)
        self.assertFalse(record["overlap_unknown"])

    def test_3b_an_unmeasurable_overlap_is_recorded_as_unknown_not_empty(self):
        """No ``files`` list means the overlap could not be proven, which is not the same
        as proven-empty; the record has to keep those two apart."""
        record = self.failure_record(
            PreparationRace(BASE, LIVE, set(), unknown=True, ahead_by=3))
        self.assertEqual(record["status"], "FAILED_PREPARATION_RACE")
        self.assertTrue(record["overlap_unknown"])
        self.assertEqual(record["overlap"], [])
        self.assertEqual(record["ahead_by"], 3)
        self.assertTrue(retry_eligible(record))

    # -- 4 -------------------------------------------------------------------------
    def test_4_a_runner_shutdown_records_whether_it_was_inferred(self):
        record = self.failure_record(
            RunnerShutdown("The runner has received a shutdown signal", inferred=True))
        self.assertEqual(record["status"], "FAILED_RUNNER_SHUTDOWN")
        self.assertEqual(record["kind"], "runner_shutdown")
        self.assertIs(record["inferred"], True,
                      "an inference read from step state must be visible as an inference")
        self.assertIn("shutdown signal", record["message"])
        self.assertTrue(retry_eligible(record))

    def test_4b_an_observed_shutdown_is_not_labelled_an_inference(self):
        record = self.failure_record(RunnerShutdown("exit_143"))
        self.assertIs(record["inferred"], False)
        self.assertTrue(retry_eligible(record))

    # -- 5 -------------------------------------------------------------------------
    def test_5_an_infrastructure_fault_names_its_subsystem(self):
        record = self.failure_record(
            InfrastructureFault("memory", "Configure runner memory headroom: cannot allocate"))
        self.assertEqual(record["status"], "FAILED_INFRASTRUCTURE")
        self.assertEqual(record["kind"], "infrastructure")
        self.assertEqual(record["subsystem"], "memory")
        self.assertIn("memory headroom", record["detail"])
        self.assertTrue(retry_eligible(record))

    # -- 6 -------------------------------------------------------------------------
    def test_6_the_catch_all_still_catches(self):
        """Narrowed, not deleted: a real engineering failure must still land here."""
        record = self.failure_record(RuntimeError("boom"))
        self.assertEqual(record["status"], "FAILED_ENGINEER")
        self.assertEqual(record["kind"], "engineer")
        self.assertEqual(record["diagnostic"], "boom")
        self.assertTrue(retry_eligible(record))

    def test_6b_budget_exhaustion_is_its_own_outcome_not_an_engineer_failure(self):
        """The clock ending is not a verdict on the code.

        Measured 2026-10-29 (run 40847696604): a run that used its whole window while still
        working was recorded as ``FAILED_ENGINEER``, which makes "out of time"
        indistinguishable from "produced a broken patch".
        """
        record = self.failure_record(ClineBudgetExhausted(14400))
        self.assertEqual(record["status"], "FAILED_BUDGET_EXHAUSTED")
        self.assertEqual(record["kind"], "budget")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertEqual(record["budget_seconds"], 14400)
        self.assertIn("BUDGET_EXHAUSTED", record["diagnostic"])
        self.assertTrue(retry_eligible(record))

    # -- 7 -------------------------------------------------------------------------
    def test_7_retryability_follows_the_status_prefix_for_every_emitted_status(self):
        produced = [
            self.failure_record(ClineDeliverableMissing("x", elapsed=1.0, exit_code=0)),
            self.failure_record(ClineDeliverableInvalid("x", "bad")),
            self.failure_record(PreparationRace(BASE, LIVE, ["a"], ahead_by=1)),
            self.failure_record(RunnerShutdown("exit_143")),
            self.failure_record(InfrastructureFault("disk", "no space")),
            self.failure_record(ClineBudgetExhausted(14400)),
            self.failure_record(RuntimeError("boom")),
        ]
        seen = {}
        for record in produced:
            status = record["status"]
            seen.setdefault(status, []).append(record["kind"])
            with self.subTest(status=status):
                self.assertEqual(retry_eligible(record), status.startswith("FAILED"),
                                 "retry_eligible must agree with the status prefix")
        # F4 closes the deliverable set at Missing plus Invalid, so those two classes share
        # one status and are distinguished by ``kind``. Every other class owns its own.
        self.assertEqual(sorted(seen["FAILED_DELIVERABLE_MISSING"]),
                         ["deliverable_invalid", "deliverable_missing"])
        self.assertEqual(len(seen), 6, "six statuses for seven classes, by that decision")

    # -- 8 -------------------------------------------------------------------------
    def test_8_the_emittable_status_set_equals_the_documented_set(self):
        """Table-driven, with both sides derived rather than restated.

        The left side is read out of ``actions_delivery.py``: the literal statuses inside
        ``main()``'s handlers plus the dynamic catch-all, plus ``reject_preparation``'s own
        status. The right side is the documented taxonomy.
        """
        source = (HERE / "actions_delivery.py").read_text(encoding="utf-8")

        def block(name, end="\ndef "):
            start = source.index("def " + name + "(")
            stop = source.find(end, start + 1)
            return source[start:stop if stop != -1 else len(source)]

        main_body = block("main", "\nif __name__")
        literals = set(re.findall(r'"status": "(FAILED_[A-Z_]+|REJECTED_[A-Z_]+)"', main_body))
        # The catch-all is built by concatenation, so it is asserted present rather than
        # parsed: ``FAILED_ENGINEER`` disappearing from the source must fail this test.
        self.assertIn('"FAILED_" + args.phase.upper()', main_body,
                      "the catch-all must stay reachable (F4: narrowed, not deleted)")
        emitted = literals | {"FAILED_ENGINEER"}

        refusal = set(re.findall(r'"status": "(REJECTED_[A-Z_]+)"', block("reject_preparation")))
        self.assertEqual(refusal, {"REJECTED_PREPARATION"},
                         "a refusal is emitted only by reject_preparation")
        emitted |= refusal

        self.assertEqual(emitted, DOCUMENTED,
                         "the emitted statuses and the documented taxonomy have diverged")
        # And the terminal half of the set behaves terminally, the retryable half retryably.
        for status in sorted(emitted):
            with self.subTest(status=status):
                self.assertEqual(retry_eligible({"status": status}),
                                 status.startswith("FAILED"))


class TerminalResultTests(unittest.TestCase):
    """What a finished run leaves behind, including the case where it wrote nothing.

    Both 2026-10-29 deliveries ended with exit 143 and were filed ``FAILED_MISSING_RECEIPT``:
    a SIGTERM kills the process before any handler writes a record, so ``finish`` had nothing
    to read. That is the taxonomy's own target class, so it is inferred and flagged.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_a_terminated_phase_is_a_runner_shutdown_flagged_as_inferred(self):
        record = actions_delivery.terminal_result(self.folder, "failure")
        self.assertEqual(record["status"], "FAILED_RUNNER_SHUTDOWN")
        self.assertEqual(record["kind"], "runner_shutdown")
        self.assertIs(record["inferred"], True,
                      "an inference from absence must never be recorded as an observation")
        self.assertTrue(retry_eligible(record))
        self.assertIn("exit 143", record["diagnostic"])

    def test_a_clean_run_that_wrote_nothing_is_still_a_missing_receipt(self):
        record = actions_delivery.terminal_result(self.folder, "success")
        self.assertEqual(record["status"], "FAILED_MISSING_RECEIPT")

    def test_a_written_failure_record_still_wins(self):
        (self.folder / "engineer-failure.json").write_text(json.dumps(
            {"status": "FAILED_BUDGET_EXHAUSTED", "kind": "budget"}), encoding="utf-8")
        record = actions_delivery.terminal_result(self.folder, "failure")
        self.assertEqual(record["status"], "FAILED_BUDGET_EXHAUSTED")
        self.assertNotIn("inferred", record)

    def test_a_written_result_still_wins(self):
        (self.folder / "engineering-result.json").write_text(json.dumps(
            {"status": "REJECTED_PREPARATION"}), encoding="utf-8")
        record = actions_delivery.terminal_result(self.folder, "failure")
        self.assertEqual(record["status"], "REJECTED_PREPARATION")

    def test_a_publication_record_is_not_overridden_by_the_inference(self):
        # The inference only fills an empty hand; it never replaces a real record.
        (self.folder / "engineering-result.json").write_text(json.dumps(
            {"status": "VERIFIED"}), encoding="utf-8")
        self.assertEqual(
            actions_delivery.terminal_result(self.folder, "failure")["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
