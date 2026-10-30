"""Exercise real OS subprocesses on Kaggle; no mocked commands or API receipts."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import kaggle_engine_worker as worker


class ProcessStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = json.loads(Path(os.environ['FLEET_RECOVERY_SNAPSHOT']).read_text(encoding='utf-8'))
        cls.task = json.loads(snapshot['queue'][0]['text'])

    def test_success_preserves_real_interpreter_output(self):
        argv = [sys.executable, '--version']
        expected = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace')
        actual = worker.run_command_safe(argv, cwd=os.getcwd(), timeout=10)
        self.assertEqual((actual.exit_code, actual.stdout, actual.stderr),
                         (expected.returncode, expected.stdout, expected.stderr))

    def test_both_streams_are_captured_and_stdout_is_live(self):
        observed = threading.Event()
        class Log(io.StringIO):
            def write(self, text):
                if 'stdout:' in text:
                    observed.set()
                return super().write(text)
        argv = [sys.executable, '-u', '-c',
                'import os,sys,time; print(os.getcwd(),flush=True); time.sleep(2); '
                'print(sys.version,file=sys.stderr,flush=True); sys.exit(7)']
        results = []
        with contextlib.redirect_stdout(Log()):
            thread = threading.Thread(target=lambda: results.append(worker.run_command_safe(argv, cwd=os.getcwd(), timeout=10)))
            thread.start()
            was_streamed = observed.wait(8)
            was_still_running = thread.is_alive()
            thread.join(timeout=12)
        self.assertTrue(was_streamed)
        self.assertTrue(was_still_running, 'Output must arrive before command completion')
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].exit_code, 7)
        self.assertEqual(results[0].stdout, os.getcwd() + '\n')
        self.assertEqual(results[0].stderr, sys.version + '\n')

    def test_stdin_preserves_actual_source_text(self):
        source = Path(worker.__file__).read_text(encoding='utf-8')
        result = worker.run_streamed_process(
            [sys.executable, '-c', 'import sys; sys.stdout.write(sys.stdin.read())'],
            cwd=os.getcwd(), timeout=10, input=source, stream_output=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, source)

    def test_timeout_keeps_partial_output_and_stops_owned_process(self):
        started = time.monotonic()
        result = worker.run_command_safe(
            [sys.executable, '-u', '-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(30)'],
            cwd=os.getcwd(), timeout=0.5,
        )
        self.assertEqual(result.exit_code, -1)
        self.assertIn('timed out after 0.5 seconds', result.stderr)
        pid = int(result.stdout.strip())
        self.assertLess(time.monotonic() - started, 6)
        if os.name == 'posix':
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    @unittest.skipUnless(os.name == 'posix', 'Kaggle process-group behavior')
    def test_timeout_stops_real_descendant_process(self):
        result = worker.run_command_safe(
            [sys.executable, '-u', '-c',
             'import subprocess,sys,time; child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
             'print(child.pid,flush=True); time.sleep(30)'],
            cwd=os.getcwd(), timeout=0.5,
        )
        self.assertEqual(result.exit_code, -1)
        pid = int(result.stdout.strip())
        stat = Path(f'/proc/{pid}/stat')
        if stat.exists():
            self.assertEqual(stat.read_text().split()[2], 'Z', 'Descendant must no longer be running')

    def test_git_error_is_real_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['git', '-C', directory, 'rev-parse', '--show-toplevel']
            expected = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace')
            out, err, code = worker.run_cmd(argv, timeout=10, retries=1)
        self.assertNotEqual(code, 0)
        self.assertEqual((out, err, code), (expected.stdout.strip(), expected.stderr.strip(), expected.returncode))

    def test_lost_ownership_stops_real_command_and_keeps_partial_output(self):
        lease = worker.FleetTaskLease(self.task, 1)
        original = worker._ACTIVE_TASK_LEASE
        worker._ACTIVE_TASK_LEASE = lease
        timer = threading.Timer(0.3, lease.lost.set)
        timer.start()
        try:
            result = worker.run_command_safe(
                [sys.executable, '-u', '-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(30)'],
                cwd=os.getcwd(), timeout=10,
            )
        finally:
            timer.join()
            worker._ACTIVE_TASK_LEASE = original
        self.assertEqual(result.exit_code, -1)
        self.assertIn('claim lease lost', result.stderr)
        pid = int(result.stdout.strip())
        if os.name == 'posix':
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_real_connection_failure_preserves_local_grace_but_blocks_publication(self):
        # This local state fixture never posts a claim or a fabricated response.
        lease = worker.FleetTaskLease(self.task, 1)
        lease.confirmed_until = time.time() + 60
        original_door, original_lease = worker.DOOR, worker._ACTIVE_TASK_LEASE
        worker.DOOR = 'http://127.0.0.1:1'
        worker._ACTIVE_TASK_LEASE = lease
        try:
            self.assertFalse(lease.owned())
            self.assertFalse(lease.lost.is_set())
            self.assertFalse(worker.fleet_lease_allows_publication())
        finally:
            worker.DOOR, worker._ACTIVE_TASK_LEASE = original_door, original_lease

    def test_real_connection_failure_without_confirmed_lease_closes_ownership(self):
        lease = worker.FleetTaskLease(self.task, 1)
        original = worker.DOOR
        worker.DOOR = 'http://127.0.0.1:1'
        try:
            self.assertFalse(lease.owned())
            self.assertTrue(lease.lost.is_set())
        finally:
            worker.DOOR = original


if __name__ == '__main__':
    unittest.main(verbosity=2)
