"""Drive real driver phases offline through the injection seam.

Before the seam, every phase was unreachable without a live repository, so
``live_pipeline_integration.py`` sat at 14.3% line coverage with every phase at
0.0%. These tests execute the production phase methods against a fake API and a
fake command runner, so the phase logic itself is exercised rather than the
contracts wrapped around it.

The fake is a fact table, not a behaviour model: it answers the exact endpoints
the phase asks for and records what was asked. A phase that invents an endpoint
fails loudly instead of silently passing.
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_pipeline_integration as live  # noqa: E402


class FakeAPI:
    """Answers a fixed endpoint table and records every call."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def api(self, endpoint, method='GET', payload=None):
        self.calls.append((method, endpoint))
        if endpoint not in self.table:
            raise AssertionError('phase requested an endpoint the fake does not model: ' + endpoint)
        answer = self.table[endpoint]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeCommand:
    def __init__(self, stdout='', returncode=0, stderr=''):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls = []

    def __call__(self, argv, *, env=None, timeout=120):
        self.calls.append(argv)
        return self.stdout


def sandbox_table(**overrides):
    """A healthy sandbox target and an active control repository."""
    target = {
        'default_branch': 'main', 'archived': False, 'disabled': False,
        'description': 'Disposable sandbox for live pipeline acceptance',
        'permissions': {'admin': True, 'push': True, 'pull': True},
        'has_pull_requests': True, 'pull_request_creation_policy': 'all',
        'has_issues': True,
    }
    target.update(overrides.pop('target', {}))
    table = {
        'user': {'login': 'isearchxsolve'},
        'repos/isearchxsolve/oss-hunter-livefire': target,
        'repos/isearchxsolve/bounty-control': {'default_branch': 'main'},
        'repos/isearchxsolve/bounty-control/commits/main': {'sha': 'a' * 40},
        'repos/isearchxsolve/bounty-control/actions/workflows/engine2.yml': {
            'state': 'active', 'html_url': 'https://example.invalid/engine2.yml'},
    }
    table.update(overrides)
    return table


def args_for(folder, **overrides):
    values = dict(run_dir=Path(folder), target='isearchxsolve/oss-hunter-livefire',
                  control='isearchxsolve/bounty-control', issue=None, model_timeout=600,
                  gateway='isolated', engineering_budget=1800, wait_minutes=60,
                  intake_max_age_minutes=90, merge_fixture=False)
    values.update(overrides)
    return argparse.Namespace(**values)


class PreflightPhaseOffline(unittest.TestCase):
    """The real preflight() body, executed end to end without a network."""

    def run_preflight(self, table=None, command=None, **arg_overrides):
        folder = tempfile.mkdtemp()
        api = FakeAPI(table if table is not None else sandbox_table())
        cmd = command if command is not None else FakeCommand(stdout='b' * 40 + '\n')
        run = live.LiveRun(args_for(folder, **arg_overrides), api=api, command=cmd)
        run.preflight()
        return run, api, cmd

    def test_a_healthy_sandbox_passes_and_records_environment(self):
        run, api, cmd = self.run_preflight()
        self.assertEqual(run.data['coverage']['ENVIRONMENT'], 'PASS')
        self.assertEqual(run.data['account'], 'isearchxsolve')
        self.assertEqual(run.data['base_branch'], 'main')
        self.assertEqual(run.data['control_branch'], 'main')
        self.assertEqual(run.data['deployed_sha'], 'a' * 40)
        self.assertEqual(run.data['local_sha'], 'b' * 40)

    def test_preflight_actually_asks_the_deployment_endpoints(self):
        _, api, _ = self.run_preflight()
        endpoints = [endpoint for _, endpoint in api.calls]
        self.assertIn('repos/isearchxsolve/bounty-control/commits/main', endpoints)
        self.assertIn('repos/isearchxsolve/bounty-control/actions/workflows/engine2.yml', endpoints)

    def test_publication_access_is_observed_not_assumed(self):
        run, _, _ = self.run_preflight()
        cases = [event['case'] for event in run.data['events']]
        self.assertIn('PUBLICATION_ACCESS', cases)

    def test_an_archived_sandbox_is_refused(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_preflight(sandbox_table(target={'archived': True}))
        self.assertIn('unavailable', str(caught.exception).lower())

    def test_a_non_sandbox_target_is_refused(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_preflight(sandbox_table(target={'description': 'Real production service'}))
        self.assertIn('sandbox', str(caught.exception).lower())

    def test_a_target_owned_by_another_account_is_refused(self):
        table = sandbox_table()
        table['repos/someoneelse/oss-hunter-livefire'] = table['repos/isearchxsolve/oss-hunter-livefire']
        with self.assertRaises(AssertionError) as caught:
            self.run_preflight(table, target='someoneelse/oss-hunter-livefire')
        self.assertIn('authenticated account', str(caught.exception))

    def test_an_inactive_delivery_workflow_is_refused(self):
        table = sandbox_table()
        table['repos/isearchxsolve/bounty-control/actions/workflows/engine2.yml'] = {'state': 'disabled_manually'}
        with self.assertRaises(AssertionError) as caught:
            self.run_preflight(table)
        self.assertIn('inactive', str(caught.exception).lower())

    def test_a_collaborator_only_target_without_push_is_refused(self):
        # The exact 2026-11-03 blocker on fiztoz/uptime-phoenix#198: admin on the
        # sandbox path is satisfied, but PR creation is collaborator-only and the
        # publisher holds no push permission, so no PR can ever be opened.
        with self.assertRaises(AssertionError) as caught:
            self.run_preflight(sandbox_table(target={
                'pull_request_creation_policy': 'collaborators_only',
                'permissions': {'admin': True, 'push': False, 'pull': True}}))
        self.assertIn('collaborators', str(caught.exception).lower())

    def test_a_deployment_change_mid_campaign_is_refused(self):
        folder = tempfile.mkdtemp()
        api = FakeAPI(sandbox_table())
        run = live.LiveRun(args_for(folder), api=api, command=FakeCommand(stdout='b' * 40))
        run.data['deployed_sha'] = 'c' * 40
        run.save()
        with self.assertRaises(AssertionError) as caught:
            run.preflight()
        self.assertIn('Deployment changed', str(caught.exception))

    def test_the_local_head_comes_from_the_command_seam(self):
        cmd = FakeCommand(stdout='d' * 40 + '\n')
        run, _, _ = self.run_preflight(command=cmd)
        self.assertEqual(run.data['local_sha'], 'd' * 40)
        self.assertEqual(cmd.calls[0][:3], ['git', 'rev-parse', 'HEAD'])


class SeamDefaultsToOneLivePath(unittest.TestCase):
    """The seam must not change production behaviour when nothing is injected."""

    def test_omitting_the_seam_still_constructs_the_real_github_client(self):
        folder = tempfile.mkdtemp()
        run = live.LiveRun(args_for(folder))
        self.assertIsInstance(run.api, live.GitHub)
        self.assertIsNone(run._command)

    def test_a_journal_from_another_target_is_refused(self):
        folder = tempfile.mkdtemp()
        live.LiveRun(args_for(folder), api=FakeAPI(sandbox_table()))
        journal = Path(folder) / 'run.json'
        data = json.loads(journal.read_text())
        data['target'] = 'other/repo'
        journal.write_text(json.dumps(data))
        with self.assertRaises(AssertionError) as caught:
            live.LiveRun(args_for(folder), api=FakeAPI(sandbox_table()))
        self.assertIn('different target', str(caught.exception))


if __name__ == '__main__':
    unittest.main(verbosity=2)
