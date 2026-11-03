"""Real dependency providers for the original lease suite; assertions stay there.

Rows are isolated fault inputs. Run observations come from actual Actions runs.
No unrelated Actions run may be cancelled by these probes.
"""
from datetime import datetime, timezone
import os
import uuid

from actions_github import GitHub, StateStore, task_id
from unittest import SkipTest


CONTROL = os.environ.get('LIVE_PROBE_CONTROL', 'isearchxsolve/bounty-control')


class LeaseAPI(GitHub):
    def __init__(self, runs=None, fail=False):
        super().__init__(token='invalid-live-lease-probe' if fail else None)
        self.calls = []
        self.aliases = {}
        for alias, requested in (runs or {}).items():
            created = requested.get('created_at')
            if requested.get('status') != 'completed' and created and (datetime.now(timezone.utc) - datetime.fromisoformat(
                    created.replace('Z', '+00:00'))).total_seconds() > 18000:
                raise SkipTest('BLOCKED: needs a dedicated real overdue cancellable Actions run; unrelated runs are never cancelled')
            status = requested.get('status', 'in_progress')
            result = GitHub().api(f'repos/{CONTROL}/actions/runs?status={status}&per_page=20')
            matches = [run for run in result['workflow_runs'] if run['status'] == status]
            if not matches:
                raise SkipTest(f'BLOCKED: no real {status} Actions owner is available')
            self.aliases[str(alias)] = str(matches[0]['id'])
            print(f'Lease fixture owner {alias} -> {matches[0]["html_url"]} '
                  f'(observed {matches[0]["status"]})', flush=True)

    def api(self, endpoint, method='GET', data=None, **kwargs):
        self.calls.append((method, endpoint))
        if method != 'GET':
            raise SkipTest('BLOCKED: a dedicated real cancellation fixture is required')
        endpoint = endpoint.replace('repos/unit/runtime/', f'repos/{CONTROL}/')
        for alias, actual in self.aliases.items():
            prefix = '/actions/runs/' + alias
            if endpoint.endswith(prefix) or prefix + '/' in endpoint:
                endpoint = endpoint.replace(prefix, '/actions/runs/' + actual, 1)
                break
        return super().api(endpoint, method, data, **kwargs)


class LeaseStore(StateStore):
    def __init__(self, rows, api=None):
        super().__init__(api=api or GitHub(), repo=CONTROL)
        self.branch = 'live-probes/lease-' + uuid.uuid4().hex
        self.ensure()
        self.identities = []
        for row in rows:
            identity = row['task_id']
            self.identities.append(identity)
            self.mutate(identity, lambda old, row=row: dict(row))
        print('Retained lease fault branch: ' + self.branch, flush=True)

    @property
    def rows(self):
        return [self.read(identity)[0] for identity in self.identities]


def claimable(api, current):
    row = {**current, 'task_id': task_id('unit/runtime', 7), 'fault_fixture': True}
    # Storage uses authenticated transport; owner observations use the real probe API.
    store = LeaseStore([row])
    # StateStore uses its one client for both persistence and owner observations.
    # Route only owner requests through the selected real owner provider.
    class BoundAPI(GitHub):
        def api(self, endpoint, method='GET', data=None, **kwargs):
            if '/actions/runs/' in endpoint:
                return api.api(endpoint, method, data, **kwargs)
            return super().api(endpoint, method, data, **kwargs)
    store.api = BoundAPI()
    return store
