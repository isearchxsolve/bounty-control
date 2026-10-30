"""Scheduling regressions; isolated fixtures never represent live task receipts."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

import autonomous_icu_pipeline as dispatcher


class FreshDiscoveryScheduleTests(unittest.TestCase):
    def test_every_query_gets_a_fresh_window_before_any_full_backlog(self):
        schedule = list(dispatcher.discovery_query_schedule(['first', 'second', 'third'], 1000, 30))
        self.assertEqual(schedule[:3], [('fresh', q, 30) for q in ['first', 'second', 'third']])
        self.assertEqual(schedule[3:], [('backlog', q, 1000) for q in ['first', 'second', 'third']])

    def test_limits_empty_queries_and_disabled_mode(self):
        self.assertEqual(list(dispatcher.discovery_query_schedule([], 1000, 30)), [])
        self.assertEqual(list(dispatcher.discovery_query_schedule(['q'], 10, 30)), [('fresh', 'q', 10)])
        self.assertEqual(list(dispatcher.discovery_query_schedule(['q'], 30, 30)), [('fresh', 'q', 30)])
        self.assertEqual(list(dispatcher.discovery_query_schedule(['q'], 1000, 0)), [('backlog', 'q', 1000)])
        for horizon, fresh in [(0, 30), (1001, 30), (1000, -1), (1000, 1001)]:
            with self.subTest(horizon=horizon, fresh=fresh), self.assertRaises(ValueError):
                list(dispatcher.discovery_query_schedule(['q'], horizon, fresh))

    def test_cli_validates_the_explicit_fresh_setting(self):
        self.assertEqual(dispatcher.parse_pipeline_args([]).fresh_limit, 30)
        self.assertEqual(dispatcher.parse_pipeline_args(['--fresh-limit', '0']).fresh_limit, 0)
        for value in ['-1', '1001']:
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                dispatcher.parse_pipeline_args(['--fresh-limit', value])

    def test_live_cli_delegates_to_the_consolidated_dispatcher(self):
        """`--live` hands off to the consolidated dispatcher instead of running a cycle.

        `main()` reads: `if live_mode and not args.upgrade_existing: from actions_dispatch
        import main as actions_main; return actions_main(["--live", "--once" if args.once else
        "--daemon"])`. The earlier version of this test asserted a `run_pipeline_cycle` call
        that the consolidation removed, so it failed while the product was behaving correctly
        -- a stale contract, not a regression.
        """
        import actions_dispatch
        for argv, expected in ((['--once', '--live', '--anytime', '--fresh-limit', '7'],
                                ['--live', '--once']),
                               (['--live', '--anytime', '--fresh-limit', '7'],
                                ['--live', '--daemon'])):
            with self.subTest(argv=argv), \
                    patch.object(actions_dispatch, 'main', return_value=0) as consolidated, \
                    patch.object(dispatcher, 'run_pipeline_cycle') as cycle, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(dispatcher.main(argv), 0)
            consolidated.assert_called_once_with(expected)
            cycle.assert_not_called()

    def test_the_legacy_non_live_cycle_still_receives_the_explicit_settings(self):
        """The preview path is still reachable and still gets the same explicit arguments."""
        with patch.object(dispatcher, 'run_pipeline_cycle', return_value=None) as cycle, \
                redirect_stdout(io.StringIO()):
            self.assertIsNone(dispatcher.main(['--once', '--anytime', '--fresh-limit', '7']))
        cycle.assert_called_once_with(live_mode=False, anytime=True, search_limit=1000, fresh_limit=7)

    def run_isolated_cycle(self, fail_first_query=False):
        def candidate(number):
            return {'number': number, 'title': 'Repair concurrent executor deadlock',
                    'repository': {'nameWithOwner': 'unit/runtime'}, 'url': 'https://example.invalid/unit/' + str(number)}

        visited, fetched, dispatched = [], [], []

        def search(query, limit):
            visited.append((query, limit))
            if query == 'algora.io':
                if limit == 2:
                    return [] if fail_first_query else [candidate(1), candidate(2)]
                return [candidate(1), candidate(2), candidate(4), candidate(5)]
            if query == 'polar.sh':
                return [candidate(3), candidate(1)]
            return []

        def fetch(repo, number):
            fetched.append(number)
            body = 'We will pay $150 for the executor fix.'
            if number == 2:
                body = 'The executor deadlocks; no monetary offer has been made.'
            elif number == 5:
                body = 'We will pay $30 for the executor fix.'
            return {'state': 'OPEN', 'title': 'Repair concurrent executor deadlock', 'body': body,
                    'author': {'login': 'maintainer'}, 'authorAssociation': 'MEMBER',
                    'labels': [], 'author_comments': []}

        with ExitStack() as stack:
            stack.enter_context(patch.object(dispatcher, 'verify_delivery_database_integrity', return_value={'integrity': 'ok', 'rows': 0}))
            for name in ['init_db', 'sync_fleet_results_to_local_db']:
                stack.enter_context(patch.object(dispatcher, name))
            stack.enter_context(patch.object(dispatcher, 'is_issue_claimed_or_delivered', side_effect=lambda repo, n: (repo != 'unit/runtime', None)))
            stack.enter_context(patch.object(dispatcher, 'search_issues', side_effect=search))
            stack.enter_context(patch.object(dispatcher, 'get_issue_fast', side_effect=fetch))
            stack.enter_context(patch.object(dispatcher, 'get_author_profile', return_value={}))
            stack.enter_context(patch.object(dispatcher, 'detect_author_corridor', return_value=('Global', True, 'Global')))
            stack.enter_context(patch.object(dispatcher, 'post_grounded_proposal', side_effect=lambda repo, n, *args, **kwargs: dispatched.append(n) or True))
            stack.enter_context(patch.object(dispatcher.time, 'sleep'))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            # The actual eligibility and $50 floor gates execute unchanged.
            dispatcher.run_pipeline_cycle(live_mode=True, anytime=True, search_limit=1000, fresh_limit=2)
        return visited, fetched, dispatched, output.getvalue()

    def test_fresh_candidates_precede_deep_work_without_retriaging_duplicates(self):
        visited, fetched, dispatched, output = self.run_isolated_cycle()
        first_backlog = next(i for i, (_, limit) in enumerate(visited) if limit == 1000)
        self.assertEqual(first_backlog, len(visited) // 2)
        self.assertTrue(all(limit == 2 for _, limit in visited[:first_backlog]))
        self.assertEqual(dispatched, [1, 3, 4])
        self.assertCountEqual(fetched, [1, 2, 3, 4, 5])
        self.assertEqual(fetched.count(1), 1)
        self.assertIn('[DISCOVERY_PASS_COMPLETE] phase=fresh', output)
        self.assertLess(output.index('phase=fresh'), output.index('phase=backlog'))

    def test_empty_or_failed_first_query_does_not_starve_other_fresh_queries(self):
        _, fetched, dispatched, _ = self.run_isolated_cycle(fail_first_query=True)
        self.assertEqual(dispatched, [3, 1, 4])
        self.assertEqual(fetched.count(1), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
