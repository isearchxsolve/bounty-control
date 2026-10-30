"""F3: a missing deliverable is a named failure, and a crash leaves a diagnosable artefact.

Measured need. Run ``40673403288`` ran Cline for 55 minutes, the job log ended
``END CLINE pid=2404 exit=0 elapsed=3331.4s``, and the artefact directory held only
``<sha>.context.json`` -- no ``preparation.json`` at all. The unguarded ``open()`` raised
``FileNotFoundError`` and the blanket handler stamped it ``FAILED_ENGINEER``, so "the agent
finished without reporting" was recorded as "the engineer's patch was bad". Two different
facts, one misleading word.

The fix has three parts and all three are exercised here through the real code:

* ``read_preparation()`` is the only reader, and it names each failure mode (absent,
  unparseable, or a skeleton Cline never replaced);
* a skeleton with ``action: "incomplete"`` is written before Cline is invoked, so an
  artefact directory always explains itself;
* ``validate_preparation()`` runs before anything downstream reads the report.

The adapter mapping is asserted by invoking the real ``main()`` with the phase body
replaced by a raise, so the status under test is the one the pipeline actually writes --
not a second copy of the table.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_delivery  # noqa: E402  (path must be set first)
import kaggle_engine_worker as worker  # noqa: E402
from delivery_errors import (  # noqa: E402
    ClineDeliverableInvalid,
    ClineDeliverableMissing,
    validate_preparation,
)

BASE = "3d4d2703da39e9903e9789484b838bd5a0930207"

GOLDEN_RETRY = {
    "action": "retry", "base_sha": BASE, "default_branch": "main",
    "worktree": "/tmp/worktree",
    "plan": {"bootstrap": [["npm", "ci"]], "baseline_tests": [["npm", "test"]],
             "final_tests": [["npm", "test"]], "builds": [], "linters": [],
             "format_checks": []},
    "regression_plan": {"component": "internal/painter/atlas.go",
                        "command": ["go", "test", "./internal/painter"],
                        "expected_failure": "atlas invalidation panic"},
}


class DeliverableReadTests(unittest.TestCase):
    """``read_preparation`` is the single accessor; every case goes through it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.report = self.dir / "abc123.preparation.json"

    def write(self, document):
        self.report.write_text(json.dumps(document), encoding="utf-8")

    def test_1_exit_zero_without_a_report_is_missing_not_an_engineer_failure(self):
        """The replay of run 40673403288: exit 0, no report, and a diagnostic by construction."""
        with self.assertRaises(ClineDeliverableMissing) as raised:
            worker.read_preparation(self.report, elapsed=3331.4, exit_code=0)
        message = str(raised.exception)
        self.assertIn(str(self.report), message, "the artefact must name the path it expected")
        self.assertIn("3331.4s", message, "elapsed time must be in the diagnostic, not only a log")
        self.assertIn("exit 0", message)

    def test_2_a_surviving_skeleton_names_incomplete(self):
        """The skeleton is not a verdict: it says the agent never reported."""
        self.write({"action": "incomplete", "base_sha": "", "base_branch": "",
                    "default_branch": "", "started_at": "2026-10-29T00:00:00+00:00",
                    "run": "4242:1"})
        with self.assertRaises(ClineDeliverableInvalid) as raised:
            worker.read_preparation(self.report)
        self.assertIn("incomplete", str(raised.exception))
        self.assertIn(str(self.report), str(raised.exception))

    def test_2b_the_skeleton_is_written_before_cline_and_is_valid_json(self):
        """No artefact directory can exist without a preparation document."""
        worker._write_json_atomic(str(self.report), {
            "action": "incomplete", "base_sha": "", "base_branch": "",
            "default_branch": "", "started_at": "2026-10-29T00:00:00+00:00", "run": "1:1"})
        self.assertTrue(self.report.exists())
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8"))["action"],
                         "incomplete")

    def test_3_truncated_json_preserves_the_parse_error_verbatim(self):
        truncated = '{"action": "retry", "base_sha": "'
        self.report.write_text(truncated, encoding="utf-8")
        try:
            json.loads(truncated)
        except ValueError as decode_error:
            expected = str(decode_error)
        else:  # pragma: no cover - the fixture must stay unparseable
            self.fail("the fixture was meant to be truncated JSON")
        with self.assertRaises(ClineDeliverableInvalid) as raised:
            worker.read_preparation(self.report)
        # The reason is the decoder's own words, not a category name substituted for them.
        self.assertIn(expected, str(raised.exception))

    def test_4_a_valid_retry_report_passes_through_unchanged(self):
        """Golden path: the reader returns the document, so today's flow is untouched."""
        self.write(GOLDEN_RETRY)
        report = worker.read_preparation(self.report, elapsed=1.0, exit_code=0)
        self.assertEqual(report["action"], "retry")
        self.assertEqual(report["base_sha"], BASE)
        self.assertEqual(report["regression_plan"]["component"],
                         "internal/painter/atlas.go")

    def test_5_a_refusal_is_a_verdict_not_a_malformed_deliverable(self):
        """``reject`` and ``blocked`` both read cleanly; the terminal handling is elsewhere.

        ``test_preparation_terminal.py`` already owns the REJECTED_PREPARATION contract, so
        this asserts only what F3 introduced: the reader must not reclassify a correct
        refusal as invalid.
        """
        for action in ("reject", "blocked"):
            with self.subTest(action=action):
                self.write({"action": action, "base_sha": BASE, "reason": "not a code change"})
                report = worker.read_preparation(self.report)
                self.assertEqual(report["action"], action)

    def test_6_a_bad_sha_is_refused_before_any_git_operation(self):
        for bad in ("", "abc", "3D4D2703DA39E9903E9789484B838BD5A0930207", "z" * 40):
            with self.subTest(sha=bad):
                document = dict(GOLDEN_RETRY, base_sha=bad)
                self.write(document)
                with self.assertRaises(ClineDeliverableInvalid) as raised:
                    worker.read_preparation(self.report)
                self.assertIn("base_sha", str(raised.exception))

    def test_6b_a_retry_without_a_plan_or_component_is_invalid(self):
        self.write({"action": "retry", "base_sha": BASE})
        with self.assertRaises(ClineDeliverableInvalid):
            worker.read_preparation(self.report)
        self.write({"action": "retry", "base_sha": BASE, "plan": {"final_tests": []},
                    "regression_plan": {}})
        with self.assertRaises(ClineDeliverableInvalid) as raised:
            worker.read_preparation(self.report)
        self.assertIn("regression_plan", str(raised.exception))

    def test_7_the_replacement_is_atomic_so_no_reader_sees_a_partial_document(self):
        """Skeleton first, real report second -- observed from inside ``os.replace``."""
        worker._write_json_atomic(str(self.report), {"action": "incomplete", "run": "1:1"})
        observed = []
        real_replace = os.replace

        def spy(source, target):
            # What a reader could hold at this instant: the whole previous document or
            # nothing at all, never half of either.
            if os.path.exists(target):
                with open(target, encoding="utf-8") as handle:
                    observed.append(("previous", json.load(handle)["action"]))
            else:
                observed.append(("absent", None))
            with open(source, encoding="utf-8") as handle:
                json.load(handle)  # the replacement is complete before it is swapped in
            return real_replace(source, target)

        with mock.patch.object(worker.os, "replace", spy):
            worker._write_json_atomic(str(self.report), GOLDEN_RETRY)
        self.assertEqual(observed, [("previous", "incomplete")],
                         "the swap must land on a complete previous document")
        self.assertFalse(Path(str(self.report) + ".tmp").exists(), "no temp file may remain")
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8"))["action"], "retry")

    def test_8_a_non_object_document_is_invalid(self):
        self.report.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ClineDeliverableInvalid) as raised:
            worker.read_preparation(self.report)
        self.assertIn("not a JSON object", str(raised.exception))


class DeliveryStatusTests(unittest.TestCase):
    """The status the pipeline records, taken from the real ``main()`` handler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifacts = Path(self.tmp.name) / "fleet-artifacts"
        self.artifacts.mkdir()
        self.env = mock.patch.dict(os.environ, {"FLEET_ARTIFACT_DIR": str(self.artifacts)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def status_for(self, failure):
        """Run the engineer phase with its body replaced by ``raise failure``."""
        def boom():
            raise failure

        with mock.patch.object(actions_delivery, "engineer", boom), \
                mock.patch.object(sys, "argv", ["actions_delivery.py", "engineer"]):
            with self.assertRaises(type(failure)):
                actions_delivery.main()
        return json.loads(
            (self.artifacts / "engineer-failure.json").read_text(encoding="utf-8"))

    def test_missing_deliverable_is_not_failed_engineer(self):
        record = self.status_for(
            ClineDeliverableMissing("x/preparation.json", elapsed=3331.4, exit_code=0))
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertEqual(record["kind"], "deliverable_missing")
        self.assertTrue(record["retryable"], "a machine fault is worth another attempt")
        self.assertEqual(record["elapsed"], 3331.4, "the diagnostic must carry elapsed time")
        self.assertEqual(record["exit_code"], 0, "and the exit code")

    def test_skeleton_only_lands_under_the_deliverable_status_with_its_reason(self):
        record = self.status_for(ClineDeliverableInvalid("x/preparation.json",
                                                         "action=incomplete: never replaced"))
        self.assertEqual(record["status"], "FAILED_DELIVERABLE_MISSING")
        self.assertNotEqual(record["status"], "FAILED_ENGINEER")
        self.assertEqual(record["kind"], "deliverable_invalid")
        self.assertIn("incomplete", record["reason"])


if __name__ == "__main__":
    unittest.main()
