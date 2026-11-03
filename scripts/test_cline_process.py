"""Real OS commands exercise the long-running agent tool; no model/network mocks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import cline_process


class NativeJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.jobs = []
        self.addCleanup(self.cleanup_jobs)

    def cli(self, *args):
        return json.loads(subprocess.check_output(
            [sys.executable, cline_process.__file__, *map(str, args)], text=True))

    def start(self, source, timeout=8):
        result = self.cli('start', '--root', self.root / 'jobs', '--cwd', self.root,
                          '--timeout', timeout, '--', sys.executable, '-u', '-c', source)
        self.jobs.append(Path(result['job']))
        return result

    def cleanup_jobs(self):
        for job in self.jobs:
            if not (job / 'exit.json').exists():
                (job / 'cancel').touch()
                cline_process.observe(job, '0:0:0', 5)
        # The durable command receipt can precede the monitor interpreter's exit
        # by a few milliseconds; Windows still holds its worker.log handle then.
        deadline = time.monotonic() + 3
        while True:
            try:
                self.temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def finish(self, result):
        result = cline_process.observe(Path(result['job']), result['next_cursor'], 10)
        self.assertNotEqual(result['status'], 'PENDING_EXIT_RECEIPT')
        return result

    def test_real_exit_code_streams_and_working_directory(self):
        result = self.start('import os,sys; print(os.getcwd()); '
                            'print("native error", file=sys.stderr); sys.exit(7)')
        result = self.finish(result)
        self.assertEqual((result['status'], result['exit_code']), ('EXITED', 7))
        self.assertEqual(result['stdout'].strip(), str(self.root))
        self.assertEqual(result['stderr'].strip(), 'native error')

    def test_quiet_running_job_remains_pending_and_observation_advances(self):
        result = self.start('import time; time.sleep(30)', timeout=6)
        first = cline_process.observe(Path(result['job']), result['next_cursor'], 0.2)
        second = cline_process.observe(Path(result['job']), first['next_cursor'], 0.2)
        self.assertEqual(second['status'], 'PENDING_EXIT_RECEIPT')
        self.assertIsNone(second['exit_code'])
        self.assertNotEqual(first['next_cursor'], second['next_cursor'])
        self.assertGreater(second['observed_at'], first['observed_at'])

    def test_cursor_reads_actual_bytes_once_including_large_logs(self):
        result = self.start('import sys; sys.stdout.write("x" * 20000)')
        first = self.finish(result)
        second = cline_process.observe(Path(result['job']), first['next_cursor'], 0)
        third = cline_process.observe(Path(result['job']), second['next_cursor'], 0)
        self.assertEqual(first['stdout'] + second['stdout'], 'x' * 20000)
        self.assertEqual(third['stdout'], '')

    def test_deadline_terminates_real_command_without_faking_success(self):
        started = time.monotonic()
        result = self.start('import time; print("started", flush=True); time.sleep(30)', timeout=0.5)
        result = self.finish(result)
        self.assertEqual(result['status'], 'TIMED_OUT')
        self.assertNotEqual(result['exit_code'], 0)
        self.assertIn('started', result['stdout'])
        self.assertLess(time.monotonic() - started, 8)

    def test_cancel_stops_owned_command_and_records_real_exit(self):
        result = self.start('import time; print("started", flush=True); time.sleep(30)')
        job = Path(result['job'])
        deadline = time.monotonic() + 4
        while not (job / 'started.json').exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.cli('cancel', job)
        result = self.finish(result)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertNotEqual(result['exit_code'], 0)

    def test_start_failure_is_a_receipt_without_exit_zero(self):
        result = self.cli('start', '--root', self.root / 'jobs', '--cwd', self.root,
                          '--timeout', 3, '--', str(self.root / 'missing-program'))
        self.jobs.append(Path(result['job']))
        result = self.finish(result)
        self.assertEqual(result['status'], 'START_FAILED')
        self.assertIsNone(result['exit_code'])
        self.assertTrue(result['error'])

    def test_invalid_log_cursor_is_rejected(self):
        result = self.start('print("real output")')
        self.finish(result)
        with self.assertRaises(ValueError):
            cline_process.observe(Path(result['job']), '1:999999:0', 0)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process-group lifetime')
    def test_timeout_stops_native_descendant(self):
        result = self.start('import subprocess,sys,time; '
                            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                            'print(child.pid, flush=True); time.sleep(30)', timeout=0.5)
        result = self.finish(result)
        self.assertEqual(result['status'], 'TIMED_OUT')
        pid = int(result['stdout'].strip())
        stat = Path(f'/proc/{pid}/stat')
        if stat.exists():
            self.assertEqual(stat.read_text().split()[2], 'Z')


if __name__ == '__main__':
    unittest.main(verbosity=2)
