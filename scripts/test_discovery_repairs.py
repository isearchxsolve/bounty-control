"""Isolated regression checks for discovery, integrity, and native manifests."""
from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import autonomous_icu_pipeline as dispatcher
import kaggle_engine_worker as worker
from fleet_recovery_policy import RECOVERY_RELEASE, recovery_decision


def issue(number=7, **changes):
    record = {
        'number': number, 'title': 'Concurrent executor deadlock',
        'body': 'Reproduction: two concurrent jobs stop making progress.',
        'repository': {'nameWithOwner': 'product/runtime'},
        'labels': [{'name': 'bounty'}], 'author': {'login': 'maintainer'},
        'authorAssociation': 'MEMBER', 'commentsCount': 1,
        'createdAt': '2026-10-20T00:00:00Z',
    }
    record.update(changes)
    return record


class DiscoveryRepairTests(unittest.TestCase):
    def test_python_verification_installs_declared_plugins_before_unchanged_test_command(self):
        for module in (dispatcher, worker):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                project = Path(directory, 'pyproject.toml')
                project.write_text('[project]\nname="unit-project"\nversion="0.0.1"\n[project.optional-dependencies]\ndev=["pytest-cov>=6"]\n[tool.pytest.ini_options]\naddopts="--cov=unit_project --cov-fail-under=80"\n')
                original = project.read_bytes()
                plan = module.discover_verification_plan(module.inspect_repository_architecture(directory), directory)
                self.assertEqual(plan.bootstrap[0], [module.sys.executable, '-m', 'pip', 'install', '-e', '.[dev]'])
                self.assertEqual(plan.baseline_tests, [[module.sys.executable, '-m', 'pytest']])
                self.assertEqual(plan.final_tests, plan.baseline_tests)
                self.assertEqual(project.read_bytes(), original)
                project.write_text('[tool.ruff]\nline-length=100\n')
                Path(directory, 'requirements-dev.txt').write_text('pytest-cov>=6\n')
                plan = module.discover_verification_plan(module.inspect_repository_architecture(directory), directory)
                self.assertEqual(plan.bootstrap, [[module.sys.executable, '-m', 'pip', 'install', '-r', 'requirements-dev.txt']])

    def test_go_bootstrap_requires_verified_archive_runtime_and_formatter(self):
        archive_bytes = b'unit-test archive bytes, never a live release receipt'
        real_open = open
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory, 'download.tar.gz')
            archive.write_bytes(archive_bytes)

            def open_archive(path, *args, **kwargs):
                self.assertTrue(str(path).endswith('.tar.gz'))
                return real_open(archive, *args, **kwargs)

            def command(argv, **kwargs):
                stdout = f'go version go{worker.GO_VERSION} linux/amd64\n' if argv[-1] == 'version' else ''
                return subprocess.CompletedProcess(argv, 0, stdout, '')

            with patch.object(worker.os.path, 'isfile', return_value=False), \
                 patch.object(worker, '_download_init_file') as download, \
                 patch('builtins.open', side_effect=open_archive), \
                 patch.object(worker.os, 'makedirs'), \
                 patch.object(worker, 'GO_SHA256', hashlib.sha256(archive_bytes).hexdigest()), \
                 patch.object(worker.subprocess, 'run', side_effect=command) as commands, \
                 patch.dict(os.environ), redirect_stdout(io.StringIO()):
                worker.ensure_supported_go()
                self.assertTrue(download.call_args.args[0].startswith('https://go.dev/dl/'))
                self.assertEqual([os.path.basename(call.args[0][0]) for call in commands.call_args_list], ['tar', 'go', 'gofmt'])
                self.assertEqual(os.environ['GOROOT'], f'/tmp/fleet-go-{worker.GO_VERSION}')

            with patch.object(worker.os.path, 'isfile', return_value=False), \
                 patch.object(worker, '_download_init_file'), \
                 patch('builtins.open', side_effect=open_archive), \
                 patch.object(worker, 'GO_SHA256', '0' * 64), \
                 patch.object(worker.subprocess, 'run') as commands:
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    worker.ensure_supported_go()
                commands.assert_not_called()

            with patch.object(worker.os.path, 'isfile', return_value=True), \
                 patch.object(worker, '_download_init_file') as download, \
                 patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'broken')):
                with self.assertRaisesRegex(RuntimeError, 'runtime verification failed'):
                    worker.ensure_supported_go()
                download.assert_not_called()

    def test_comment_funded_issue_survives_search_but_requires_real_funding_gate(self):
        candidate = issue()
        with patch.object(dispatcher, 'run_cmd', return_value=(json.dumps([candidate]), '', 0)):
            self.assertEqual(dispatcher.search_issues('--label bounty'), [candidate])
        args = (candidate['title'], candidate['body'], [], candidate['labels'], 'product/runtime')
        self.assertFalse(dispatcher.verify_genuine_icu_patient(
            *args, author_assoc='MEMBER', author='maintainer', live_delivery_mode=True)[0])
        self.assertTrue(dispatcher.verify_genuine_icu_patient(
            candidate['title'], candidate['body'],
            ['Algora bounty: $150 funded at https://algora.io/product/bounties/7'],
            candidate['labels'], 'product/runtime', author_assoc='MEMBER',
            author='maintainer', live_delivery_mode=True)[0])

    def test_early_filter_excludes_mirrors_bots_and_banking_collection(self):
        candidates = [
            issue(1, repository={'nameWithOwner': 'mirror/gh-disc-123-runtime'}),
            issue(2, author={'login': 'app/example', 'is_bot': True}),
            issue(3, title='Banking transcripts, $10 each'),
            issue(4),
        ]
        with patch.object(dispatcher, 'run_cmd', return_value=(json.dumps(candidates), '', 0)):
            self.assertEqual([r['number'] for r in dispatcher.search_issues('--label bounty')], [4])

    def test_grouped_query_preserved_and_cli_labels_still_work(self):
        with patch.object(dispatcher, 'run_cmd', return_value=('[]', '', 0)) as command:
            dispatcher.search_issues('bounty "race condition"')
            argv = command.call_args.args[0]
            self.assertEqual(argv[3], 'bounty "race condition"')
            self.assertEqual(argv[argv.index('--limit') + 1], '1000')
            dispatcher.search_issues('--label bounty')
            self.assertEqual(command.call_args.args[0][3:5], ['--label', 'bounty'])

    def test_cli_rejects_silent_unknown_flags_and_invalid_search_limits(self):
        self.assertEqual(dispatcher.parse_pipeline_args([]).search_limit, 1000)
        self.assertTrue(dispatcher.parse_pipeline_args(['--24x7']).anytime)
        for argv in [['--all-lanes'], ['--search-limit', '0'], ['--search-limit', '1001']]:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    dispatcher.parse_pipeline_args(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_integrity_check_does_not_create_or_mutate_delivery_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deliveries.sqlite3'
            self.assertEqual(dispatcher.verify_delivery_database_integrity(path)['integrity'], 'new database')
            self.assertFalse(path.exists())
            dispatcher.init_db(path)
            self.assertTrue(dispatcher.try_claim_issue('product/runtime', 7, 'Deadlock', 'maintainer', 'Global', 'funded', db_path=path))
            self.assertEqual(dispatcher.verify_delivery_database_integrity(path), {'integrity': 'ok', 'rows': 1})
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT status FROM deliveries').fetchone()[0], 'CLAIMED')
            invalid = Path(directory) / 'invalid.sqlite3'
            invalid.write_bytes(b'This is intentionally not a SQLite database.')
            with self.assertRaises(sqlite3.DatabaseError):
                dispatcher.verify_delivery_database_integrity(invalid)

    def test_cycle_retrieves_full_depth_and_triages_each_issue_once(self):
        candidates = [issue(7), issue(8)]
        live = {'state': 'OPEN', 'title': 'Executor deadlock', 'body': 'We will pay $150 USDC to fix this deadlock.',
                'author': {'login': 'maintainer'}, 'authorAssociation': 'MEMBER',
                'author_comments': [], 'labels': [{'name': 'bounty'}]}
        with patch.object(dispatcher, 'verify_delivery_database_integrity', return_value={'integrity': 'ok', 'rows': 0}), \
             patch.object(dispatcher, 'init_db'), patch.object(dispatcher, 'sync_fleet_results_to_local_db'), \
             patch.object(dispatcher, 'is_issue_claimed_or_delivered', side_effect=lambda repo, number: (repo != 'product/runtime', None)), \
             patch.object(dispatcher, 'search_issues', return_value=candidates) as search, \
             patch.object(dispatcher, 'get_issue_fast', return_value=live) as fetch, \
             patch.object(dispatcher, 'get_author_profile', return_value={}), \
             patch.object(dispatcher, 'detect_author_corridor', return_value=('Global', True, 'Global')) as corridor, \
             patch.object(dispatcher, 'post_grounded_proposal', return_value=True) as dispatch, \
             patch.object(dispatcher.time, 'sleep'), redirect_stdout(io.StringIO()):
            dispatcher.run_pipeline_cycle(live_mode=True, anytime=True)
        self.assertGreater(search.call_count, 1)
        self.assertTrue(all(call.kwargs['limit'] == 1000 for call in search.call_args_list))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(corridor.call_count, 1)

    def test_unavailable_competition_lookup_does_not_permanently_blacklist_issue(self):
        with patch.object(dispatcher, 'is_issue_claimed_or_delivered', return_value=(False, None)), \
             patch.object(dispatcher, 'verify_genuine_icu_patient', return_value=(True, 'funded')), \
             patch.object(dispatcher, 'has_existing_open_pr', return_value=(True, 'GitHub PR query failed: timeout')), \
             patch.object(dispatcher, 'mark_issue_rejected') as reject, \
             patch.object(dispatcher, 'dispatch_task_to_fleet') as enqueue, redirect_stdout(io.StringIO()):
            self.assertFalse(dispatcher.post_grounded_proposal('product/runtime', 7, 'Deadlock', 'maintainer', '', '', [], [], 'funded', 'Global', live_mode=True))
        reject.assert_not_called()
        enqueue.assert_not_called()

    def test_nested_product_rust_workspace_retains_native_test_and_lint_gates(self):
        for module in (dispatcher, worker):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                for relative in ['compiler/Cargo.toml', 'examples/Cargo.toml']:
                    path = Path(directory, relative)
                    path.parent.mkdir()
                    path.write_text('[workspace]\nmembers = []\n')
                arch = module.inspect_repository_architecture(directory)
                self.assertEqual(arch['rust_manifest'], 'compiler/Cargo.toml')
                plan = module.discover_verification_plan(arch, directory)
                self.assertIn(['cargo', 'test', '--manifest-path', 'compiler/Cargo.toml', '--workspace'], plan.baseline_tests)
                self.assertEqual(plan.baseline_tests, plan.final_tests)
                self.assertIn('--manifest-path', plan.linters[0])
                self.assertEqual(plan.linters[0][-3:], ['--', '-D', 'warnings'])

    def test_ambiguous_or_example_only_manifests_do_not_invent_verification(self):
        for module in (dispatcher, worker):
            for children in [['examples'], ['compiler', 'server']]:
                with self.subTest(module=module.__name__, children=children), tempfile.TemporaryDirectory() as directory:
                    for child in children:
                        path = Path(directory, child, 'Cargo.toml')
                        path.parent.mkdir()
                        path.write_text('[workspace]\nmembers = []\n')
                    arch = module.inspect_repository_architecture(directory)
                    self.assertEqual(arch['ecosystem'], 'unknown')
                    self.assertEqual(module.discover_verification_plan(arch, directory).baseline_tests, [])

    def test_native_workspace_retry_requires_scoped_fresh_authorization(self):
        task = {'task_id': 'unit-workspace', 'repo': 'product/compiler', 'issue_number': 7}
        failure = {'at': 1, 'text': 'FAILED engine verification plan: FAILED_NO_TEST_VERIFICATION: no native test commands were discovered for the worktree. for product/compiler#7 attempt=1'}
        authorization = {'at': 2, 'text': f'RECOVERY_AUTHORIZED unit-workspace for product/compiler#7 release={RECOVERY_RELEASE} repair=nested-rust-workspace manifest=compiler/Cargo.toml attempt_limit=2'}
        self.assertFalse(recovery_decision(task, [], [failure], now=1000).allowed)
        decision = recovery_decision(task, [authorization], [failure], now=1000)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.attempt, 2)
        for wrong in [
            authorization['text'].replace('product/compiler#7', 'product/compiler#8').replace('unit-workspace', 'other-task'),
            authorization['text'].replace(RECOVERY_RELEASE, 'old-release'),
            authorization['text'].replace('compiler/Cargo.toml', '../Cargo.toml'),
            authorization['text'].replace('attempt_limit=2', 'attempt_limit=99'),
        ]:
            self.assertFalse(recovery_decision(task, [{'at': 2, 'text': wrong}], [failure], now=1000).allowed)
        claim = {'at': 3, 'text': 'CLAIMED unit-workspace by engine for product/compiler#7 attempt=2 run=second lease_until=2000'}
        self.assertEqual(recovery_decision(task, [authorization, claim], [failure], now=1000).reason, 'active claim lease')
        self.assertFalse(recovery_decision(task, [authorization, claim], [failure], now=3000).allowed)
        second_failure = dict(failure, at=4, text=failure['text'].replace('attempt=1', 'attempt=2'))
        self.assertFalse(recovery_decision(task, [authorization, claim], [failure, second_failure], now=3000).allowed)
        security = dict(failure, text=failure['text'] + ' Security violation')
        self.assertFalse(recovery_decision(task, [authorization], [security], now=1000).allowed)

    def test_repository_rust_pin_is_installed_and_used_without_sourcing_host_paths(self):
        for module in (dispatcher, worker):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                manifest = Path(directory, 'compiler', 'Cargo.toml')
                manifest.parent.mkdir()
                manifest.write_text('[workspace]\nmembers=[]\n')
                env = Path(directory, 'tools', 'env.sh')
                env.parent.mkdir()
                marker = Path(directory, 'must-not-be-created')
                env.write_text(f'touch "{marker}"\nexport RUSTUP_HOME="/home/z/.rustup"\nexport PINNED_RUST="1.99.0" # repository pin\n')
                arch = module.inspect_repository_architecture(directory)
                self.assertEqual(arch['rust_toolchain'], '1.99.0')
                plan = module.discover_verification_plan(arch, directory)
                self.assertEqual(plan.bootstrap[0][:4], ['rustup', 'toolchain', 'install', '1.99.0'])
                self.assertEqual(plan.baseline_tests[0][:3], ['cargo', '+1.99.0', 'test'])
                self.assertEqual(plan.linters[0][:3], ['cargo', '+1.99.0', 'clippy'])
                self.assertFalse(marker.exists())
                env.write_text('export PINNED_RUST="1.99.0; touch unexpected"\n')
                self.assertNotIn('rust_toolchain', module.inspect_repository_architecture(directory))

    def test_provider_startup_retries_throttling_but_keeps_auth_failures_closed(self):
        with patch.object(worker, 'configure_cline_for_engine', return_value=(True, 'configured')) as configure, \
             patch.object(worker, 'verify_cline_provider_wire', side_effect=[(False, 'TokenHarbor router HTTP 429'), (True, 'tool round trip verified')]) as verify, \
             patch.object(worker.time, 'sleep') as sleep, patch.object(worker, 'door_say'), patch.object(worker, '_command_log'):
            self.assertTrue(worker.initialize_cline_for_engine()[0])
        configure.assert_called_once()
        self.assertEqual(verify.call_count, 2)
        sleep.assert_called_once_with(30)
        with patch.object(worker, 'configure_cline_for_engine', return_value=(False, 'Cline provider readback failed')), \
             patch.object(worker, 'verify_cline_provider_wire') as verify:
            self.assertFalse(worker.initialize_cline_for_engine()[0])
        verify.assert_not_called()
        with patch.object(worker, 'configure_cline_for_engine', return_value=(True, 'configured')), \
             patch.object(worker, 'verify_cline_provider_wire', return_value=(False, 're-authenticate your Cline account HTTP 401')) as verify, \
             patch.object(worker.time, 'sleep') as sleep:
            self.assertFalse(worker.initialize_cline_for_engine()[0])
        self.assertEqual(verify.call_count, 1)
        sleep.assert_not_called()

    def test_provider_startup_exhaustion_is_bounded(self):
        with patch.object(worker, 'configure_cline_for_engine', return_value=(True, 'configured')), \
             patch.object(worker, 'verify_cline_provider_wire', return_value=(False, 'TokenHarbor router HTTP 429')) as verify, \
             patch.object(worker.time, 'sleep') as sleep, patch.object(worker, 'door_say'), patch.object(worker, '_command_log'):
            self.assertFalse(worker.initialize_cline_for_engine()[0])
        self.assertEqual(verify.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 60])

    def test_pin_drift_retry_is_scoped_and_cannot_grant_a_fourth_attempt(self):
        task = {'task_id': 'unit-pin', 'repo': 'product/compiler', 'issue_number': 7}
        native = {'at': 1, 'text': 'FAILED engine verification plan: FAILED_NO_TEST_VERIFICATION: no native test commands were discovered for the worktree. for product/compiler#7 attempt=1'}
        pin = {'at': 3, 'text': 'FAILED engine untouched upstream baseline: Bootstrap command failed: cargo check --manifest-path compiler/Cargo.toml --workspace | error: failed to run custom build command for `hyb v0.0.1` for product/compiler#7 attempt=2'}
        authorization = {'at': 4, 'text': f'RECOVERY_AUTHORIZED unit-pin for product/compiler#7 release={RECOVERY_RELEASE} repair=pinned-rust-toolchain manifest=compiler/Cargo.toml toolchain=1.99.0 attempt_limit=3'}
        self.assertFalse(recovery_decision(task, [], [native, pin], now=10000).allowed)
        allowed = recovery_decision(task, [authorization], [native, pin], now=10000)
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.attempt, 3)
        for wrong in [authorization['text'].replace('toolchain=1.99.0', 'toolchain=unknown'), authorization['text'].replace('pinned-rust-toolchain', 'nested-rust-workspace')]:
            self.assertFalse(recovery_decision(task, [{'at': 4, 'text': wrong}], [native, pin], now=10000).allowed)
        final = dict(pin, at=6, text=pin['text'].replace('attempt=2', 'attempt=3'))
        self.assertFalse(recovery_decision(task, [authorization], [native, pin, final], now=10000).allowed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
