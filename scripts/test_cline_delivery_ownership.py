"""Isolated lifecycle tests. Fixtures and mocked Cline are not live fleet receipts."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import delivery_supervisor as supervisor
import kaggle_engine_worker as worker
from deploy_kaggle_engines import worker_source_for_deployment


def checkout(root):
    root.mkdir(parents=True)
    for args in (['init', '-q'], ['config', 'user.email', 'unit@example.invalid'],
                 ['config', 'user.name', 'Isolated unit fixture']):
        subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
    package = root / 'package.json'
    package.write_text(json.dumps({'scripts': {'test': 'node --test'}}), encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', 'package.json'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'unit fixture'], check=True, capture_output=True)
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()


def document(root, test=None):
    test = test or ['corepack', 'pnpm@9', 'test']
    # The intake prompt requires a regression_plan naming the defect component, and
    # validate_preparation enforces it. This fixture predated that contract, so it carries
    # the field now; no assertion in this suite depends on its absence.
    return {'action': 'retry', 'reason': 'Unit fixture plan, not an installation receipt',
            'sources': [{'path': 'package.json', 'sha256': hashlib.sha256((root / 'package.json').read_bytes()).hexdigest()}],
            'plan': {'bootstrap': [], 'baseline_tests': [test], 'final_tests': [test],
                     'linters': [], 'format_checks': []},
            'regression_plan': {'component': 'package.json', 'command': test,
                                'expected_failure': 'unit fixture regression assertion'}}


class DeliveryOwnershipTests(unittest.TestCase):
    def test_cline_is_first_executor_and_full_issue_is_not_an_argv_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory, 'sandbox')
            worktree = sandbox / 'repos' / 'unit--runtime--7'
            sha = checkout(worktree)
            packet = Path(directory, 'artifacts')
            task = {'repo': 'unit/runtime', 'issue_number': 7, 'body': 'Full issue fixture.\n' * 6000,
                    'prior_failures': ['Complete previous failure.\n' * 2000]}
            calls = []
            prompts = []

            def cline_command(cwd, prompt):
                return ['unit-cline', prompt]

            def execute(argv, **kwargs):
                calls.append('cline')
                prompt = argv[-1]
                prompts.append(prompt)
                self.assertLess(len(prompt), 12000)
                context = Path(re.search(r'from (.+\.context\.json);', prompt)[1])
                self.assertEqual(json.loads(context.read_text(encoding='utf-8')), task)
                report_path = Path(re.search(r'to (.+\.preparation\.json):', prompt)[1])
                report = document(worktree)
                report.update(worktree=str(worktree), base_sha=sha, default_branch='main')
                report_path.write_text(json.dumps(report), encoding='utf-8')
                return worker.CommandResult(argv, kwargs['cwd'], 0, 'isolated mock Cline', '', 0)

            original_git = worker._git_checked

            def git(*args, **kwargs):
                calls.append('host-git')
                return original_git(*args, **kwargs)

            with patch.object(worker, 'SANDBOX_DIR', str(sandbox)), patch.object(worker, 'PACKET_DIR', str(packet)), \
                 patch.object(worker, 'cline_worktree_command', side_effect=cline_command), \
                 patch.object(worker, 'run_command_safe', side_effect=execute), \
                 patch.object(worker, '_git_checked', side_effect=git), \
                 patch.object(worker, 'inspect_repository_architecture', side_effect=AssertionError('Host must not select tools first')), \
                 redirect_stdout(io.StringIO()):
                report = worker.run_cline_claim_intake(task, SimpleNamespace(run_id='isolated-unit-run'))
            self.assertEqual(calls[0], 'cline')
            self.assertIn('concrete code change', prompts[0])
            self.assertIn('willingness-to-pay research', prompts[0])
            self.assertIn('Do not turn a rejected/non-engineering issue into a fallback proposal', prompts[0])
            self.assertIn('Manage runner resources', prompts[0])
            # This used to pin 'separate serial commands', which was the loophole: it invited
            # the agent to run a monorepo's component checks during preparation. Two runs
            # died at exit 143 doing exactly that (2026-10-29), so the contract is now the
            # opposite -- preparation is one targeted command, repo-wide checks go in the plan.
            self.assertIn('HARD RULE for this phase', prompts[0])
            self.assertIn('ONE targeted command', prompts[0])
            self.assertIn('Do NOT run repo-wide or workspace-wide', prompts[0])
            self.assertIn('Put every repo-wide command the delivery needs in `plan`', prompts[0])
            self.assertNotIn('separate serial commands in the plan', prompts[0])
            self.assertEqual(report['plan'].baseline_tests, [['corepack', 'pnpm@9', 'test']])
            self.assertEqual(report['base_sha'], sha)

    def test_claim_dispatch_enters_cline_before_host_delivery(self):
        order = []
        context = {'plan': worker.VerificationPlan()}
        lease = SimpleNamespace(attempt=1, run_id='unit', close=lambda: None)
        with patch.object(worker, 'door_say'), \
             patch.object(worker, 'run_cline_claim_intake', side_effect=lambda *a: order.append('cline') or context), \
             patch.object(worker, 'attempt_automated_pull_request', side_effect=lambda *a, **kw: order.append(('host', kw['prepared_context']))), \
             patch.object(worker, 'get_execution_diagnostic', return_value='isolated unit blocked'):
            worker.execute_claimed_fleet_task({'repo': 'unit/runtime', 'issue_number': 7}, lease)
        self.assertEqual(order, ['cline', ('host', context)])

    def test_cline_plan_replaces_host_package_and_test_detection(self):
        plan = worker.VerificationPlan(baseline_tests=[['custom-runner', 'test']],
                                       final_tests=[['custom-runner', 'test']])
        context = {'worktree': 'unit-checkout', 'base_sha': 'a' * 40, 'default_branch': 'main',
                   'context_path': 'full-context.json', 'plan': plan}
        with ExitStack() as stack:
            stack.enter_context(patch.object(worker, 'inspect_repository_architecture', side_effect=AssertionError('Host selected tooling')))
            stack.enter_context(patch.object(worker, 'discover_verification_plan', side_effect=AssertionError('Host selected tests')))
            stack.enter_context(patch.object(worker, 'prepare_isolated_worktree', side_effect=AssertionError('Host replaced Cline checkout')))
            stack.enter_context(patch.object(worker, 'check_competing_prs_fail_closed', return_value=(True, 'clear')))
            stack.enter_context(patch.object(worker, 'run_cmd', return_value=('main', '', 0)))
            baseline = stack.enter_context(patch.object(worker, 'verify_baseline', return_value=(False, 'unit environment error', [])))
            repair = stack.enter_context(patch.object(worker, 'cline_supervise_delivery_phase', return_value=(False, plan, 'unit blocked')))
            stack.enter_context(patch.object(worker, 'mark_issue_blocked_baseline'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertIsNone(worker.attempt_automated_pull_request('unit/runtime', 7, 'Unit issue', 'Context',
                                                                   prepared_context=context))
        baseline.assert_called_once_with('unit-checkout', plan)
        self.assertEqual(repair.call_args.args[3], 'baseline')

    def test_custom_native_runner_is_not_rejected_by_ecosystem_whitelist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{}', encoding='utf-8')
            result = supervisor.validate_plan(document(root, ['unfamiliar-native-runner', 'verify']), root)
            self.assertEqual(result['final_tests'], [['unfamiliar-native-runner', 'verify']])

    def test_synthetic_success_and_bypass_commands_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{}', encoding='utf-8')
            for command in (['true'], ['echo', 'tests passed'], ['python', '-c', 'print("passed")'],
                            ['npm', 'test', '--if-present'], ['sh', '-c', 'test-command || true']):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    supervisor.validate_plan(document(root, command), root)

    def test_citations_and_baseline_targets_cannot_be_forged_or_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{}', encoding='utf-8')
            report = document(root)
            report['sources'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                supervisor.validate_plan(report, root)
            old = worker.VerificationPlan(baseline_tests=[['npm', 'test']], final_tests=[['npm', 'test']])
            with self.assertRaisesRegex(ValueError, 'dropped'):
                supervisor.validate_plan(document(root, ['other', 'smoke']), root, old)
            report = document(root)
            report['plan']['final_tests'] = []
            with self.assertRaisesRegex(ValueError, 'mandatory'):
                supervisor.validate_plan(report, root)

    def test_source_mutation_during_environment_repair_is_preserved_and_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, 'checkout')
            checkout(root)
            artifacts = Path(directory, 'artifacts')

            def execute(argv, **kwargs):
                (root / 'package.json').write_text('{"changed": true}', encoding='utf-8')
                return worker.CommandResult(argv, str(root), 0, '', '', 0)

            with patch.object(worker, 'PACKET_DIR', str(artifacts)):
                ok, _, diagnostic = supervisor.supervise(
                    root, 'unit/runtime', 7, 'baseline', 'unit baseline error', worker.VerificationPlan(),
                    artifacts, lambda *args: ['unit-cline'], execute, worker.VerificationPlan,
                    worker.preserve_cline_edits)
            self.assertFalse(ok)
            self.assertIn('changed repository', diagnostic)
            self.assertEqual((root / 'package.json').read_text(), '{"changed": true}')
            self.assertTrue(list(artifacts.rglob('*.zip')))
            self.assertTrue(list(artifacts.rglob('*.journal.json')))

    def test_preparation_cannot_omit_native_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{}', encoding='utf-8')
            report = document(root)
            report['plan']['baseline_tests'] = []
            with self.assertRaisesRegex(ValueError, 'mandatory'):
                supervisor.validate_plan(report, root)

    def test_pending_remote_checks_do_not_trigger_code_repair(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(worker, 'PACKET_DIR', folder), \
             patch.object(worker, 'run_cmd', return_value=(json.dumps([{'name': 'CI', 'bucket': 'pending'}]), '', 8)), \
             patch.object(worker, 'run_engineering_iteration_loop') as repair:
            state = worker.monitor_delivery_checks({}, 'unit/runtime', 7, 'Unit', 'Body', 'https://example.invalid/pr/1')
        self.assertEqual(state, 'CHECKS_PENDING')
        repair.assert_not_called()

    def test_real_remote_failure_is_returned_to_cline_repair(self):
        context = dict(worktree='unit', arch={}, plan=worker.VerificationPlan(), scenarios=[], base_sha='a' * 40)
        with tempfile.TemporaryDirectory() as folder, patch.object(worker, 'PACKET_DIR', folder), \
             patch.object(worker, 'run_cmd', return_value=(json.dumps([{'name': 'CI', 'bucket': 'fail'}]), '', 1)), \
             patch.object(worker, 'run_engineering_iteration_loop', return_value=(False, None, 'isolated repair blocked')) as repair, \
             redirect_stdout(io.StringIO()):
            state = worker.monitor_delivery_checks(context, 'unit/runtime', 7, 'Unit', 'Body', 'https://example.invalid/pr/1')
        self.assertEqual(state, 'REMOTE_CI_REPAIR_BLOCKED')
        self.assertIn('Actual failed remote checks', repair.call_args.args[4])

    def test_single_file_kaggle_bundle_includes_prompt_supervisor(self):
        source = worker_source_for_deployment()
        compile(source, 'unit-kaggle-bundle.py', 'exec')
        self.assertIn("_fleet_sys.modules['delivery_supervisor']", source)
        self.assertIn('CLINE_FIRST_AFTER_CLAIM', source)
        self.assertNotIn('native_build_tools', source)

    def test_all_native_commands_have_the_same_runway(self):
        with patch.dict(worker.os.environ, {'FLEET_NATIVE_TIMEOUT_SECONDS': '3600'}):
            for command in (['cargo', 'test'], ['pnpm', 'test'], ['sbt', 'test'], ['custom', 'verify']):
                self.assertEqual(worker.native_verification_timeout(command, 180), 3600)


if __name__ == '__main__':
    unittest.main(verbosity=2)
