"""Failure reporting must remain reliable when a child suite fails or hangs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_pipeline_master as master


class RunnerTests(unittest.TestCase):
    def test_process_outcomes_are_distinct(self):
        for outcome, expected in [(subprocess.CompletedProcess([], 0), "PASS"),
                                  (subprocess.CompletedProcess([], 7), "FAIL"),
                                  (subprocess.TimeoutExpired("test", 1), "TIMEOUT"),
                                  (OSError("cannot launch"), "ERROR")]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(master.subprocess, "run", **kwargs):
                    result = master.execute({"file": "test_fake.py", "mode": "script"}, Path(temp), 1)
                self.assertEqual(result["status"], expected)
                self.assertTrue((Path(temp) / result["log"]).exists())

    def test_failure_does_not_skip_later_suite_and_report_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            results = [{"suite": "first", "status": "FAIL", "seconds": 0},
                       {"suite": "second", "status": "PASS", "seconds": 0}]
            with patch.object(master, "execute", side_effect=results) as execute:
                code = master.main(["--output", temp, "--suite", "test_pipeline_failure_master.py",
                                    "--suite", "test_pipeline_master_runner.py"])
            report = json.loads(next(Path(temp).glob("*/report.json")).read_text())
            self.assertEqual(code, 1)
            self.assertEqual(execute.call_count, 2)
            self.assertTrue(report["complete"])
            self.assertFalse(report["passed"])
            self.assertEqual(report["results"], results)

    def test_invalid_selection_and_timeout_fail_before_execution(self):
        for args in (["--suite", "test_live_probe.py"], ["--timeout", "0"]):
            with self.subTest(args=args), patch.object(master, "execute") as execute:
                with self.assertRaises(SystemExit) as caught:
                    master.main(args)
                self.assertEqual(caught.exception.code, 2)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
