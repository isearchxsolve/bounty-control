"""Drive the real dispatch() phase offline.

dispatch() is where duplicate-publication risk lives: it decides whether a
waiting task gets a delivery generation, and it must not create a second one on
replay. Before the store seam it could only be executed against a live
repository, so it sat at 0.0% line coverage.

These tests execute the production dispatch() body against a fake ledger and a
stubbed hydration call. The stub models the one behaviour dispatch() depends on:
hydration either dispatches the waiting task or does not.
"""
import argparse
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_pipeline_integration as live  # noqa: E402
from actions_github import task_id  # noqa: E402
from pipeline_evidence import bind_proof, source_revision  # noqa: E402

TARGET = 'isearchxsolve/oss-hunter-livefire'
CONTROL = 'isearchxsolve/bounty-control'
ISSUE = 5
IDENTITY = task_id(TARGET, ISSUE)


class FakeAPI:
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

    def pages(self, endpoint, **params):
        self.calls.append(('GET', endpoint))
        return self.table.get(endpoint, [])

    def workflow_runs(self, repo, status=None):
        self.calls.append(('GET', f'workflow_runs:{repo}:{status}'))
        return self.table.get(f'workflow_runs:{status}', [])

    def issue_context(self, repo, number):
        self.calls.append(('GET', f'issue_context:{repo}#{number}'))
        return self.table['issue_context']


class FakeStore:
    """A durable ledger that records what dispatch() did to it."""

    def __init__(self, state=None, sha='sha-0', records=()):
        self.state = state
        self.sha = sha
        self._records = list(records)
        self.reads = 0

    def read(self, identity):
        self.reads += 1
        return self.state, (self.sha if self.state else None)

    def records(self):
        return list(self._records)


def context_for(state='open', comments=2, archived=False):
    return {
        'repo': TARGET, 'issue_number': ISSUE, 'title': 'duration helper returns hours',
        'body': 'As repository owner I will pay $500 for this fix.',
        'issue': {'number': ISSUE, 'state': state, 'comments': comments, 'title': 'duration helper'},
        'repository': {'default_branch': 'main', 'archived': archived, 'disabled': False, 'size': 120},
        'comments': [{'id': 11, 'body': 'confirmed'}, {'id': 12, 'body': 'will pay'}][:comments],
        'author_comments': ['confirmed'], 'fetched_at': '2026-11-03T00:00:00Z',
        'complete_comments': True, 'comment_count_evidence': {}, 'base_branch': 'main',
    }


def admitted_row(context):
    return {'sovereign_admission': True,
            'admission': bind_proof({'amount': 500, 'currency': 'USD'}, context),
            'competition': {'blocking': False, 'verified': True, 'verdict': 'clear'}}


def api_for(context):
    return FakeAPI({
        'issue_context': context,
        f'repos/{TARGET}': context['repository'],
        f'repos/{TARGET}/issues/{ISSUE}': context['issue'],
        f'repos/{TARGET}/issues/{ISSUE}/comments': context['comments'],
        'workflow_runs:queued': [], 'workflow_runs:in_progress': [],
        'workflow_runs:waiting': [], 'workflow_runs:pending': [], 'workflow_runs:requested': [],
    })


class HydrationStub:
    """Stands in for sovereign_discovery.discover during dispatch()."""

    def __init__(self, store, dispatch=True, replay_dispatches=False, admission=None):
        self.store, self.dispatch, self.replay_dispatches = store, dispatch, replay_dispatches
        self.admission = admission
        self.calls = []

    def __call__(self, lanes, **kwargs):
        self.calls.append({'lanes': list(lanes), **kwargs})
        budget = kwargs.get('max_dispatches', 0)
        current = self.store.state or {}
        # A failed record is not a live generation: hydration replaces it.
        live_generation = current.get('dispatch_id') and not str(
            current.get('status', '')).startswith('FAILED')
        if budget and self.dispatch and not live_generation:
            self.store.state = {**current, 'status': 'DISPATCHED',
                                'dispatch_id': 'gen-1', 'admission': self.admission}
            self.store.sha = 'sha-1'
            return {'dispatched': [IDENTITY]}
        if self.replay_dispatches:
            self.store.state = {**self.store.state, 'dispatch_id': 'gen-2'}
            return {'dispatched': [IDENTITY]}
        return {'dispatched': []}


def args_for(folder, **overrides):
    values = dict(run_dir=Path(folder), target=TARGET, control=CONTROL, issue=ISSUE,
                  model_timeout=600, gateway='isolated', engineering_budget=1800,
                  wait_minutes=60, intake_max_age_minutes=90, merge_fixture=False)
    values.update(overrides)
    return argparse.Namespace(**values)


class DispatchPhaseOffline(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.context = context_for()

    def build(self, *, state=None, records=(), admitted=True, queue_dir=True, **stub):
        api = api_for(self.context)
        store = FakeStore(state=state, records=records)
        row = admitted_row(self.context)
        hydration = HydrationStub(store, admission=row['admission'], **stub)
        module = types.ModuleType('sovereign_discovery')
        module.discover = hydration
        self._previous = sys.modules.get('sovereign_discovery')
        sys.modules['sovereign_discovery'] = module
        run = live.LiveRun(args_for(self.folder), api=api, store=store)
        # task_id and issue are written by provision()/admit() in a real campaign.
        run.data.update(task_id=IDENTITY, issue=ISSUE)
        if admitted:
            run.data['admitted'] = row
        if queue_dir:
            run.data['queue_dir'] = str(Path(self.folder) / 'queue')
        run.save()
        return run, api, store, hydration

    def tearDown(self):
        if self._previous is None:
            sys.modules.pop('sovereign_discovery', None)
        else:
            sys.modules['sovereign_discovery'] = self._previous

    def test_a_waiting_task_gets_exactly_one_generation(self):
        run, _, store, hydration = self.build()
        run.dispatch()
        self.assertEqual(run.data['coverage']['REAL_REPOSITORY_DISPATCH'], 'PASS')
        self.assertEqual(run.data['dispatch_id'], 'gen-1')
        self.assertEqual(store.state['dispatch_id'], 'gen-1')

    def test_replay_does_not_create_a_second_generation(self):
        run, _, store, hydration = self.build()
        run.dispatch()
        self.assertEqual(run.data['coverage']['LIVE_QUEUE_REPLAY'], 'PASS')
        self.assertEqual(len(hydration.calls), 2, 'dispatch must hydrate once and replay once')
        self.assertEqual(store.state['dispatch_id'], 'gen-1')

    def test_handoff_and_replay_keep_every_production_entry_lane(self):
        run, _, _, hydration = self.build()
        run.dispatch()
        for call in hydration.calls:
            self.assertEqual(set(call['lanes']), {'startup', 'founder', 'normal', 'programs'})

    def test_hydration_is_asked_for_exactly_one_dispatch(self):
        run, _, _, hydration = self.build()
        run.dispatch()
        self.assertEqual(hydration.calls[0]['max_dispatches'], 1)
        self.assertTrue(hydration.calls[0]['hydrate_only'],
                        'dispatch must drain the queue, not re-run discovery search')

    def test_a_replay_that_dispatches_again_is_refused(self):
        run, _, _, _ = self.build(replay_dispatches=True)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('another delivery generation', str(caught.exception))

    def test_hydration_that_dispatches_nothing_is_refused(self):
        run, _, _, _ = self.build(dispatch=False)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('did not dispatch', str(caught.exception))

    def test_dispatch_without_admission_is_refused(self):
        run, _, _, hydration = self.build(admitted=False)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('Real admission required', str(caught.exception))
        self.assertEqual(hydration.calls, [], 'no admission must mean no hydration')

    def test_a_closed_campaign_is_refused(self):
        run, _, _, _ = self.build()
        run.data['closed'] = True
        run.save()
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('Campaign closed', str(caught.exception))

    def test_an_existing_generation_is_resumed_not_replaced(self):
        state = {'task_id': IDENTITY, 'status': 'ENGINEERING', 'dispatch_id': 'gen-existing',
                 'admission': admitted_row(self.context)['admission'],
                 'dispatched_at': '2026-11-02T00:00:00Z'}
        run, _, _, hydration = self.build(state=state)
        run.dispatch()
        self.assertEqual(run.data['dispatch_id'], 'gen-existing')
        # DISPATCH_RESUME is an observation, not a required acceptance case, so it lives in
        # the event log rather than the coverage map.
        self.assertIn('DISPATCH_RESUME', [event['case'] for event in run.data['events']])
        self.assertEqual(hydration.calls, [], 'a resume must not hydrate again')

    def test_an_existing_task_without_a_generation_is_refused(self):
        state = {'task_id': IDENTITY, 'status': 'ENGINEERING',
                 'admission': admitted_row(self.context)['admission']}
        run, _, _, _ = self.build(state=state)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('no delivery generation', str(caught.exception))

    def test_an_unrelated_existing_record_is_refused(self):
        state = {'task_id': IDENTITY, 'status': 'ENGINEERING', 'dispatch_id': 'gen-x',
                 'admission': {'task_id': 'f' * 32, 'source_revision': 'e' * 64}}
        run, _, _, _ = self.build(state=state)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('unrelated task record', str(caught.exception))

    def test_a_failed_record_is_replaced_rather_than_resumed(self):
        state = {'task_id': IDENTITY, 'status': 'FAILED_VERIFIED', 'dispatch_id': 'gen-old',
                 'admission': admitted_row(self.context)['admission']}
        run, _, store, _ = self.build(state=state)
        run.dispatch()
        self.assertEqual(run.data['dispatch_id'], 'gen-1', 'a failed generation must not be resumed')

    def test_a_full_fleet_defers_dispatch(self):
        reservations = [{'status': 'DISPATCHED'} for _ in range(4)]
        run, _, _, hydration = self.build(records=reservations)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('at capacity', str(caught.exception))
        self.assertEqual(hydration.calls, [], 'a full fleet must not hydrate')

    def test_corrupt_admission_evidence_is_refused_before_hydration(self):
        run, _, _, hydration = self.build()
        run.data['admitted']['admission']['source_revision'] = '0' * 64
        run.save()
        with self.assertRaises(ValueError) as caught:
            run.dispatch()
        self.assertIn('source changed', str(caught.exception))
        self.assertEqual(hydration.calls, [], 'unproven evidence must not reach hydration')

    def test_a_closed_issue_is_refused_before_hydration(self):
        self.context = context_for(state='closed')
        run, _, _, hydration = self.build()
        with self.assertRaises(ValueError) as caught:
            run.dispatch()
        self.assertIn('no longer open', str(caught.exception))
        self.assertEqual(hydration.calls, [])

    def test_a_missing_queue_is_refused(self):
        run, _, _, hydration = self.build(queue_dir=False)
        with self.assertRaises(AssertionError) as caught:
            run.dispatch()
        self.assertIn('queue is required', str(caught.exception))
        self.assertEqual(hydration.calls, [])


class LedgerSeamDefaultsToLive(unittest.TestCase):
    def test_omitting_the_store_seam_uses_real_github_storage(self):
        folder = tempfile.mkdtemp()
        run = live.LiveRun(args_for(folder))
        self.assertIsInstance(run.ledger(), live.StateStore)
        self.assertIsNone(run._store)


if __name__ == '__main__':
    unittest.main(verbosity=2)
