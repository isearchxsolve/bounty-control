"""Regression checks for the four partition plumbing faults; no model calls."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import autonomous_icu_pipeline as dispatcher
import kaggle_engine_worker as worker
from fleet_recovery_policy import is_repaired_infrastructure_failure


class PartitionRegressionTests(unittest.TestCase):
    def test_cline_engineering_standalone_timeout_is_at_least_sixty_minutes(self):
        ecosystems = [
            [], ['typescript'], ['javascript'], ['python'], ['rust'], ['go'],
            ['typescript', 'rust'], ['unknown'],
        ]
        for ecosystem in ecosystems:
            with self.subTest(ecosystem=ecosystem):
                self.assertGreaterEqual(worker.cline_turn_timeout_seconds(ecosystem), 3600)

    def test_actions_cline_budget_is_shared_across_turns_and_expires(self):
        worker.set_cline_execution_budget(None)
        try:
            with patch.object(worker.time, 'monotonic', side_effect=[100.0, 100.0, 3700.0, 14500.0]):
                worker.set_cline_execution_budget(14400)
                self.assertEqual(worker.cline_turn_timeout_seconds(['typescript']), 14400)
                self.assertEqual(worker.cline_turn_timeout_seconds(['typescript']), 10800)
                self.assertEqual(worker.cline_turn_timeout_seconds(['typescript']), 0)
        finally:
            worker.set_cline_execution_budget(None)

    def test_actions_delivery_installs_four_hour_budget_before_first_cline_phase(self):
        root = Path(__file__).resolve().parent.parent
        delivery = (root / 'scripts' / 'actions_delivery.py').read_text(encoding='utf-8')
        workflow = (root / '.github' / 'workflows' / 'engine2.yml').read_text(encoding='utf-8')
        self.assertLess(delivery.index('worker.set_cline_execution_budget(cline_budget)'),
                        delivery.index('worker.run_cline_claim_intake(task, lease)'))
        self.assertIn("CLINE_TOTAL_BUDGET_SECONDS: '14400'", workflow)

    def test_four_hour_cline_timeout_is_recognized_as_repaired_infrastructure_failure(self):
        reason = 'Cline execution failed (exit -1): Command timed out after 14400 seconds'
        self.assertTrue(is_repaired_infrastructure_failure(reason))
        self.assertTrue(is_repaired_infrastructure_failure(
            'CLINE_TOTAL_BUDGET_EXHAUSTED after preserving the current worktree'))
        self.assertFalse(is_repaired_infrastructure_failure(
            'Cline execution failed: Command timed out after 7200 seconds'))

    def test_real_collector_reads_new_nested_tests_and_unusual_names(self):
        for module in (dispatcher, worker):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                subprocess.run(['git', 'init', '-q', directory], check=True)
                subprocess.run(['git', '-C', directory, 'config', 'core.autocrlf', 'false'], check=True)
                relative = 'tests/regression/new test case.ts'
                source = 'export const regression = true;\n'

                def execute(*args, **kwargs):
                    target = Path(directory, relative)
                    target.parent.mkdir(parents=True)
                    target.write_text(source, encoding='utf-8')
                    return module.CommandResult(argv=['cline'], cwd=directory, exit_code=0,
                                                stdout='', stderr='', duration_s=0)

                with patch.object(module, 'resolve_cline_command', return_value=['cline']), \
                     patch.object(module, 'ensure_cline_proxy_running', return_value=(True, 'ready')), \
                     patch.object(module, 'run_command_safe', side_effect=execute):
                    ok, changes, paths, message = module.run_cline_engineering_turn(
                        directory, 'owner/repository', 1, 'Regression', 'Actual requirements', {}, [], None)
                self.assertTrue(ok, message)
                self.assertEqual(changes, [(relative, source)])
                self.assertEqual(paths, [relative])
                self.assertEqual(Path(directory, relative).read_text(), source)

    def test_failed_collection_recovery_preserves_tracked_and_nested_untracked_bytes(self):
        for module in (dispatcher, worker):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory, \
                 tempfile.TemporaryDirectory() as packets:
                subprocess.run(['git', 'init', '-q', directory], check=True)
                subprocess.run(['git', '-C', directory, 'config', 'core.autocrlf', 'false'], check=True)
                tracked = Path(directory, 'tracked.txt')
                tracked.write_bytes(b'before\n')
                subprocess.run(['git', '-C', directory, 'add', '.'], check=True)
                subprocess.run(['git', '-C', directory, '-c', 'user.name=Verifier',
                                '-c', 'user.email=verifier@localhost', 'commit', '-qm', 'base'], check=True)
                tracked.write_bytes(b'completed edit\n')
                nested = Path(directory, 'tests/regression/test.bin')
                nested.parent.mkdir(parents=True)
                nested.write_bytes(b'\x00\xffcompleted test')
                with patch.object(module, 'PACKET_DIR', packets):
                    receipt = module.preserve_cline_edits(directory)
                archive_path, digest = receipt.split(' sha256=')
                self.assertEqual(hashlib.sha256(Path(archive_path).read_bytes()).hexdigest(), digest)
                subprocess.run(['git', '-C', directory, 'reset', '--hard', '-q', 'HEAD'], check=True)
                subprocess.run(['git', '-C', directory, 'clean', '-fdx', '-q'], check=True)
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(archive.read('tracked/tracked.txt'), b'completed edit\n')
                    self.assertEqual(archive.read('untracked/tests/regression/test.bin'), b'\x00\xffcompleted test')
                    result = subprocess.run(['git', '-C', directory, 'apply', '--binary', '-'],
                                            input=archive.read('tracked.patch'), capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(tracked.read_bytes(), b'completed edit\n')

    def test_nul_parser_does_not_split_filename_arrows_or_drop_rename_source(self):
        for module in (dispatcher, worker):
            ok, paths, message = module._status_paths_from_porcelain(
                '?? tests/new -> case.ts\0R  renamed test.ts\0old test.ts\0')
            self.assertTrue(ok, message)
            self.assertEqual(paths, ['old test.ts', 'renamed test.ts', 'tests/new -> case.ts'])
            self.assertFalse(module._status_paths_from_porcelain('R  renamed.ts\0')[0])

    def test_prompt_retains_issue_beyond_twenty_thousand_and_allows_tests(self):
        body = 'Actual issue context\n' * 2400 + 'FINAL_REQUIREMENT'
        self.assertGreater(len(body), 20000)
        for module in (dispatcher, worker):
            prompt = module.build_cline_engineering_prompt('owner/repository', 1, 'Issue', body, {}, [], None)
            self.assertIn('FINAL_REQUIREMENT', prompt)
            self.assertIn('Run the relevant repository tests and linters when practical', prompt)
            self.assertIn('available RAM/CPU', prompt)
            self.assertIn('serially', prompt)
            self.assertNotIn('Do not run compilers', prompt)

    def test_node22_bootstrap_replaces_old_runtime_and_verifies_checksum(self):
        payload = b'archive bytes used only to exercise checksum enforcement'
        probes = [subprocess.CompletedProcess([], 0, 'v20.19.0\n', ''),
                  subprocess.CompletedProcess([], 0, '', ''),
                  subprocess.CompletedProcess([], 0, f'v{worker.NODE_LTS_VERSION}\n', '')]
        with tempfile.TemporaryDirectory() as temporary:
            def download(url, destination, timeout):
                self.assertIn('/dist/v22.', url)
                Path(destination).write_bytes(payload)

            real_open = open
            def redirected_open(path, *args, **kwargs):
                return real_open(Path(temporary, Path(path).name), *args, **kwargs)

            def redirected_download(url, destination, timeout):
                download(url, str(Path(temporary, Path(destination).name)), timeout)

            with patch.object(worker, '_download_init_file', side_effect=redirected_download), \
                 patch('builtins.open', side_effect=redirected_open), \
                 patch.object(worker.os, 'makedirs'), \
                 patch.object(worker.shutil, 'which', return_value='/runtime/node'), \
                 patch.object(worker.subprocess, 'run', side_effect=probes) as commands, \
                 patch.object(worker, 'NODE_LTS_SHA256', hashlib.sha256(payload).hexdigest()), \
                 patch.object(worker, 'CLINE_NODE_EXE', ''), patch.dict(os.environ):
                self.assertEqual(worker.ensure_supported_node(), '/runtime/node')
                self.assertEqual(worker.CLINE_NODE_EXE, '/runtime/node')
                self.assertEqual(commands.call_args_list[1].args[0][0], 'tar')

            with patch.object(worker, '_download_init_file', side_effect=redirected_download), \
                 patch('builtins.open', side_effect=redirected_open), \
                 patch.object(worker.shutil, 'which', return_value=None), \
                 patch.object(worker.subprocess, 'run') as commands:
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    worker.ensure_supported_node()
                commands.assert_not_called()


if __name__ == '__main__':
    unittest.main()
