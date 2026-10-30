"""Isolated regression fixtures; live receipts are recorded separately."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import autonomous_icu_pipeline as dispatcher
from discovery_horizon import Horizon


class DispatcherHorizonTests(unittest.TestCase):
    def test_real_command_boundary_preserves_phrases_without_quoting_whole_query(self):
        with patch.object(dispatcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[]', '')) as run:
            dispatcher.run_cmd(['gh', 'search', 'issues', 'bounty "race condition"', '--limit', '30'])
        self.assertEqual(run.call_args.args[0][1:], ['search', 'issues', 'bounty', 'race condition', '--limit', '30'])

    def test_quoted_debate_amount_is_not_an_offer_even_from_owner(self):
        allowed, reason = dispatcher.verify_genuine_icu_patient(
            'Discuss payment liability', 'The systems should work.\n> Users will pay $10,000 for shopping.',
            [], [], 'owner/runtime', author='owner', author_assoc='OWNER', live_delivery_mode=True)
        self.assertFalse(allowed, reason)

    def test_maintainer_bounty_banner_can_use_markdown_blockquote(self):
        allowed, reason = dispatcher.verify_genuine_icu_patient(
            'End-to-end pipeline test', '> **BOUNTY — $50 USD**\nAdd an end-to-end regression test.',
            [], [{'name': 'bounty'}], 'unit/runtime', author='maintainer',
            author_assoc='MEMBER', live_delivery_mode=True)
        self.assertTrue(allowed, reason)

    def test_partition_splits_without_gaps_and_resumes_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'horizon.db')
            horizon = Horizon(path)
            root = horizon.window('global', now=1200000000)
            self.assertEqual(horizon.complete('global', root, 1000, 1000), 'split')
            first = Horizon(path).window('global')
            self.assertEqual(first[1], root[1])
            horizon.complete('global', first, 4, 1000)
            second = horizon.window('global')
            self.assertEqual(first[2] + 1, second[1])
            self.assertEqual(second[2], root[2])
            self.assertEqual(horizon.window('global'), second)  # failure does not advance

    def test_unpartitionable_second_is_reported_saturated(self):
        with tempfile.TemporaryDirectory() as folder:
            horizon = Horizon(Path(folder, 'horizon.db'))
            root = horizon.window('global', now=1199145600)  # 2008-01-01 UTC
            self.assertEqual(horizon.complete('global', root, 1000, 1000), 'saturated')

    def search_fixture(self, item, hydrated=None, query='bounty in:title'):
        with ExitStack() as stack:
            command = stack.enter_context(patch.object(dispatcher, 'run_cmd', return_value=(json.dumps([item]), '', 0)))
            stack.enter_context(patch.object(dispatcher, 'get_issue_fast', return_value=hydrated))
            stack.enter_context(patch.object(dispatcher, 'detect_author_corridor', return_value=('Global', True, 'Global')))
            stack.enter_context(patch.object(dispatcher, 'evaluate_custom_query_gates', return_value=(True, 'OK')))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = dispatcher.search_issues(query, limit=30)
        return result, command.call_args_list[0].args[0]

    @staticmethod
    def candidate(**changes):
        item = dict(number=7, title='Fix executor deadlock', body='We will pay $150 USDC to fix the deadlock.',
                    repository={'nameWithOwner': 'unit/runtime'}, author={'login': 'reporter'},
                    labels=[], commentsCount=15, createdAt='2019-01-01T00:00:00Z')
        item.update(changes)
        return item

    def test_old_discussed_assigned_issues_are_not_excluded_by_proxy(self):
        result, argv = self.search_fixture(self.candidate())
        self.assertEqual(len(result), 1)
        self.assertNotIn('--no-assignee', argv)
        self.assertNotIn('--comments', argv)
        query = argv[argv.index('--internal-search-query') + 1]
        self.assertIn('is:public', query)
        self.assertIn('archived:false', query)
        self.assertIn('-label:type/experiment', query)

    def test_unlabelled_comment_funding_and_authority_survive(self):
        data = dict(state='OPEN', authorAssociation='CONTRIBUTOR', payerAssociation='MEMBER',
                    author_comments=['We will pay $150 USDC to fix this deadlock.'])
        result, _ = self.search_fixture(self.candidate(body='Executor deadlock reproduction.'), data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['payerAssociation'], 'MEMBER')

    def test_small_bounty_and_unfunded_hydrated_issue_still_rejected(self):
        self.assertEqual(self.search_fixture(self.candidate(body='We will pay $10 USDC for this fix.'))[0], [])
        data = dict(state='OPEN', authorAssociation='CONTRIBUTOR', author_comments=['Can anyone fix this?'])
        self.assertEqual(self.search_fixture(self.candidate(body='Deadlock reproduction.'), data)[0], [])

    def test_live_dispatch_floor_is_enforced_before_candidate_leaves_search(self):
        below = self.candidate(body='We will pay $49 USDC to fix the deadlock.')
        at_floor = self.candidate(body='We will pay $50 USDC to fix the deadlock.',
                                  authorAssociation='MEMBER', author={'login': 'maintainer'})
        self.assertEqual(self.search_fixture(below)[0], [])
        self.assertEqual(len(self.search_fixture(at_floor)[0]), 1)

    def test_explicit_qualifier_and_global_query_lanes_preserved(self):
        _, argv = self.search_fixture(self.candidate(), query='comments:>2 bounty')
        query = argv[argv.index('--internal-search-query') + 1]
        self.assertIn('comments:>2 bounty', query)
        self.assertIn('-label:type/experiment', query)
        self.assertIn('bounty in:title', dispatcher.DYNAMIC_DISCOVERY_QUERIES)
        self.assertIn('"will pay"', dispatcher.DYNAMIC_DISCOVERY_QUERIES)
        self.assertIn('--label bounty', dispatcher.DYNAMIC_DISCOVERY_QUERIES)

    def test_persisted_full_horizon_partition_reaches_rest_search_query(self):
        window = ('global', 1_000_000, 1_001_000)
        with ExitStack() as stack:
            run = stack.enter_context(patch.object(
                dispatcher, 'run_cmd', return_value=('[]', '', 0)))
            horizon = stack.enter_context(patch.object(dispatcher, 'DISCOVERY_HORIZON'))
            horizon.window.return_value = window
            horizon.qualifier.return_value = '2026-01-01..2026-01-02'
            horizon.complete.return_value = 'split'
            stack.enter_context(redirect_stdout(io.StringIO()))
            dispatcher.search_issues('bounty', limit=1000)
        argv = run.call_args.args[0]
        query = argv[argv.index('--internal-search-query') + 1]
        self.assertIn('created:2026-01-01..2026-01-02', query)
        self.assertIn('-label:type/experiment', query)

    def test_rest_maintainer_offer_not_reporter_affiliation_sets_payer(self):
        issue = dict(author={'login': 'reporter'}, comments=[{'author': {'login': 'maintainer'}, 'body': '/bounty $150'}])
        rest = [[dict(user={'login': 'maintainer'}, body='/bounty $150', author_association='MEMBER')]]
        with patch.object(dispatcher, 'run_cmd', side_effect=[(json.dumps(issue), '', 0), ('CONTRIBUTOR', '', 0), (json.dumps(rest), '', 0)]):
            data = dispatcher.get_issue_fast('unit/runtime', 7)
        self.assertEqual(data['payerAssociation'], 'MEMBER')
        self.assertEqual(data['authorAssociation'], 'CONTRIBUTOR')

    def test_reporter_pool_and_severity_titles_are_not_live_payer_authority(self):
        for body in ['Bounty Pool: Stage 1 Bug Bounty ($3,000 USD Pool). Settlement Wallet: 0x123.',
                     'Severity: High ($150 to $400 USDC). Settlement Wallet: 0x123.']:
            with self.subTest(body=body):
                allowed, reason = dispatcher.verify_genuine_icu_patient(
                    '[BOUNTY] Medium: executor precision bug', body, [], [],
                    'unit/runtime', author='reporter', author_assoc='NONE', live_delivery_mode=True)
                self.assertFalse(allowed, reason)

    def test_live_tier_cannot_manufacture_an_amount(self):
        allowed, reason = dispatcher.verify_genuine_icu_patient(
            '[BOUNTY] High: executor deadlock', 'Please fix this deadlock.', [], [],
            'unit/runtime', author='maintainer', author_assoc='MEMBER', live_delivery_mode=True)
        self.assertFalse(allowed, reason)

    def test_tool_installation_is_clines_decision_not_a_search_language_ban(self):
        allowed, reason = dispatcher.verify_genuine_icu_patient(
            'Fix a Flutter plugin regression', 'We will pay $300 USDC for a tested fix.',
            [], [], 'unit/runtime', author='maintainer', author_assoc='MEMBER', live_delivery_mode=True)
        self.assertTrue(allowed, reason)

    def test_platform_demo_instructions_do_not_turn_software_work_into_marketing(self):
        allowed, reason = dispatcher.verify_genuine_icu_patient(
            'Implement a backend integration', 'Build an app that invokes the service.',
            ['Algora bounty: $300 funded at https://algora.io/unit/bounties/7. '
             'Submit a demo video as proof of the implementation.'],
            [], 'unit/runtime', author='maintainer', author_assoc='MEMBER', live_delivery_mode=True)
        self.assertTrue(allowed, reason)


if __name__ == '__main__':
    unittest.main(verbosity=2)
