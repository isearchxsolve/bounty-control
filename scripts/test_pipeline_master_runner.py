"""Failure reporting must remain reliable when a child suite fails or hangs."""
import json
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_pipeline_master as master


@contextlib.contextmanager
def real_child(outcome):
    """Provision actual process outcomes instead of replacing subprocess.run."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='test_live_master_child_',
            dir=master.ROOT / 'scripts', encoding='utf-8', delete=False) as child:
        child.write('import time\ntime.sleep(3)\n' if isinstance(outcome, subprocess.TimeoutExpired)
                    else 'raise SystemExit(%d)\n' % getattr(outcome, 'returncode', 0))
        path = Path(child.name)
    executable = master.sys.executable
    try:
        if isinstance(outcome, OSError):
            master.sys.executable = str(path.with_suffix('.missing-executable'))
        yield {'file': path.name, 'mode': 'script'}
    finally:
        master.sys.executable = executable
        path.unlink()


def execute_outcome(outcome, folder):
    if os.environ.get('PIPELINE_RUNNER_LIVE') == '1':
        with real_child(outcome) as suite:
            # Positive controls allow interpreter startup; the hang probe keeps
            # the original one-second enforced deadline.
            return master.execute(suite, folder,
                                  10 if isinstance(outcome, subprocess.CompletedProcess) else 1)
    kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
    with patch.object(master.subprocess, 'run', **kwargs):
        return master.execute({'file': 'test_fake.py', 'mode': 'script'}, folder, 1)


@contextlib.contextmanager
def executions(results=None):
    if os.environ.get('PIPELINE_RUNNER_LIVE') != '1':
        with patch.object(master, 'execute', **({'side_effect': results} if results is not None else {})) as executor:
            yield executor
        return
    expected = list(results or [])
    if results is not None:
        results.clear()
    original = master.execute
    class Recorder:
        call_count = 0
        def __call__(self, suite, output, timeout):
            index = self.call_count
            self.call_count += 1
            code = 7 if expected[index]['status'] == 'FAIL' else 0
            with real_child(subprocess.CompletedProcess([], code)) as child:
                receipt = original(child, output, timeout)
            results.append(receipt)
            return receipt
        def assert_not_called(self):
            if self.call_count:
                raise AssertionError('Unexpected real child execution')
    executor = Recorder()
    master.execute = executor
    try:
        yield executor
    finally:
        master.execute = original


class RunnerTests(unittest.TestCase):
    def test_process_outcomes_are_distinct(self):
        for outcome, expected in [(subprocess.CompletedProcess([], 0), "PASS"),
                                  (subprocess.CompletedProcess([], 7), "FAIL"),
                                  (subprocess.TimeoutExpired("test", 1), "TIMEOUT"),
                                  (OSError("cannot launch"), "ERROR")]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                result = execute_outcome(outcome, Path(temp))
                self.assertEqual(result["status"], expected)
                self.assertTrue((Path(temp) / result["log"]).exists())

    def test_failure_does_not_skip_later_suite_and_report_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            results = [{"suite": "first", "status": "FAIL", "seconds": 0},
                       {"suite": "second", "status": "PASS", "seconds": 0}]
            with executions(results) as execute:
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
            with self.subTest(args=args), executions() as execute:
                with self.assertRaises(SystemExit) as caught:
                    master.main(args)
                self.assertEqual(caught.exception.code, 2)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
