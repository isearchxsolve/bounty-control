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
            # Baba 2026-10-31 (sovereign entry door): these three assertions used to pin the
            # intake classification gate - "proceed only when it requests a concrete code
            # change", "willingness-to-pay research", "do not turn a rejected issue into a
            # proposal". That gate was the delivery-side twin of the door's decision and it
            # refused 42 of 42 admitted tickets. The prompt now carries the opposite law.
            self.assertIn('SUPREME MANDATE: ZERO JUDGMENT OF ISSUE QUALITY', prompts[0])
            self.assertIn('strictly forbidden from writing action="blocked"', prompts[0])
            self.assertIn('Sovereign Entry Door has ALREADY inspected', prompts[0])
            self.assertNotIn('willingness-to-pay research', prompts[0])
            self.assertNotIn('classify the issue', prompts[0])
            self.assertIn('Manage runner resources', prompts[0])
            # This used to pin 'separate serial commands', which was the loophole: it invited
            # the agent to run a monorepo's component checks during preparation. Two runs
            # died at exit 143 doing exactly that (2026-10-29), so the contract is now the
            # opposite -- preparation is one targeted command, repo-wide checks go in the plan.
            self.assertIn('HOW THE MEASURING WORKS', prompts[0])
            self.assertIn('ONE targeted command', prompts[0])
            self.assertIn('Repo-wide or workspace-wide lint, typecheck, build or test', prompts[0])
            self.assertIn('Put every repo-wide command the delivery needs in `plan`', prompts[0])
            self.assertNotIn('separate serial commands in the plan', prompts[0])
            # The baseline rule is knowledge of the world, not a prohibition: measured 2026-11-01,
            # six retries wrote regression tests into the customer's tree because the directive
            # asked for a reproduction command without saying the test is authored in the
            # engineering turn.
            self.assertIn('HOW THIS DELIVERY IS SHAPED', prompts[0])
            self.assertIn('the test is authored in the engineering turn', prompts[0])
            self.assertIn('never the repository tree', prompts[0])
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


    def test_the_delivery_phase_uses_the_guard_and_not_the_bare_status_check(self):
        """Reverting the call site reintroduces the false positive without touching the guard,
        so the wiring is pinned here rather than only the guard's behaviour.

        Measured 2026-11-01: the call site read `if status_paths(root): raise ValueError(
        "Provisioning mutated the untouched source baseline")`, and that one line refused a
        whole day's deliveries over a lockfile their own bootstrap had rewritten.
        """
        source = (Path(__file__).resolve().parent / 'actions_delivery.py').read_text(encoding='utf-8')
        self.assertIn('guard_untouched_baseline(root)', source)
        self.assertNotIn('if status_paths(root):\n            raise ValueError("Provisioning mutated '
                         'the untouched source baseline")', source)
        """Measured 2026-11-01 (OpenOrg-gg/AmphoraProtocol#4, run 41357319521): the plan said
        `npm install --no-save`, npm 7+ rewrote package-lock.json anyway, and the host killed the
        delivery at the untouched-baseline gate -- twice in one day. The directive now names the
        non-destructive form, so the agent does not have to discover it by failing."""
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory, 'sandbox')
            worktree = sandbox / 'repos' / 'unit--runtime--7'
            sha = checkout(worktree)
            prompts = []

            def execute(argv, **kwargs):
                prompts.append(argv[-1])
                report = document(worktree)
                report.update(worktree=str(worktree), base_sha=sha, default_branch='main')
                report_path = Path(re.search(r'to (.+\.preparation\.json):', argv[-1])[1])
                report_path.write_text(json.dumps(report), encoding='utf-8')
                return worker.CommandResult(argv, kwargs['cwd'], 0, 'isolated mock Cline', '', 0)

            with patch.object(worker, 'SANDBOX_DIR', str(sandbox)), \
                 patch.object(worker, 'PACKET_DIR', str(Path(directory, 'packet'))), \
                 patch.object(worker, 'cline_worktree_command', side_effect=lambda cwd, p: ['unit-cline', p]), \
                 patch.object(worker, 'run_command_safe', side_effect=execute), \
                 patch.object(worker, '_git_checked', side_effect=worker._git_checked), \
                 redirect_stdout(io.StringIO()):
                worker.run_cline_claim_intake({'repo': 'unit/runtime', 'issue_number': 7,
                                               'body': 'fixture'}, SimpleNamespace(run_id='isolated-unit-run'))
        self.assertIn('non-destructive to tracked files', prompts[0])
        self.assertIn('--no-package-lock', prompts[0])
        self.assertIn('npm ci', prompts[0])


class SupervisorReceiptTests(unittest.TestCase):
    """The repair turn's control artifact must survive the turn being killed.

    Measured 2026-11-01 (Spectral-Finance/lux#74, run 41357309340): Cline's repair turn was
    aborted by the supervisor timeout while a background Erlang compile was still running. The
    turn exited without writing a decision, the reader raised FileNotFoundError on the absent
    receipt, and the host stamped that as BLOCKED_BASELINE -- a transient timeout recorded as a
    permanent statement about the repository. A write-early skeleton makes the artifact exist
    from the moment the command is built, and names what an unfinished turn actually was.
    """

    def receipts(self, artifacts):
        folder = artifacts / 'delivery-supervisor'
        return [path for path in folder.glob('*.json')
                if not path.name.endswith(('.plan.json', '.journal.json'))]

    def test_an_aborted_turn_explains_itself_instead_of_vanishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, 'checkout')
            checkout(root)
            artifacts = Path(directory, 'artifacts')
            seen = {}

            def execute(argv, **kwargs):
                # The turn ends cleanly and never writes a decision: what an abort by another
                # client looks like from the outside.
                receipt = self.receipts(artifacts)[0]
                seen['skeleton'] = json.loads(receipt.read_text(encoding='utf-8'))
                return worker.CommandResult(argv, kwargs['cwd'], 0, '', '', 0)

            ok, recovered, diagnostic = supervisor.supervise(
                root, 'unit/runtime', 7, 'baseline', 'unit baseline error',
                worker.VerificationPlan(), artifacts, lambda *args: ['unit-cline'], execute,
                worker.VerificationPlan, worker.preserve_cline_edits)
            self.assertFalse(ok)
            self.assertIn('finished without a decision', diagnostic)
            self.assertNotIn('No such file', diagnostic)
            # The skeleton was already on disk when the command ran: that is the whole fix.
            self.assertEqual(seen['skeleton']['action'], 'incomplete')
            self.assertEqual(seen['skeleton']['repo'], 'unit/runtime')
            self.assertEqual(seen['skeleton']['issue_number'], 7)
            # And the file the reader finds is the same one, so the journal names the cause.
            self.assertEqual(json.loads(self.receipts(artifacts)[0].read_text(encoding='utf-8')),
                             seen['skeleton'])

    def test_a_finished_turn_replaces_the_skeleton_with_its_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, 'checkout')
            checkout(root)
            artifacts = Path(directory, 'artifacts')

            def execute(argv, **kwargs):
                report = document(root)
                report.update(worktree=str(root), base_sha='0' * 40, default_branch='main')
                receipt = self.receipts(artifacts)[0]
                receipt.write_text(json.dumps(report), encoding='utf-8')
                return worker.CommandResult(argv, kwargs['cwd'], 0, 'isolated mock Cline', '', 0)

            ok, recovered, diagnostic = supervisor.supervise(
                root, 'unit/runtime', 7, 'baseline', 'unit baseline error',
                worker.VerificationPlan(), artifacts, lambda *args: ['unit-cline'], execute,
                worker.VerificationPlan, worker.preserve_cline_edits)
            self.assertTrue(ok, diagnostic)
            self.assertEqual(json.loads(self.receipts(artifacts)[0].read_text(encoding='utf-8'))['action'],
                             'retry')

    def test_the_supervisor_prompt_does_not_read_a_reported_defect_as_a_blocker(self):
        """Measured 2026-11-01 (smallbets/userbase#305): the supervisor directive said an upstream
        product/test defect is a finding to record as BLOCKED_BASELINE, while the preparation
        directive says the same defect is the regression target. The two disagreed, and the
        stricter one won -- a bounty about a broken build was blocked as an environment fault."""
        prompt = supervisor_prompt_text()
        self.assertIn('A failure is not automatically a blocker either', prompt)
        self.assertIn('the failure IS the defect this issue', prompt)
        self.assertNotIn('An upstream product/test defect is a finding to record as BLOCKED_BASELINE',
                         prompt)
        self.assertIn('BLOCKED_BASELINE is for what no amount of engineering', prompt)


def supervisor_prompt_text():
    """The directive the repair turn actually reads, rendered for a known repair."""
    captured = {}

    def execute(argv, **kwargs):
        captured['prompt'] = argv[-1]
        return worker.CommandResult(argv, kwargs['cwd'], 1, 'no decision written', '', 0)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory, 'checkout')
        checkout(root)
        supervisor.supervise(root, 'unit/runtime', 7, 'baseline', 'unit baseline error',
                            worker.VerificationPlan(), Path(directory, 'artifacts'),
                            lambda cwd, prompt: ['unit-cline', prompt], execute,
                            worker.VerificationPlan, worker.preserve_cline_edits)
    return captured['prompt']


class UntouchedBaselineGuardTests(unittest.TestCase):
    """Provisioning's install may rewrite a tracked manifest; engineering's edit may not.

    Measured 2026-11-01, twice in one day: OpenOrg-gg/AmphoraProtocol#4 (run 41357319521) and
    Manthan-cpp/GramRaksha-AI#2 aborted seconds before engineering began because their bootstrap
    rewrote the tracked lockfile and the untouched-baseline gate read it as a mutated source.
    Cline had run the same install and verified `git status` clean itself, so the write belonged
    to provisioning -- whose checkout it is. The guard restores tracked files before it measures,
    and a change that survives that restore is a real one, named in the failure.
    """

    def fixture(self, directory):
        root = Path(directory, 'checkout')
        root.mkdir(parents=True)
        for args in (['init', '-q'], ['config', 'user.email', 'unit@example.invalid'],
                     ['config', 'user.name', 'Isolated unit fixture']):
            subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        (root / 'package-lock.json').write_text('{"lockfileVersion": 2}', encoding='utf-8')
        (root / 'package.json').write_text(json.dumps({'scripts': {'test': 'node --test'}}), encoding='utf-8')
        source = root / 'src'
        source.mkdir()
        (source / 'retry.js').write_text('module.exports = () => 0;\n', encoding='utf-8')
        # node_modules is ignored in every real checkout, which is why an install never showed
        # up in `git status` before and why the installed tree must survive the restore.
        (root / '.gitignore').write_text('node_modules/\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(root), 'add', 'package.json', 'package-lock.json',
                        '.gitignore', 'src/retry.js'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'unit fixture'], check=True, capture_output=True)
        modules = root / 'node_modules'
        (modules / 'left-pad').mkdir(parents=True)
        (modules / 'left-pad' / 'index.js').write_text('module.exports = 1;\n', encoding='utf-8')
        return root

    def provisioning_installs(self, root):
        """What npm 7+ leaves behind under `--no-save`: the lockfile rewritten and staged."""
        (root / 'package-lock.json').write_text('{"lockfileVersion": 3, "resolved": true}', encoding='utf-8')
        subprocess.run(['git', '-C', str(root), 'add', 'package-lock.json'], capture_output=True)
        # The dependency tree the install produced survives nothing else in this test.
        (root / 'node_modules' / 'left-pad' / 'package.json').write_text('{}', encoding='utf-8')

    def test_a_package_manager_lockfile_rewrite_is_not_engineering_edit(self):
        from actions_release import guard_untouched_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.provisioning_installs(root)
            self.assertEqual(guard_untouched_baseline(root), [])
            self.assertEqual((root / 'package-lock.json').read_text(encoding='utf-8'),
                             '{"lockfileVersion": 2}')
            self.assertTrue((root / 'node_modules' / 'left-pad' / 'index.js').is_file(),
                            'the installed tree must survive the restore')
            self.assertTrue((root / 'node_modules' / 'left-pad' / 'package.json').is_file())
            self.assertEqual(release_status(root), [], 'node_modules is ignored, not a change')

    def test_an_unstaged_staged_or_deleted_manifest_is_restored_either_way(self):
        from actions_release import guard_untouched_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            (root / 'package-lock.json').write_text('{"lockfileVersion": 4}', encoding='utf-8')
            self.assertEqual(guard_untouched_baseline(root), [])
            self.assertEqual((root / 'package-lock.json').read_text(encoding='utf-8'),
                             '{"lockfileVersion": 2}')
            subprocess.run(['git', '-C', str(root), 'add', 'package-lock.json'], capture_output=True)
            self.assertEqual(guard_untouched_baseline(root), [])
            (root / 'package-lock.json').unlink()
            self.assertEqual(guard_untouched_baseline(root), [])
            self.assertEqual((root / 'package-lock.json').read_text(encoding='utf-8'),
                             '{"lockfileVersion": 2}')

    def test_the_installed_tree_is_what_engineering_builds_on(self):
        """The restore must not take the dependencies with it: that is the whole point."""
        from actions_release import guard_untouched_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.provisioning_installs(root)
            guard_untouched_baseline(root)
            installed = root / 'node_modules' / 'left-pad'
            self.assertTrue((installed / 'index.js').is_file())
            self.assertTrue((installed / 'package.json').is_file())
            self.assertEqual((root / 'src' / 'retry.js').read_text(encoding='utf-8'),
                             'module.exports = () => 0;\n')

    def test_a_real_source_change_still_fails_and_names_the_path(self):
        """A change in the delivered tree is not provisioning's write, and it must refuse.

        The old gate answered every change with "Provisioning mutated the untouched source
        baseline", which sent the agent hunting for an install flag when the tree itself had
        moved. The two faults are now named apart: the message says which one it was.
        """
        from actions_release import guard_untouched_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            (root / 'src' / 'retry.js').write_text('module.exports = () => 1;\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Repository tree changed before engineering'):
                guard_untouched_baseline(root)
            with self.assertRaisesRegex(ValueError, 'src/retry.js'):
                guard_untouched_baseline(root)
            self.assertEqual((root / 'src' / 'retry.js').read_text(encoding='utf-8'),
                             'module.exports = () => 1;\n',
                             'a refused change is preserved for the diagnostic, not discarded')

    def test_an_unignored_file_left_by_a_build_still_fails_loudly(self):
        """Only ignored or untracked-by-design trees pass: a build that drops a file in the
        repository root is a change to the delivered tree, and the gate says which file."""
        from actions_release import guard_untouched_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            (root / 'generated-bundle.js').write_text('// build output\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'generated-bundle.js'):
                guard_untouched_baseline(root)


def release_status(root):
    """`git status --porcelain` for the fixture, normalised to path names."""
    result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1',
                             '--untracked-files=all'], capture_output=True, text=True, check=True)
    return sorted(line[3:] for line in result.stdout.splitlines() if line[3:])


if __name__ == '__main__':
    unittest.main(verbosity=2)
