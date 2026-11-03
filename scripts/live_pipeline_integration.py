"""Live GitHub/Cline/Actions integration driver. No mock transports or invented success.

Each command resumes a durable local run journal. Mutations are confined to an
explicit sandbox target, this run's issues/PRs, and a separate fault-test branch.
The delivery itself uses the deployed production engine2.yml and durable store.
"""
import argparse
import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode

from actions_github import GitHub, GitHubError, StateStore, repository, task_id
from pipeline_evidence import require_evidence

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_LANES = ('startup', 'founder', 'normal', 'programs')
REQUIRED_CASES = (
    'ENVIRONMENT', 'LIVE_INTAKE', 'LIVE_MODEL_ADMISSION', 'LIVE_QUEUE_DEFERRAL',
    'LIVE_SOURCE_REJECTIONS', 'LIVE_QUEUE_RECOVERY', 'LIVE_QUEUE_REPLAY',
    'REAL_REPOSITORY_DISPATCH', 'REAL_INVALID_GENERATION', 'ACTIONS_TERMINAL',
    'REAL_PUBLICATION', 'ACTUAL_RELEASE_POSITIVE_CONTROL', 'MERGE_AND_RECONCILE_REPLAY',
    'LIVE_STATE_ROUNDTRIP', 'LIVE_CAS_CONFLICT', 'LIVE_CONCURRENT_CLAIM',
    'LIVE_CLAIM_REPLAY', 'LIVE_STALE_GENERATION', 'LIVE_WRONG_OWNER',
    'LIVE_REVOKED_OWNER', 'LIVE_RETRY_CAP', 'LIVE_TRUNCATED_STATE',
    'LIVE_GITHUB_401', 'LIVE_GITHUB_404',
    'LIVE_RELEASE_TASK_IDENTITY', 'LIVE_RELEASE_HEAD', 'LIVE_RELEASE_TREE',
    'LIVE_RELEASE_FILE_MANIFEST', 'LIVE_RELEASE_NATIVE_RECEIPTS_MISSING',
    'LIVE_RELEASE_REGRESSION_NEVER_RED', 'LIVE_RELEASE_REGRESSION_NOT_GREEN',
    'LIVE_FAILURE_SURFACE',
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def retained_admissions(queue, api):
    """Recheck actual queued admissions left by an interrupted entry session."""
    database = Path(queue) / 'agent-queue.sqlite3'
    if not database.exists():
        return []
    with contextlib.closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        rows = con.execute("SELECT task_id,payload FROM decisions WHERE disposition='capacity_wait'").fetchall()
    valid = []
    for identity, payload in rows:
        row = json.loads(payload)
        try:
            context = api.issue_context(row['repo'], row['issue'])
            require_evidence(row, context)
            check(identity == task_id(row['repo'], row['issue']), 'Queued task identity mismatch')
        except (ValueError, AssertionError):
            continue
        valid.append(identity)
    return valid


def delivery_harness(run, state, expected, *, continuation=False):
    """Bind a repaired generation to its actual Actions owner, never ambient HEAD."""
    actual = run['head_sha']
    if actual != expected:
        check(continuation, 'Deployed harness changed since preflight')
        check(re.fullmatch(r'[0-9a-f]{40}', actual), 'Invalid delivery harness SHA')
        check(state.get('harness_sha') == actual, 'Claim and Actions harness differ')
        check(state.get('owner') == f'{run["id"]}:{run["run_attempt"]}', 'Claim and Actions owner differ')
        check(state.get('run_url') == run['html_url'], 'Claim and Actions execution differ')
    return actual


def drain_evidence(folder, run):
    """Validate actual hydrated queue artifacts, including cache freshness."""
    census = json.loads((folder / 'census.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    check(census.get('door_reason') == 'HYDRATE_ONLY', 'Hydration did not run the production agent-queue path')
    started = datetime.fromisoformat(run['run_started_at'].replace('Z', '+00:00'))
    check(datetime.fromisoformat(census['at'].replace('Z', '+00:00')) >= started,
          'Hydration receipt is inherited stale cache evidence')
    with contextlib.closing(sqlite3.connect((folder / 'agent-queue.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)) as con:
        rows = con.execute("SELECT at FROM decisions WHERE disposition IN ('capacity_wait','deferred','received')").fetchall()
    check(all(datetime.fromisoformat(at.replace('Z', '+00:00')) >= started for (at,) in rows),
          'Hydration left pending rows unexamined')
    return census


FAILURE_PREFIXES = ('FAILED_', 'REJECTED_')
CAUSE_KEYS = ('diagnostic', 'error', 'reason', 'detail', 'message', 'error_summary')
HISTORY_KEYS = ('failures', 'failure_history', 'history')
RUN_FAILURE_CONCLUSIONS = ('failure', 'timed_out', 'startup_failure')


def failure_kind(status):
    """Classify the status token only: FAILED_ is a fault, REJECTED_ is a verdict."""
    text = str(status or '')
    for prefix in FAILURE_PREFIXES:
        if text.startswith(prefix):
            return ('failure' if prefix == 'FAILED_' else 'refusal'), (text[len(prefix):].lower() or 'unknown')
    return None, None


def recorded_cause(row):
    """The cause the record itself carries, or None. It is never an invented explanation."""
    for key in CAUSE_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in HISTORY_KEYS:
        history = row.get(key)
        if not isinstance(history, list):
            continue
        for entry in reversed(history):
            if isinstance(entry, dict):
                for inner in CAUSE_KEYS:
                    value = entry.get(inner)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            elif isinstance(entry, str) and entry.strip():
                return entry.strip()
    return None


class ScopedStore(StateStore):
    """Real GitHub storage, restricting reconciliation to this run's task IDs."""
    def __init__(self, api, repo, identities):
        super().__init__(api=api, repo=repo)
        self.identities = identities

    def records(self):
        for identity in self.identities:
            row, _ = self.read(identity)
            if row:
                yield row


class LiveRun:
    def __init__(self, args, *, api=None, command=None, store=None):
        """``api``, ``command`` and ``store`` are injection seams, not test hooks in production.

        Every phase drives real remote state through ``self.api``, shells out through
        ``self.command`` and reads the durable ledger through ``self.ledger()``. With all
        three hard-wired, the only way to execute a phase was a live repository, which is
        why the driver sat at 14.3% line coverage with every phase at 0.0%: the contracts
        around the driver were tested and the driver itself was not. Defaults are unchanged,
        so a live campaign behaves exactly as before.
        """
        self.args = args
        self.folder = args.run_dir.resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "run.json"
        self.api = api if api is not None else GitHub()
        self._command = command
        self._store = store
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            "id": "r" + uuid.uuid4().hex[:12], "target": repository(args.target),
            "control": repository(args.control), "started_at": self.now(),
            "events": [], "end_to_end_passed": False,
            "not_exercised": ["provider-wide outage/429", "runner OOM/disk-full",
                              "cross-account review changes", "payment settlement",
                              "process death at every publication boundary",
                              "unrestricted scheduled discovery",
                              "automatic scheduler execution during an outage"]}
        check(self.data.get('mode') != 'ORIGINAL_READ_ONLY',
              'Legacy audit journal: use a fresh run directory with the master suite')
        check(self.data["target"] == args.target and self.data["control"] == args.control,
              "Run directory belongs to a different target/control pair")
        self.target, self.control = self.data["target"], self.data["control"]
        if args.issue is not None:
            check(args.issue > 0, 'Issue number must be positive')
            check(not self.data.get('issue') or self.data['issue'] == args.issue, 'Run journal names another issue')
            self.data['existing_issue'] = args.issue
        self.save()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def save(self):
        latest = {event['case']: event['status'] for event in self.data['events']}
        self.data['coverage'] = {case: latest.get(case, 'NOT_RUN') for case in REQUIRED_CASES}
        if any(status != 'PASS' for status in self.data['coverage'].values()):
            self.data['end_to_end_passed'] = False
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def record(self, case, status, **evidence):
        if status in ('FAIL', 'PENDING', 'INCOMPLETE'):
            self.data['end_to_end_passed'] = False
        # Collapse an identical repeat. A poll loop re-records the same terminal verdict every
        # 20s -- measured 2026-11-03, run 41588321800 wrote 15 identical ACTIONS_TERMINAL FAIL
        # rows for one failed delivery, and the run before wrote 8 PIPELINE_MEMBER FAIL rows for
        # one cause. Fixing that per call site only moved it (the dedupe held for PIPELINE_MEMBER
        # and the repeats reappeared one case over), so the rule lives here instead: an event is
        # dropped only when it repeats the previous event's case, status and diagnostic exactly.
        # Every real transition still lands, and the count is kept on the event so a repeated
        # verdict stays visible as a fact (`repeats`) rather than vanishing.
        previous = self.data['events'][-1] if self.data['events'] else None
        if (previous and previous.get('case') == case and previous.get('status') == status
                and previous.get('diagnostic') == evidence.get('diagnostic')):
            previous['repeats'] = previous.get('repeats', 1) + 1
            previous['last_at'] = self.now()
            self.save()
            self.publish_progress()
            return
        event = {"case": case, "status": status, "at": self.now(), **evidence}
        self.data["events"].append(event)
        self.save()
        print(json.dumps(event), flush=True)
        self.publish_progress()

    def publish_progress(self, *, force=False):
        """Expose factual stage receipts while Actions' unfinished logs are unavailable."""
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        if (os.environ.get('LIVE_PIPELINE_PROGRESS') != '1' or not run_id.isdecimal()
                or self.args.issue is not None):
            return
        latest = self.data['events'][-1] if self.data['events'] else {}
        signature = (latest.get('case'), latest.get('status'))
        if (not force and signature == getattr(self, '_progress_signature', None)
                and time.monotonic() < getattr(self, '_progress_next', 0)):
            return
        self._progress_next = time.monotonic() + 30
        attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
        if not attempt.isdecimal():
            return
        path = f'live-integration/{run_id}-{attempt}.json'
        store = StateStore(self.api, self.control)
        # Only allowlisted status facts travel here, never prompts, model logs,
        # environment, task bodies or arbitrary diagnostic text.
        progress = {'at': self.now(), 'run_url': f'https://github.com/{self.control}/actions/runs/{run_id}',
                    'end_to_end_passed': self.data['end_to_end_passed'],
                    'coverage': dict(self.data['coverage']),
                    'events': [{key: event.get(key) for key in ('case', 'status', 'at')}
                               for event in self.data['events'][-15:]],
                    'cohort': {identity: {key: member.get(key) for key in ('repo', 'issue', 'state')}
                               for identity, member in self.data.get('cohort', {}).items()}}
        try:
            current = getattr(self, '_progress_sha', None)
            if current is None:
                try:
                    current = self.api.api(f'repos/{self.control}/contents/{path}?ref={store.branch}')['sha']
                except GitHubError as exc:
                    if '404' not in str(exc):
                        raise
            body = {'message': f'live integration progress {run_id}', 'branch': store.branch,
                    'content': base64.b64encode(json.dumps(progress, indent=2).encode()).decode()}
            if current:
                body['sha'] = current
            result = self.api.api(f'repos/{self.control}/contents/{path}', 'PUT', body)
            self._progress_sha = result['content']['sha']
            self._progress_signature = signature
        except (GitHubError, KeyError, TypeError, OSError):
            self._progress_sha = None
            print(json.dumps({'phase': 'LIVE_PROGRESS_UNAVAILABLE', 'run_id': run_id}), flush=True)

    def recent_runs(self):
        """Complete pagination bounded to this campaign's real creation window."""
        rows, page = [], 1
        while True:
            query = urlencode({'created': '>=' + self.data.get('run_search_since', self.data['started_at']), 'per_page': 100, 'page': page})
            batch = self.api.api(f'repos/{self.control}/actions/workflows/engine2.yml/runs?{query}')['workflow_runs']
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1

    def ledger(self):
        """The durable ledger for this run: the injected one in a test, real GitHub otherwise."""
        return self._store if self._store is not None else StateStore(self.api, self.control)

    def command(self, argv, *, env=None, timeout=120):
        if self._command is not None:
            return self._command(argv, env=env, timeout=timeout)
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        check(result.returncode == 0, f"Command {argv[0:3]} failed ({result.returncode}): {result.stderr[-1500:]}")
        return result.stdout

    def preflight(self, *, require_publication=True):
        user = self.api.api("user")
        target = self.api.api(f"repos/{self.target}")
        if not self.data.get('existing_issue'):
            check(self.target.split('/')[0].lower() == user['login'].lower(), "Sandbox must be owned by authenticated account")
            check(target.get('permissions', {}).get('admin'), "Sandbox admin permission required")
            check('sandbox' in (target.get('description') or '').lower(), "Target must explicitly identify itself as a sandbox")
        check(not target['archived'] and not target.get('disabled'), "Sandbox unavailable")
        self.record('PUBLICATION_ACCESS', 'OBSERVED', repository=self.target,
                    has_pull_requests=target.get('has_pull_requests'),
                    pull_request_creation_policy=target.get('pull_request_creation_policy'),
                    viewer_permissions=target.get('permissions'))
        publication_errors = []
        if target.get('has_pull_requests') is False:
            publication_errors.append('Target has disabled pull request creation')
        if (target.get('pull_request_creation_policy') == 'collaborators_only'
                and target.get('permissions', {}).get('push') is False):
            publication_errors.append('Target restricts PR creation to collaborators; publisher has no write access')
        workflow = self.api.api(f"repos/{self.control}/actions/workflows/engine2.yml")
        check(workflow['state'] == 'active', "Production delivery workflow inactive")
        control = self.api.api(f"repos/{self.control}")
        deployed = self.api.api(f"repos/{self.control}/commits/{control['default_branch']}")['sha']
        local = self.command(['git', 'rev-parse', 'HEAD']).strip()
        check(not self.data.get('deployed_sha') or self.data['deployed_sha'] == deployed,
              'Deployment changed during campaign; retain this report and start a new campaign')
        self.data.update(account=user['login'], base_branch=target['default_branch'],
                         control_branch=control['default_branch'],
                         deployed_sha=deployed, local_sha=local)
        self.record('ENVIRONMENT', 'PASS', login=user['login'], deployed_sha=deployed,
                    local_sha=local, workflow=workflow['html_url'], issues_enabled=target['has_issues'])
        if require_publication:
            check(not publication_errors, '; '.join(publication_errors))

    @staticmethod
    def age_seconds(run):
        return (datetime.now(timezone.utc)
                - datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00'))).total_seconds()

    def discovery_runs(self, *, status=None, per_page=20):
        query = f'?per_page={per_page}' + (f'&status={status}' if status else '')
        return self.api.api(f'repos/{self.control}/actions/workflows/bounty-discovery.yml/runs{query}')['workflow_runs']

    def discovery_cadence(self):
        """How often scheduled discovery actually fires, in hours. A platform fact, not a gate."""
        scheduled = [r for r in self.discovery_runs(per_page=100) if r.get('event') == 'schedule']
        if len(scheduled) < 2:
            return {'scheduled_runs_sampled': len(scheduled), 'observed_interval_hours': None}
        stamps = sorted(datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')) for r in scheduled)
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(stamps, stamps[1:])]
        return {'scheduled_runs_sampled': len(scheduled),
                'youngest_scheduled_age_hours': round((datetime.now(timezone.utc) - stamps[-1]).total_seconds() / 3600, 2),
                'observed_interval_hours': round(sum(gaps) / len(gaps), 2),
                'interval_min_hours': round(min(gaps), 2), 'interval_max_hours': round(max(gaps), 2)}

    def ensure_discovery_receipt(self):
        """Cause a fresh completed discovery run instead of sampling a throttled cron.

        The campaign needs a completed discovery run inside the freshness deadline to read real
        intake receipts. Waiting for the scheduler to supply one is a race against GitHub's cron
        throttle, measured 2026-11-03: `bounty-discovery` is declared `7,37 * * * *` (every 30
        minutes) but its scheduled runs actually fired every 5-7 hours, while each run itself
        takes ~63 minutes. The freshness window therefore existed for roughly 85 minutes in every
        5-7 hours, so LIVE_INTAKE flipped PASS at 05:13 and FAIL at 06:11 in the same campaign
        with no code change -- and each flip read as a pipeline defect.

        So the suite dispatches the real production workflow and waits for it, which is the same
        power it already uses for hydration. Freshness is then owed by construction and the
        receipts it reads are still this pipeline's own. Nothing about liveness is weakened:
        workflow state, a registered schedule, the recovery heartbeat, the hydration drain and the
        run's own conclusion are all still checked, and a failed discovery run still fails intake.
        A run that is already in flight is waited for rather than doubled, because the production
        workflow holds a `bounty-discovery` concurrency group and a second dispatch would queue
        behind the first. If that in-flight run overruns the deadline, the failure names the run
        and its elapsed time: that is a real, actionable fact, not a hidden freshness miss.
        """
        budget = self.args.intake_max_age_minutes * 60
        deadline = time.monotonic() + budget
        dispatched = self.data.get('discovery_dispatch')
        while True:
            completed = [r for r in self.discovery_runs(status='completed') if r.get('conclusion')]
            fresh = [r for r in completed if self.age_seconds(r) <= budget]
            if fresh:
                return fresh[0]
            running = (self.discovery_runs(status='in_progress')
                       + self.discovery_runs(status='queued') + self.discovery_runs(status='pending'))
            if not running and not dispatched:
                self.command(['gh', 'workflow', 'run', 'bounty-discovery.yml', '--repo', self.control,
                              '--ref', 'main'], timeout=120)
                dispatched = self.data['discovery_dispatch'] = {
                    'at': self.now(),
                    'reason': 'no completed discovery run inside the freshness deadline',
                    'previous_run': completed[0].get('html_url') if completed else None,
                    'previous_age_minutes': (round(self.age_seconds(completed[0]) / 60, 1)
                                             if completed else None)}
                self.save()
                self.record('LIVE_DISCOVERY_DISPATCH', 'OBSERVED', **dispatched)
                continue
            if time.monotonic() >= deadline:
                if running:
                    newest = running[0]
                    elapsed = (datetime.now(timezone.utc)
                               - datetime.fromisoformat(newest['created_at'].replace('Z', '+00:00'))).total_seconds() / 60
                    detail = f"discovery run {newest['html_url']} has been {newest['status']} for {round(elapsed, 1)} minutes"
                elif completed:
                    detail = (f"youngest completed discovery run {completed[0]['html_url']} is "
                              f"{round(self.age_seconds(completed[0]) / 60, 1)} minutes old and the dispatch did not land")
                else:
                    detail = 'no discovery run exists and the dispatch did not land'
                raise AssertionError(f'No discovery receipt inside the {self.args.intake_max_age_minutes}-minute '
                                     f'freshness deadline: {detail}. Cancel or repair that run; the campaign '
                                     'cannot read intake receipts while the production discovery queue is blocked.')
            time.sleep(20)

    def intake(self):
        """Inspect deployed intake wiring and actual discovery queue receipts."""
        import yaml

        self.data.update(intake_passed=False, end_to_end_passed=False)
        self.save()
        observations = {'discovery_cadence': self.discovery_cadence()}
        for name in ('bounty-discovery.yml', 'bounty-hydration.yml', 'discovery-heartbeat.yml'):
            workflow = self.api.api(f'repos/{self.control}/actions/workflows/{name}')
            source = self.api.api(f'repos/{self.control}/contents/.github/workflows/{name}')
            document = yaml.load(base64.b64decode(source['content']), Loader=yaml.BaseLoader)
            observations[name] = {
                'state': workflow['state'], 'source_sha': source['sha'],
                'schedule': document.get('on', {}).get('schedule', []),
            }
        run = self.ensure_discovery_receipt()
        age = self.age_seconds(run)
        destination = self.folder / ('intake-' + str(run['id']))
        destination.mkdir(exist_ok=True)
        if not list(destination.rglob('agent-queue.sqlite3')):
            self.command(['gh', 'run', 'download', str(run['id']), '--repo', self.control,
                          '--name', 'discovery-' + str(run['id']), '--dir', str(destination)], timeout=180)
        queues = list(destination.rglob('agent-queue.sqlite3'))
        check(len(queues) == 1, 'Actual discovery queue receipt missing or ambiguous')
        with contextlib.closing(sqlite3.connect(queues[0].resolve().as_uri() + '?mode=ro', uri=True)) as con:
            counts = dict(con.execute('SELECT disposition,count(*) FROM decisions GROUP BY disposition'))
        censuses = list(destination.rglob('census.jsonl'))
        check(len(censuses) == 1, 'Actual discovery census missing or ambiguous')
        lines = censuses[0].read_text(encoding='utf-8').splitlines()
        check(lines, 'Discovery census is empty')
        latest = json.loads(lines[-1])
        failures = []
        discovery = observations['bounty-discovery.yml']
        hydration = observations['bounty-hydration.yml']
        if discovery['state'] != 'active' or not discovery['schedule']:
            failures.append('Automatic discovery is inactive or unscheduled')
        heartbeat = observations['discovery-heartbeat.yml']
        if heartbeat['state'] != 'active' or not heartbeat['schedule']:
            failures.append('Discovery scheduler recovery heartbeat is inactive or unscheduled')
        if age > self.args.intake_max_age_minutes * 60:
            failures.append('Latest completed discovery exceeds the configured freshness deadline')
        if run['conclusion'] != 'success':
            failures.append('Latest real discovery execution failed')
        # The deployed sovereign discovery branch only replays cached decisions in
        # hydrate_only mode. Its dedicated workflow must therefore run automatically.
        if counts.get('capacity_wait', 0) and (hydration['state'] != 'active' or not hydration['schedule']):
            failures.append('Capacity-wait backlog has no scheduled hydration drain')
        # A registered cron is not proof that it runs, reads the right queue,
        # or restores the cached backlog. Inspect the actual workflow artifact.
        drains = self.api.api(f'repos/{self.control}/actions/workflows/bounty-hydration.yml/runs?status=completed&per_page=1')['workflow_runs']
        pending = sum(counts.get(k, 0) for k in ('capacity_wait', 'deferred', 'received'))
        if pending and not drains:
            failures.append('Pending backlog has no completed hydration execution')
        if pending and drains:
            drain = drains[0]
            drain_age = (datetime.now(timezone.utc) - datetime.fromisoformat(drain['updated_at'].replace('Z', '+00:00'))).total_seconds()
            if drain['conclusion'] != 'success' or drain_age > self.args.intake_max_age_minutes * 60:
                failures.append('Backlog drain execution is failed or stale')
            else:
                try:
                    destination = self.folder / ('hydration-' + str(drain['id']))
                    destination.mkdir(exist_ok=True)
                    if not (destination / 'census.jsonl').is_file():
                        self.command(['gh', 'run', 'download', str(drain['id']), '--repo', self.control,
                                      '--name', 'hydration-' + str(drain['id']), '--dir', str(destination)], timeout=180)
                    census = drain_evidence(destination, drain)
                    observations['hydration_execution'] = {'run': drain['html_url'], 'census': census}
                except (AssertionError, OSError, ValueError, KeyError, IndexError, sqlite3.Error) as exc:
                    failures.append('Hydration evidence invalid: ' + str(exc))
        self.record('LIVE_INTAKE', 'FAIL' if failures else 'PASS', run=run['html_url'],
                    age_seconds=age, workflows=observations, queue=counts,
                    census=latest, failures=failures)
        check(not failures, '; '.join(failures))
        self.data['intake_passed'] = True
        self.save()

    def provision(self):
        if self.data.get('existing_issue'):
            number = self.data['existing_issue']
            context = self.api.issue_context(self.target, number)
            check(context['issue']['state'] == 'open', 'Original issue is not open')
            self.data.update(issue=number, issue_url=context['issue']['html_url'], task_id=task_id(self.target, number))
            self.save()
            self.preflight()
            self.record('FIXTURE', 'PASS', issue=self.data['issue_url'], existing_original=True,
                        created_or_modified=False)
            return
        self.preflight()
        check(not self.data.get('issue'), "Fixture already exists; resume admit/dispatch/observe")
        if self.data.get('issue_title'):
            # Recover a real accepted create with a lost client acknowledgement.
            found = [r for r in self.api.pages(f'repos/{self.target}/issues', state='all')
                     if not r.get('pull_request') and r['title'] == self.data['issue_title']
                     and r['user']['login'] == self.data['account']]
            check(len(found) <= 1, 'Multiple matching fixture issues; inspect before proceeding')
            if found:
                issue = found[0]
                self.data.update(issue=issue['number'], issue_url=issue['html_url'],
                                 task_id=task_id(self.target, issue['number']))
                self.record('FIXTURE_RECOVERED', 'PASS', issue=issue['html_url'])
                return
        prefix = 'live_cases/' + self.data['id']
        source = 'def days_to_seconds(days):\n    """Convert a nonnegative integer number of days into seconds."""\n    if isinstance(days, bool) or not isinstance(days, int) or days < 0:\n        raise ValueError("days must be a nonnegative integer")\n    return days * 3600\n'
        baseline = f'import unittest\nfrom live_cases.{self.data["id"]}.duration import days_to_seconds\n\nclass Baseline(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(days_to_seconds(0), 0)\n    def test_negative(self):\n        with self.assertRaises(ValueError):\n            days_to_seconds(-1)\n'
        ci = "name: Live fixture native checks\n'on':\n  pull_request: {}\n  workflow_dispatch: {}\npermissions:\n  contents: read\njobs:\n  native:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n    - uses: actions/checkout@v4\n    - run: python3 -m unittest discover -s live_cases -p 'test_*.py' -v\n"
        files = {'live_cases/__init__.py': '', prefix + '/__init__.py': '',
                 prefix + '/duration.py': source, prefix + '/test_baseline.py': baseline,
                 '.github/workflows/live-integration-fixture.yml': ci}
        branch = self.data['base_branch']
        parent = self.api.api(f'repos/{self.target}/commits/{branch}')
        tree = self.api.api(f'repos/{self.target}/git/trees', 'POST', {
            'base_tree': parent['commit']['tree']['sha'], 'tree': [
                {'path': path, 'mode': '100644', 'type': 'blob', 'content': content}
                for path, content in files.items()]})
        commit = self.api.api(f'repos/{self.target}/git/commits', 'POST', {
            'message': f'Live integration fixture {self.data["id"]}',
            'tree': tree['sha'], 'parents': [parent['sha']]})
        self.data.update(fixture_commit=commit['sha'], source_path=prefix + '/duration.py')
        self.save()  # retain objects if a later write fails
        self.api.api(f'repos/{self.target}/git/refs/heads/{branch}', 'PATCH', {'sha': commit['sha'], 'force': False})
        self.api.api(f'repos/{self.target}', 'PATCH', {'has_issues': True})
        body = (f'Live integration test {self.data["id"]}; explicitly authorized sandbox work, not a paid bounty.\n\n'
                f'As repository owner I request a fix for {prefix}/duration.py. '
                'days_to_seconds(1) returns 3600, but one day has 86400 seconds. '
                'Correct the conversion for all nonnegative integer inputs, preserve zero and invalid-input behavior, '
                'and add regression tests covering 1, 2, 7 days, zero, negative values, booleans and nonintegers.\n\n'
                f'Scope: fix {prefix}/duration.py and add regression tests in {prefix}/. '
                'Do not edit existing tests or unrelated source. '
                'Native baseline and final suite: python -m unittest discover -s live_cases -p "test_*.py" -v. '
                'Build and lint may use python -m compileall -q live_cases. '
                'The regression must fail on the base and pass on the fix. '
                'No payment is promised or requested. Treat this as an unpriced owner request.\n')
        # Recover an accepted create whose client response was lost, on subsequent inspection.
        self.data['issue_title'] = f'[LIVE-INTEGRATION {self.data["id"]}] Correct day-to-second conversion'
        self.save()
        issue = self.api.api(f'repos/{self.target}/issues', 'POST', {'title': self.data['issue_title'], 'body': body})
        self.data.update(issue=issue['number'], issue_url=issue['html_url'],
                         task_id=task_id(self.target, issue['number']))
        self.record('FIXTURE', 'PASS', issue=issue['html_url'], commit=commit['sha'])

    def admit(self):
        check(not self.data.get('closed'), 'Campaign closed; use a new run directory')
        check(self.data.get('issue'), 'Provision a fixture first')
        check(not self.data.get('dispatch_id'), 'Cannot re-admit a dispatched generation')
        import agent_door
        from functools import partial
        from sovereign_discovery import discover
        server = None
        previous_port = agent_door.PROXY_PORT
        previous_url = os.environ.get('TOKENHARBOR_PROXY_BASE_URL')
        previous_door = os.environ.get('BOUNTY_ENTRY_DOOR')
        os.environ['BOUNTY_ENTRY_DOOR'] = 'cline'
        if self.args.gateway == 'isolated':
            # Serve the actual deployed gateway handler, with actual provider calls,
            # on a private port. Do not reuse or stop another application's proxy.
            from http.server import HTTPServer
            import kaggle_engine_worker as worker
            server = HTTPServer(('127.0.0.1', 0), worker._ClineProxyHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            agent_door.PROXY_PORT = server.server_port
            os.environ['TOKENHARBOR_PROXY_BASE_URL'] = f'http://127.0.0.1:{server.server_port}/v1'
            self.record('GATEWAY_INSTANCE', 'OBSERVED', implementation='kaggle_engine_worker._ClineProxyHandler',
                        port=server.server_port, isolated=True)
        else:
            check(agent_door.start_gateway(), 'Real model gateway unavailable')
        attempt = 1 + len(list(self.folder.glob('scout-*')))
        work = self.folder / f'scout-{attempt}'
        work.mkdir(exist_ok=True)
        previous_workspace = os.environ.get('BOUNTY_AGENT_WORKSPACE')
        previous_timeout = os.environ.get('BOUNTY_AGENT_TIMEOUT')
        os.environ['BOUNTY_AGENT_WORKSPACE'] = str((work / 'agent').resolve())
        os.environ['BOUNTY_AGENT_TIMEOUT'] = str(self.args.model_timeout)
        self.data['queue_dir'] = str(work.resolve())
        self.save()
        before, before_sha = StateStore(self.api, self.control).read(self.data['task_id'])
        try:
            outcome = discover(['normal', 'founder'], max_dispatches=0, live=True,
                state_dir=work, api=self.api, store=StateStore(self.api, self.control),
                finder=partial(agent_door.find_issues, targets=[(self.target, self.data['issue'])]))
        finally:
            agent_door.PROXY_PORT = previous_port
            for name, value in [('TOKENHARBOR_PROXY_BASE_URL', previous_url), ('BOUNTY_ENTRY_DOOR', previous_door),
                                ('BOUNTY_AGENT_WORKSPACE', previous_workspace), ('BOUNTY_AGENT_TIMEOUT', previous_timeout)]:
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            if server:
                server.shutdown()
                server.server_close()
        (work / 'result.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
        with contextlib.closing(sqlite3.connect(work / 'agent-queue.sqlite3')) as con:
            rows = con.execute('SELECT task_id,payload,disposition FROM decisions').fetchall()
        # A scout that never wrote a row has a reason, and it is in the scout's own result.
        # Measured 2026-11-02: the door died on "TokenHarbor router HTTP 429: You've used this
        # period's free allowance", but this assertion reported only "Real scout failed", so the
        # one fact that explained the run -- an exhausted provider quota, not a code defect --
        # was thrown away and the failure looked like a pipeline bug. Report the reason.
        if not rows:
            logs = sorted(work.rglob('agent.log'), key=lambda p: p.stat().st_mtime)
            tail = logs[-1].read_text(encoding='utf-8', errors='replace')[-1200:] if logs else ''
            detail = {'result': outcome, 'tail': tail, 'log_path': str(logs[-1]) if logs else None}
            (self.folder / 'scout-result.json').write_text(json.dumps(detail, indent=2), encoding='utf-8')
            raise AssertionError('Real scout failed before writing a row: '
                                 + str(outcome) + '\n' + (str(detail.get('tail') or '') or f'No agent log retained under {work}'))
        check(len(rows) == 1 and rows[0][0] == self.data['task_id'], 'Production search did not queue exactly the scoped original')
        check(rows[0][2] == 'capacity_wait', f'Production queue did not defer at zero dispatch budget: {outcome}')
        state, state_sha = StateStore(self.api, self.control).read(self.data['task_id'])
        check(state == before and state_sha == before_sha, 'Durable ledger changed during zero-budget discovery; repeat observation')
        check(not outcome['dispatched'], 'Zero-budget discovery dispatched a task')
        self.data['admitted'] = json.loads(rows[0][1])
        require_evidence(self.data['admitted'], self.api.issue_context(self.target, self.data['issue']))
        (self.folder / 'admission.json').write_text(json.dumps(self.data['admitted'], indent=2), encoding='utf-8')
        self.record('LIVE_MODEL_ADMISSION', 'PASS', implementation='agent_door.find_issues',
                    source_revision=self.data['admitted']['admission']['source_revision'])
        self.record('LIVE_QUEUE_DEFERRAL', 'PASS', queue=str(work), dispatch_budget=0, ledger_unchanged=True)
        self.source_rejections()

    def source_rejections(self):
        """Corrupt copies of real admission evidence; original sources stay untouched."""
        import copy
        row = self.data['admitted']
        context = self.api.issue_context(self.target, self.data['issue'])
        require_evidence(row, context)
        before, sha = StateStore(self.api, self.control).read(self.data['task_id'])
        outcomes = {}
        mutations = {
            'identity': ('Admission task identity mismatch', lambda r: r['admission'].update(task_id='0' * 32)),
            'source_revision': ('Admission source changed', lambda r: r['admission'].update(source_revision='0' * 64)),
            'competition_unavailable': ('Competition observation unavailable', lambda r: r['competition'].update(verified=False)),
            'admission_missing': ('Admission proof missing', lambda r: r.update(admission=None)),
        }
        for name, (expected, mutate) in mutations.items():
            changed = copy.deepcopy(row)
            mutate(changed)
            try:
                require_evidence(changed, context)
            except ValueError as exc:
                check(expected in str(exc), f'Wrong evidence refusal for {name}: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'Corrupt real admission accepted: {name}')
        after, after_sha = StateStore(self.api, self.control).read(self.data['task_id'])
        check(before == after and sha == after_sha, 'Evidence probes changed the real ledger')
        self.record('LIVE_SOURCE_REJECTIONS', 'PASS', refusals=outcomes, ledger_unchanged=True)

    def dispatch(self):
        check(not self.data.get('closed'), 'Campaign closed; use a new run directory')
        check(self.data.get('admitted'), 'Real admission required')
        store = self.ledger()
        old, _ = store.read(self.data['task_id'])
        if old and not str(old.get('status', '')).startswith('FAILED'):
            check(old.get('admission') == self.data['admitted']['admission'], 'Existing unrelated task record')
            check(old.get('dispatch_id'), 'Existing task has no delivery generation; cannot resume it')
            self.data['dispatch_id'] = old.get('dispatch_id')
            self.data['run_search_since'] = min(self.data['started_at'], old.get('dispatched_at') or self.data['started_at'])
            self.save()
            self.record('DISPATCH_RESUME', 'OBSERVED', remote_status=old['status'])
            return
        from actions_dispatch import repository_over_capacity, repository_size_kb
        context = self.api.issue_context(self.target, self.data['issue'])
        row = self.data['admitted']
        require_evidence(row, context)
        check(not repository_over_capacity(repository_size_kb(self.api, self.target)), 'Sandbox over capacity')
        active = {r['id'] for status in ('queued', 'in_progress', 'waiting', 'pending', 'requested')
                  for r in self.api.workflow_runs(self.control, status)}
        reservations = [r for r in store.records() if r.get('status') in
                        ('DISPATCHING', 'DISPATCHED', 'CLAIMED', 'ENGINEERING', 'VERIFIED', 'PUBLISHING')]
        check(max(len(active), len(reservations)) < 4, 'Live fleet at capacity; resume dispatch later')
        from sovereign_discovery import discover
        check(self.data.get('queue_dir'), 'Production discovery queue is required; re-run admission')
        outcome = discover(list(PRODUCTION_LANES), max_dispatches=1, live=True,
                           state_dir=self.data['queue_dir'], hydrate_only=True,
                           api=self.api, store=store, preparation_budget=self.args.engineering_budget)
        check(outcome['dispatched'] == [self.data['task_id']], f'Production hydration did not dispatch the waiting original: {outcome}')
        state, sha = store.read(self.data['task_id'])
        self.data['dispatch_id'] = state['dispatch_id']
        self.record('REAL_REPOSITORY_DISPATCH', 'PASS', dispatch_id=state['dispatch_id'], state_sha=sha)
        self.record('LIVE_QUEUE_RECOVERY', 'PASS', resumed_from_disk=True, dispatch_id=state['dispatch_id'])
        replay = discover(list(PRODUCTION_LANES), max_dispatches=1, live=True,
                          state_dir=self.data['queue_dir'], hydrate_only=True, api=self.api, store=store)
        after, _ = store.read(self.data['task_id'])
        check(not replay['dispatched'] and after['dispatch_id'] == state['dispatch_id'],
              'Hydration replay created another delivery generation')
        self.record('LIVE_QUEUE_REPLAY', 'PASS', additional_dispatches=0)

    def observe(self):
        check(self.data.get('dispatch_id'), 'No dispatched generation to observe')
        from actions_reconcile import reconcile
        identity = self.data['task_id']
        store = ScopedStore(self.api, self.control, [identity])
        runs = self.recent_runs()
        matches = [r for r in runs if self.data['dispatch_id'] in r.get('display_title', '')]
        check(len(matches) <= 1, 'Duplicate real Actions runs for one generation')
        if not matches:
            self.record('ACTIONS_RUN', 'PENDING', reason='Dispatch not yet observed')
            return
        run = matches[0]
        self.data.update(run_id=run['id'], run_url=run['html_url'], run_status=run['status'],
                         run_conclusion=run.get('conclusion'))
        jobs = list(self.api.api(f'repos/{self.control}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs'])
        (self.folder / 'jobs.json').write_text(json.dumps(jobs, indent=2), encoding='utf-8')
        state, sha = store.read(identity)
        (self.folder / 'remote-state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        check(state['dispatch_id'] == self.data['dispatch_id'], 'Generation changed')
        if run['status'] != 'completed':
            self.record('ACTIONS_RUN', 'PENDING', url=run['html_url'], jobs=[
                {'name': j['name'], 'status': j['status'], 'conclusion': j['conclusion']} for j in jobs])
            return
        destination = self.folder / ('artifacts-' + str(run['id']))
        destination.mkdir(exist_ok=True)
        if not self.data.get('artifacts_downloaded'):
            self.command(['gh', 'run', 'download', str(run['id']), '--repo', self.control,
                          '--dir', str(destination)], timeout=180)
            self.data['artifacts_downloaded'] = True
            self.save()
        reconcile(repair=False, api=self.api, store=store)
        state, sha = store.read(identity)
        self.data['remote_status'] = state['status']
        self.record('ACTIONS_TERMINAL', 'PASS' if run['conclusion'] == 'success' else 'FAIL',
                    url=run['html_url'], conclusion=run['conclusion'], state=state['status'], state_sha=sha,
                    diagnostic=state.get('diagnostic'))
        expected = self.data.get('delivery_harnesses', {}).get(self.data['dispatch_id'], self.data['deployed_sha'])
        verified_harness = delivery_harness(run, state, expected,
                                            continuation=bool(self.data.get('continuations')))
        check(run['conclusion'] == 'success', 'Real pipeline failed; artifacts retained, downstream stages untested')
        required = {'claim', 'engineer', 'publish', 'reconcile'}
        check(required <= {j['name'] for j in jobs if j['conclusion'] == 'success'}, 'A real delivery job did not succeed')
        check(state.get('pr_number'), 'No real PR publication recorded')
        pr = self.api.api(f'repos/{self.target}/pulls/{state["pr_number"]}')
        check(pr['head']['sha'] == state['head_sha'], 'Published head differs from durable evidence')
        releases = list(destination.rglob('release.json'))
        check(releases, 'Real release receipt missing')
        release = json.loads(releases[0].read_text())
        check(release.get('harness_sha') == verified_harness, 'Release and Actions harness differ')
        check(release['task_id'] == identity and release['admission'] == self.data['admitted']['admission'],
              'Source-bound proof did not survive the real pipeline')
        check(release['head_sha'] == pr['head']['sha'], 'Release receipt head mismatch')
        check(release.get('verification') and all(r['exit_code'] == 0 for r in release['verification']),
              'Native command receipts missing or failing')
        from actions_reconcile import classify_checks
        checks = classify_checks(self.api, self.target, pr['head']['sha'])
        self.data.update(pr_number=pr['number'], pr_url=pr['html_url'], head_sha=pr['head']['sha'],
                         checks=checks, delivered_to_pr=True)
        self.data.setdefault('delivery_harnesses', {})[self.data['dispatch_id']] = verified_harness
        self.record('DELIVERY_HARNESS', 'OBSERVED', dispatch_id=self.data['dispatch_id'],
                    actions_sha=verified_harness, driver_sha=self.data['local_sha'])
        self.record('REAL_PUBLICATION', 'PASS', pr=pr['html_url'], head=pr['head']['sha'], checks=checks['state'])

    def failed_jobs(self, run):
        """The jobs Actions itself marked failed. Never an interpretation of the log."""
        try:
            jobs = self.api.api(f"repos/{self.control}/actions/runs/{run['id']}/jobs?per_page=100")['jobs']
        except (GitHubError, KeyError, ValueError):
            return ''
        failed = [str(j.get('name')) for j in jobs if j.get('conclusion') == 'failure']
        if failed:
            return ','.join(failed)
        skipped = [str(j.get('name')) for j in jobs if j.get('conclusion') == 'skipped']
        return 'no failed job' + ('; skipped: ' + ','.join(skipped) if skipped else '')

    def surface_entries(self):
        """Every failure and refusal the production lane carries, with what it states.

        Two independent witnesses, because either alone is blind. The durable ledger holds a
        row per task; Actions holds a run per dispatch. A run that died before writing a row
        has no row to read, and a row whose run was deleted has no run to read -- so a surface
        built from one of them reports a lane that never existed.

        Measured 2026-11-01: 113 ledger records, 8 FAILED_* rows, 0 PR URLs behind them, and
        no code in the repository read any of them.
        """
        entries, violations = [], []
        try:
            rows = list(self.ledger().records() or [])
        except (GitHubError, ValueError) as exc:
            rows = []
            violations.append('Durable ledger unreadable: ' + str(exc)[:300])
        self.data['surface_ledger_rows'] = len(rows)
        dispatched = {}
        for row in rows:
            if row.get('dispatch_id'):
                dispatched[str(row['dispatch_id'])] = True
            kind, stage = failure_kind(row.get('status'))
            if not kind:
                continue
            entries.append({'kind': kind, 'status': str(row.get('status')), 'stage': stage,
                            'identity': row.get('task_id') or 'unknown-task',
                            'repo': row.get('repo'), 'issue': row.get('issue_number'),
                            'dispatch_id': row.get('dispatch_id'), 'attempt': row.get('attempt'),
                            'at': row.get('finished_at') or row.get('updated_at'),
                            'pr': row.get('pr_url'), 'run_url': row.get('run_url'),
                            'cause': recorded_cause(row), 'witness': 'ledger'})
        runs = []
        try:
            runs = list(self.api.workflow_runs(self.control, 'completed') or [])
        except (GitHubError, ValueError) as exc:
            violations.append('Actions runs unreadable: ' + str(exc)[:300])
        self.data['surface_completed_runs'] = len(runs)
        for run in runs:
            conclusion = str(run.get('conclusion') or '')
            if conclusion not in RUN_FAILURE_CONCLUSIONS:
                continue
            dispatch = next(iter(re.findall(r'[0-9a-f]{32}', run.get('display_title') or '')), None)
            if dispatch and dispatch in dispatched:
                continue
            jobs = self.failed_jobs(run)
            entries.append({'kind': 'failure', 'status': 'RUN_' + conclusion.upper(),
                            'stage': jobs or 'unknown', 'identity': dispatch or str(run.get('id')),
                            'repo': self.target, 'issue': None, 'dispatch_id': dispatch,
                            'attempt': None, 'at': run.get('updated_at'), 'pr': None,
                            'run_url': run.get('html_url'),
                            'cause': 'run concluded ' + conclusion + ('; failing jobs: ' + jobs if jobs else ''),
                            'witness': 'actions'})
        for entry in entries:
            if entry['kind'] != 'failure':
                continue
            if not entry['cause']:
                violations.append(f"unexplained failure {entry['identity']} ({entry['status']})")
            if entry['stage'] in (None, '', 'unknown'):
                violations.append(f"unclassified failure {entry['identity']} ({entry['status']})")
        return entries, violations

    def failures(self):
        """Surface every real run failure, live, from the ledger and Actions together.

        It judges nothing. A failure is a record whose status says FAILED_; a refusal is one
        that says REJECTED_ and is counted apart, because re-dispatching a verdict spends a
        run to relearn an answer already written down. A fault with no stated cause is
        surfaced as unexplained and fails the case: that is the class that stayed invisible.
        """
        entries, violations = self.surface_entries()
        receipt = self.folder / 'failures.json'
        receipt.write_text(json.dumps(entries, indent=2) + "\n", encoding='utf-8')
        faults = [e for e in entries if e['kind'] == 'failure']
        verdicts = [e for e in entries if e['kind'] == 'refusal']
        by_stage = {}
        for entry in faults:
            by_stage[entry['stage']] = by_stage.get(entry['stage'], 0) + 1
        summary = ['| kind | stage | status | cause | run |', '|---|---|---|---|---|']
        for entry in entries:
            cause = (entry['cause'] or 'UNEXPLAINED').replace('|', '/').replace('\n', ' ')[:180]
            summary.append('| ' + entry['kind'] + ' | ' + str(entry['stage']) + ' | ' + entry['status']
                           + ' | ' + cause + ' | ' + (entry['run_url'] or '') + ' |')
        (self.folder / 'failures.md').write_text("\n".join(summary) + "\n", encoding='utf-8')
        self.record('LIVE_FAILURE_SURFACE', 'FAIL' if violations else 'PASS',
                    failures=len(faults), refusals=len(verdicts), by_stage=by_stage,
                    ledger_rows=self.data.get('surface_ledger_rows'),
                    completed_runs=self.data.get('surface_completed_runs'),
                    unexplained=[e['identity'] for e in faults if not e['cause']],
                    violations=violations, receipt=str(receipt))
        check(not violations, '; '.join(violations))

    def merge(self):
        self.intake()
        check(self.data.get('delivered_to_pr'), 'Observe a successfully published real PR first')
        from actions_reconcile import classify_checks, reconcile
        head = self.data['head_sha']
        checks = classify_checks(self.api, self.target, head)
        check(checks['state'] == 'PASSED', f'Real native CI is {checks["state"]}; merge refused')
        number = self.data['pr_number']
        pr = self.api.api(f'repos/{self.target}/pulls/{number}')
        check(pr['head']['sha'] == head and pr['user']['login'] == self.data['account'], 'PR ownership/head changed')
        if not pr['merged']:
            check(not self.data.get('existing_issue'), 'Original upstream PR must be merged by its maintainer')
            result = self.api.api(f'repos/{self.target}/pulls/{number}/merge', 'PUT',
                                  {'sha': head, 'merge_method': 'squash'})
            check(result.get('merged'), 'GitHub did not merge fixture PR')
        store = ScopedStore(self.api, self.control, [self.data['task_id']])
        reconcile(repair=False, api=self.api, store=store)
        first, _ = store.read(self.data['task_id'])
        reconcile(repair=False, api=self.api, store=store)
        second, _ = store.read(self.data['task_id'])
        check(first['status'] == second['status'] == 'DELIVERED', 'Merge/replay did not settle to DELIVERED')
        check(second.get('payment_status') == 'UNVERIFIED', 'Merge was incorrectly treated as payment')
        self.data.update(remote_status=second['status'], payment_status=second.get('payment_status'))
        (self.folder / 'terminal-state.json').write_text(json.dumps(second, indent=2), encoding='utf-8')
        self.record('MERGE_AND_RECONCILE_REPLAY', 'PASS', pr=self.data['pr_url'], payment='UNVERIFIED')
        missing = [case for case, status in self.data['coverage'].items() if status != 'PASS']
        check(not missing, f'Master coverage is incomplete or failing: {missing}')
        self.data['end_to_end_passed'] = True
        self.save()

    def audit(self):
        self.preflight()
        runs = self.api.workflow_runs(self.control)[:10]
        observations = []
        for run in runs[:4]:
            jobs = self.api.api(f'repos/{self.control}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
            observations.append({'run': run['html_url'], 'status': run['status'], 'conclusion': run['conclusion'],
                                 'jobs': [{'name': j['name'], 'conclusion': j['conclusion']} for j in jobs]})
        self.record('LIVE_DEPLOYMENT_AUDIT', 'OBSERVED', runs=observations)

    def faults(self):
        """Real remote storage/transport failures. Seeded states are fault inputs, not E2E receipts."""
        self.preflight(require_publication=False)
        branch = 'live-integration/' + self.data['id']
        store = StateStore(self.api, self.control)
        store.branch = branch
        store.ensure()
        self.data['fault_branch'] = branch
        self.save()
        identity = task_id(self.target, self.data.get('issue', 1))
        failures = []

        def case(name, action):
            try:
                evidence = action() or {}
                self.record(name, 'PASS', **evidence)
            except Exception as exc:
                failures.append(name)
                self.record(name, 'FAIL', diagnostic=str(exc)[:1200])

        def denied(action, exception, phrase):
            try:
                action()
            except exception as exc:
                check(phrase.lower() in str(exc).lower(), f'Wrong refusal: {exc}')
                return {'refusal': str(exc)[:300]}
            raise AssertionError('Fault was accepted instead of refused')

        def roundtrip():
            store.mutate(identity, lambda old: {'task_id': identity, 'status': 'FAULT_FIXTURE',
                                              'marker': self.data['id'], 'text': 'Unicode ₹ 日本語\nsecond line'})
            observed, sha = store.read(identity)
            check(observed['text'] == 'Unicode ₹ 日本語\nsecond line', 'Remote bytes changed')
            return {'state_sha': sha, 'branch': branch}
        case('LIVE_STATE_ROUNDTRIP', roundtrip)

        def stale_write():
            old, sha = store.read(identity)
            fresh = store.mutate(identity, lambda row: {**row, 'counter': 1})
            try:
                store.write(identity, {**old, 'counter': 2}, sha)
            except GitHubError as exc:
                check('409' in str(exc) or '422' in str(exc), 'Expected real GitHub CAS conflict')
            else:
                raise AssertionError('GitHub accepted stale state SHA')
            observed, new_sha = store.read(identity)
            check(observed['counter'] == fresh['counter'] == 1, 'Stale write lost the winning update')
            return {'old_sha': sha, 'new_sha': new_sha}
        case('LIVE_CAS_CONFLICT', stale_write)

        generation = uuid.uuid4().hex
        def race():
            store.mutate(identity, lambda old: {'task_id': identity, 'repo': self.target,
                         'issue_number': self.data.get('issue', 1), 'status': 'DISPATCHED',
                         'dispatch_id': generation, 'attempt': 0, 'fault_fixture': True})
            barrier = threading.Barrier(2)
            def claimant(owner):
                barrier.wait(timeout=15)
                try:
                    claimed = store.claim(self.target, self.data.get('issue', 1), owner,
                                          'https://example.invalid/fault-worker', self.data['local_sha'],
                                          dispatch_id=generation)
                    return {'owner': owner, 'claimed': True, 'attempt': claimed['attempt']}
                except ValueError as exc:
                    return {'owner': owner, 'claimed': False, 'refusal': str(exc)}
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(claimant, ['fault-worker-a:1', 'fault-worker-b:1']))
            check(sum(r['claimed'] for r in outcomes) == 1, f'Double claim or no winner: {outcomes}')
            row, _ = store.read(identity)
            check(row['attempt'] == 1, 'Losing claimant consumed an attempt')
            return {'outcomes': outcomes}
        case('LIVE_CONCURRENT_CLAIM', race)

        def replay():
            row, _ = store.read(identity)
            again = store.claim(self.target, self.data.get('issue', 1), row['owner'],
                                row['run_url'], self.data['local_sha'], dispatch_id=generation)
            check(again['attempt'] == row['attempt'], 'Same-owner replay consumed another attempt')
            return {'owner': again['owner'], 'attempt': again['attempt']}
        case('LIVE_CLAIM_REPLAY', replay)
        case('LIVE_STALE_GENERATION', lambda: denied(lambda: store.claim(
            self.target, self.data.get('issue', 1), 'late:1', 'url', self.data['local_sha'],
            dispatch_id='stale-' + generation), ValueError, 'generation mismatch'))
        case('LIVE_WRONG_OWNER', lambda: denied(lambda: store.owned_update(
            identity, 'not-the-owner:1', status='PUBLISHING'), ValueError, 'ownership lost'))

        def revoked():
            row, _ = store.read(identity)
            store.mutate(identity, lambda old: {**old, 'owner_revoked': old['owner']})
            return denied(lambda: store.assert_owner(identity, row['owner']), ValueError, 'ownership lost')
        case('LIVE_REVOKED_OWNER', revoked)

        def cap():
            store.mutate(identity, lambda old: {'status': 'FAILED_ENGINEERING', 'attempt': 3})
            return denied(lambda: store.claim(self.target, self.data.get('issue', 1),
                          'retry:1', 'url', self.data['local_sha']), ValueError, 'attempts exhausted')
        case('LIVE_RETRY_CAP', cap)

        def corruption():
            row, sha = store.read(identity)
            endpoint = f'repos/{self.control}/contents/fleet-state/{identity}.json'
            result = self.api.api(endpoint, 'PUT', {'message': 'integration: inject truncated state',
                      'branch': branch, 'sha': sha, 'content': base64.b64encode(b'{"status":').decode()})
            corrupt_sha = result['content']['sha']
            try:
                denied(lambda: store.read(identity), json.JSONDecodeError, 'Expecting')
            finally:
                store.write(identity, row, corrupt_sha)
            restored, _ = store.read(identity)
            check(restored == row, 'Corrupt state fixture was not restored')
            return {'corrupt_sha': corrupt_sha, 'restored': True}
        case('LIVE_TRUNCATED_STATE', corruption)
        case('LIVE_GITHUB_401', lambda: denied(lambda: GitHub(token='invalid-live-integration-token').api('user'),
                                              GitHubError, '401'))
        case('LIVE_GITHUB_404', lambda: denied(lambda: self.api.api(
            f'repos/{self.data["account"]}/integration-missing-{self.data["id"]}'), GitHubError, '404'))
        self.data['fault_failures'] = failures
        self.save()
        check(not failures, f'Live fault cases failed: {failures}')

    def cleanup(self):
        """Close only this run's issue/PR. Preserve source, ledger, and remote receipts."""
        if self.data.get('existing_issue'):
            self.record('CLEANUP', 'OBSERVED', reason='Original issue and upstream PR are retained unchanged')
            return
        if self.data.get('run_id'):
            run = self.api.api(f'repos/{self.control}/actions/runs/{self.data["run_id"]}')
            check(run['status'] == 'completed', 'Delivery still running; cleanup refused')
            state, _ = StateStore(self.api, self.control).read(self.data['task_id'])
            check(state and state.get('dispatch_id') == self.data.get('dispatch_id'),
                  'Another generation has taken over; cleanup refused')
        if self.data.get('pr_number'):
            number = self.data['pr_number']
            pr = self.api.api(f'repos/{self.target}/pulls/{number}')
            check(pr['head']['sha'] == self.data['head_sha'], 'PR changed; cleanup refused')
            if pr['state'] == 'open':
                self.api.api(f'repos/{self.target}/pulls/{number}', 'PATCH', {'state': 'closed'})
        if self.data.get('issue'):
            issue = self.api.api(f'repos/{self.target}/issues/{self.data["issue"]}')
            check(self.data['id'] in issue['title'], 'Fixture identity changed')
            if issue['state'] == 'open':
                self.api.api(f'repos/{self.target}/issues/{self.data["issue"]}', 'PATCH', {'state': 'closed'})
        if self.data.get('negative_issue'):
            check(self.data.get('negative_claim_passed'), 'Negative workflow has not been verified complete')
            number = self.data['negative_issue']
            issue = self.api.api(f'repos/{self.target}/issues/{number}')
            check(self.data['id'] in issue['title'], 'Negative fixture identity changed')
            if issue['state'] == 'open':
                self.api.api(f'repos/{self.target}/issues/{number}', 'PATCH', {'state': 'closed'})
        self.data['closed'] = True
        self.record('CLEANUP', 'PASS', retained=['source fixtures', 'fault branch', 'durable ledger', 'Actions artifacts'])

    def negative_claim(self):
        """Submit an actually invalid generation to the real Actions workflow."""
        check(not self.data.get('closed'), 'Campaign closed; use a new run directory')
        check(self.data.get('issue'), 'Provision a fixture first')
        if self.data.get('negative_dispatch', {}).get('rejected'):
            self.data.setdefault('negative_dispatch_attempts', []).append(self.data.pop('negative_dispatch'))
        check(not self.data.get('negative_dispatch'), 'Negative dispatch already submitted; observe it')
        # A separate real issue prevents legitimate positive-job writes from
        # invalidating the negative case's unchanged-ledger assertion.
        if self.data.get('existing_issue'):
            self.data['negative_issue'] = self.data['existing_issue']
        if not self.data.get('negative_issue'):
            issue = self.api.api(f'repos/{self.target}/issues', 'POST', {
                'title': f'[LIVE-INTEGRATION {self.data["id"]}] Invalid generation rejection fixture',
                'body': 'Authorized negative integration fixture. This is not an engineering task or bounty. '
                        'A deliberately invalid workflow generation must be rejected before engineering.'})
            self.data['negative_issue'] = issue['number']
            self.save()
        identity = task_id(self.target, self.data['negative_issue'])
        store = StateStore(self.api, self.control)
        before, sha = store.read(identity)
        baseline = [r['id'] for r in self.recent_runs()]
        self.data['negative_dispatch'] = {'generation': 'invalid-' + self.data['id'],
            'baseline_runs': baseline, 'state_sha': sha, 'state': before, 'submitted_at': self.now(),
            'task_id': identity, 'issue': self.data['negative_issue']}
        self.save()  # An ambiguous POST must never be blindly replayed.
        # Dispatch at a ref that is actually a branch. ``control_branch`` is only written by
        # preflight(), which this phase does not call, so the fallback has to be a real branch
        # name -- never a commit SHA: the dispatch API answers HTTP 422 "No ref found" for a
        # SHA, which reads as a transport fault rather than the wrong-ref mistake it is.
        branch = self.data.get('control_branch') or self.api.api(f'repos/{self.control}')['default_branch']
        check(isinstance(branch, str) and branch and not re.fullmatch(r'[0-9a-f]{40}', branch),
              f'Negative dispatch needs a branch name, not {branch!r}')
        try:
            self.api.api(f'repos/{self.control}/actions/workflows/engine2.yml/dispatches', 'POST', {
                'ref': branch, 'inputs': {'mode': 'deliver', 'target_repo': self.target,
                'issue_number': str(self.data['negative_issue']), 'dispatch_id': self.data['negative_dispatch']['generation']}})
        except GitHubError as exc:
            if any(f'HTTP {status}' in str(exc) for status in (400, 401, 403, 404, 422)):
                self.data['negative_dispatch']['rejected'] = True
                self.save()
            raise
        self.record('REAL_INVALID_GENERATION_SUBMITTED', 'OBSERVED')

    def observe_negative(self):
        negative = self.data['negative_dispatch']
        matches = [r for r in self.recent_runs()
                   if r['id'] not in negative['baseline_runs'] and r['event'] == 'workflow_dispatch'
                   and self.target in r.get('display_title', '')
                   and r.get('display_title', '').rstrip().endswith(f'#{negative["issue"]}')]
        check(len(matches) <= 1, 'Ambiguous negative workflow run; manual inspection required')
        if not matches or matches[0]['status'] != 'completed':
            self.record('REAL_INVALID_GENERATION', 'PENDING')
            return
        run = matches[0]
        jobs = self.api.api(f'repos/{self.control}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
        jobs_by_name = {j['name']: j for j in jobs}
        check(jobs_by_name['claim']['conclusion'] == 'failure', 'Invalid generation did not fail claim')
        check(all(jobs_by_name.get(n, {}).get('conclusion') == 'skipped' for n in ('engineer', 'publish')),
              'Invalid generation reached engineering/publication')
        log = self.command(['gh', 'run', 'view', str(run['id']), '--repo', self.control, '--log-failed'])
        (self.folder / 'negative-claim.log').write_text(log, encoding='utf-8')
        check('Matching admitted dispatch generation required' in log,
              'Claim failed for an unrelated reason; expected gate was not exercised')
        after, sha = StateStore(self.api, self.control).read(negative['task_id'])
        check(after == negative['state'] and sha == negative['state_sha'], 'Invalid generation changed durable state')
        self.data['negative_claim_passed'] = True
        self.record('REAL_INVALID_GENERATION', 'PASS', run=run['html_url'], downstream='engineer/publish skipped')

    def artifact_faults(self):
        """Corrupt copies of actual Actions release artifacts, then run the real validator and Git clone."""
        check(self.data.get('delivered_to_pr'), 'A real successful delivery is required; no synthetic release allowed')
        import copy
        from actions_delivery import validate_bundle
        receipts = list((self.folder / ('artifacts-' + str(self.data['run_id']))).rglob('release.json'))
        check(receipts, 'Downloaded release artifact missing')
        receipt = json.loads(receipts[0].read_text())
        check(receipt['harness_sha'] == self.data['deployed_sha'], 'Unexpected release harness')
        os.environ['GITHUB_SHA'] = self.data['deployed_sha']
        bundle = receipts[0].with_name('release.bundle')
        check(bundle.is_file(), 'Actual Git release bundle missing')
        root = self.folder / ('release-probes-' + uuid.uuid4().hex[:8])
        root.mkdir()
        validate_bundle(receipt, bundle, root / 'control')
        self.record('ACTUAL_RELEASE_POSITIVE_CONTROL', 'PASS')
        mutations = {
            'task_identity': lambda r: r.update(task_id='0' * 32),
            'head': lambda r: r.update(head_sha='0' * 40),
            'tree': lambda r: r.update(tree_sha='0' * 40),
            'file_manifest': lambda r: r.update(files={}),
            'native_receipts_missing': lambda r: r.update(verification=[]),
            'regression_never_red': lambda r: r['regression'].update(red_exit=0),
            'regression_not_green': lambda r: r['regression'].update(green_exit=1),
        }
        expected = {'task_identity': 'task identity mismatch', 'head': 'Bundle HEAD mismatch',
                    'tree': 'Release tree mismatch', 'file_manifest': 'Changed-file release proof mismatch',
                    'native_receipts_missing': 'lacks a successful receipt',
                    'regression_never_red': 'Red-to-green regression proof missing',
                    'regression_not_green': 'Red-to-green regression proof missing'}
        failures = []
        for name, mutate in mutations.items():
            changed = copy.deepcopy(receipt)
            mutate(changed)
            try:
                validate_bundle(changed, bundle, root / name)
            except ValueError as exc:
                matched = expected[name].lower() in str(exc).lower()
                if not matched:
                    failures.append(name)
                self.record('LIVE_RELEASE_' + name.upper(), 'PASS' if matched else 'FAIL', refusal=str(exc))
            except Exception as exc:
                failures.append(name)
                self.record('LIVE_RELEASE_' + name.upper(), 'FAIL', diagnostic=str(exc))
            else:
                failures.append(name)
                self.record('LIVE_RELEASE_' + name.upper(), 'FAIL', diagnostic='Corrupt artifact accepted')
        check(not failures, f'Actual release validation failures: {failures}')

    def wait(self):
        deadline = time.monotonic() + self.args.wait_minutes * 60
        while time.monotonic() < deadline:
            self.observe()
            if self.data.get('delivered_to_pr') and self.data.get('checks', {}).get('state') == 'PASSED':
                return
            time.sleep(20)
        raise TimeoutError('Live delivery/CI deadline exhausted; resume observe, do not redispatch')

    def run(self):
        if self.args.issue is None and not self.data.get('existing_issue'):
            return self.pipeline()
        """Retain fleet-health failures while exercising independent scoped delivery."""
        check(not self.data.get('closed'), 'Campaign was closed; use a new run directory')
        try:
            self.intake()
        except (AssertionError, GitHubError) as exc:
            # Fleet backlog and the explicitly scoped test issue are independent.
            # Continue collecting real delivery receipts; final acceptance still
            # requires the intake case and every other required case to pass.
            self.record('LIVE_INTAKE', 'FAIL', diagnostic=str(exc)[:2000])
        blockers = []
        try:
            if not self.data.get('issue'):
                self.provision()
            else:
                self.preflight()
        except (AssertionError, GitHubError) as exc:
            self.record('TARGET_PREFLIGHT', 'FAIL', diagnostic=str(exc)[:2000])
            if not (self.data.get('existing_issue') and self.data.get('issue') and self.data.get('deployed_sha')):
                raise
            blockers.append(str(exc))
        # Source reading and admission are read-only with a zero dispatch budget.
        # Exercise the real entry door even when publication itself is blocked.
        if not self.data.get('admitted'):
            try:
                self.admit()
            except (AssertionError, GitHubError) as exc:
                self.record('LIVE_MODEL_ADMISSION', 'FAIL', diagnostic=str(exc)[:2000])
                blockers.append('Entry door: ' + str(exc))
        self.faults()
        if not self.data.get('negative_dispatch'):
            self.negative_claim()
        deadline = time.monotonic() + 600
        while not self.data.get('negative_claim_passed') and time.monotonic() < deadline:
            self.observe_negative()
            if not self.data.get('negative_claim_passed'):
                time.sleep(20)
        check(self.data.get('negative_claim_passed'), 'Invalid-generation workflow observation timed out')
        check(not blockers, 'Delivery blocked; independent fault checks completed: ' + '; '.join(blockers))
        if not self.data.get('dispatch_id'):
            self.dispatch()
        # One shot, every independent surface. A wait deadline or a blocked publication used to
        # abort the remaining cases, so each repair round only ever revealed the next one. Each
        # phase below now records its own verdict and the campaign continues; the aggregate at the
        # end names every failing required case at once.
        def phase(case, action):
            try:
                action()
            except (AssertionError, GitHubError, ValueError, TimeoutError) as exc:
                if self.data['coverage'].get(case) != 'FAIL':
                    self.record(case, 'FAIL', diagnostic=str(exc)[:2000])

        phase('LIVE_DELIVERY', self.wait)
        phase('LIVE_ARTIFACT_FAULTS', self.artifact_faults)
        phase('LIVE_FAILURE_SURFACE', self.failures)
        if self.args.merge_fixture or self.data.get('existing_issue'):
            phase('MERGE_AND_RECONCILE_REPLAY', self.merge)
        else:
            self.record('END_TO_END', 'INCOMPLETE', reason='Merge/reconciliation requires --merge-fixture')
            self.record('MERGE_AND_RECONCILE_REPLAY', 'INCOMPLETE', reason='--merge-fixture required')
        missing = {case: status for case, status in self.data['coverage'].items() if status != 'PASS'}
        check(not missing, 'Live campaign incomplete or failing; every independent case was executed: '
              + json.dumps(missing))
        self.data['end_to_end_passed'] = True
        self.save()

    def pipeline(self):
        """Drive the production door across its live sources; no selected issue or fixture."""
        from sovereign_discovery import discover

        self.data['mode'] = 'PIPELINE'
        user = self.api.api('user')
        control = self.api.api(f'repos/{self.control}')
        deployed = self.api.api(f'repos/{self.control}/commits/{control["default_branch"]}')['sha']
        check(not self.data.get('deployed_sha') or self.data['deployed_sha'] == deployed,
              'Deployment changed during campaign; start a fresh pipeline journal')
        self.data.update(account=user['login'], deployed_sha=deployed,
                         local_sha=self.command(['git', 'rev-parse', 'HEAD']).strip())
        self.save()
        try:
            self.intake()
        except (AssertionError, GitHubError) as exc:
            self.record('LIVE_INTAKE', 'FAIL', diagnostic=str(exc))

        # Surface production failures independently of whether entry or delivery
        # can advance. A failed surface remains a failed required case, while
        # the rest of the live campaign continues to collect real evidence.
        try:
            self.failures()
        except (AssertionError, GitHubError) as exc:
            self.record('LIVE_FAILURE_SURFACE', 'FAIL', diagnostic=str(exc))

        queue = self.folder / 'entry-queue'
        if self.data.get('continuations') and not self.data.get('pipeline_admitted'):
            retained = retained_admissions(queue, self.api)
            if retained:
                self.record('PIPELINE_ENTRY', 'PASS', queued_originals=len(retained),
                            source='retained admissions revalidated against live sources', issue_filter=None)
                self.data['pipeline_admitted'] = True
                self.save()
        if not self.data.get('pipeline_admitted'):
            self.record('PIPELINE_ENTRY', 'PENDING', issue_filter=None)
            settings = {'BOUNTY_ENTRY_DOOR': 'cline',
                        'BOUNTY_AGENT_WORKSPACE': str((self.folder / 'entry-scout').resolve()),
                        'BOUNTY_AGENT_TIMEOUT': str(self.args.model_timeout)}
            previous = {key: os.environ.get(key) for key in settings}
            os.environ.update(settings)
            try:
                result = discover(list(PRODUCTION_LANES),
                    max_dispatches=0, live=True, state_dir=queue,
                    api=self.api, store=StateStore(self.api, self.control))
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.data['entry_result'] = result
            self.save()
            with contextlib.closing(sqlite3.connect(queue / 'agent-queue.sqlite3')) as con:
                admitted = con.execute("SELECT count(*) FROM decisions WHERE disposition='capacity_wait'").fetchone()[0]
            self.record('PIPELINE_ENTRY', 'PASS' if admitted else 'FAIL',
                        result=result, queued_originals=admitted, issue_filter=None)
            check(admitted, 'Production entry door admitted no real candidate; downstream is unexercised')
            self.data['pipeline_admitted'] = True
            self.save()

        with contextlib.closing(sqlite3.connect(queue / 'agent-queue.sqlite3')) as con:
            rows = con.execute('SELECT task_id,payload,revision,disposition,at FROM decisions ORDER BY at,task_id').fetchall()
        cohort = self.data.setdefault('cohort', {})
        children = []

        def absorb(child):
            position = cohort[child.data['task_id']].get('events_read', 0)
            for event in child.data['events'][position:]:
                evidence = {key: value for key, value in event.items() if key not in ('case', 'status', 'at')}
                evidence.update(original=child.data['issue_url'], evidence_journal=str(child.path), source_at=event['at'])
                self.record(event['case'], event['status'], **evidence)
            cohort[child.data['task_id']]['events_read'] = len(child.data['events'])
            self.save()

        for identity, payload, revision, disposition, at in rows:
            if disposition != 'capacity_wait':
                continue
            row = json.loads(payload)
            member = cohort.setdefault(identity, {'repo': row['repo'], 'issue': row['issue']})
            args = SimpleNamespace(**{**vars(self.args), 'target': row['repo'], 'issue': row['issue'],
                                      'run_dir': self.folder / 'originals' / identity, 'merge_fixture': False})
            child = LiveRun(args)
            if self.data.get('continuations'):
                child.data['continuations'] = list(self.data['continuations'])
            if not child.data.get('admitted'):
                child.data.update(issue=row['issue'], issue_url=row['url'], task_id=identity, admitted=row)
                child_queue = child.folder / 'queue'
                child_queue.mkdir(exist_ok=True)
                with contextlib.closing(sqlite3.connect(child_queue / 'agent-queue.sqlite3')) as con:
                    con.execute('CREATE TABLE IF NOT EXISTS decisions(task_id TEXT PRIMARY KEY,payload TEXT,revision TEXT,disposition TEXT,at TEXT)')
                    con.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?)', (identity, payload, revision, disposition, at))
                    con.commit()
                child.data['queue_dir'] = str(child_queue.resolve())
                child.record('LIVE_MODEL_ADMISSION', 'PASS', production_entry_journal=str(self.path),
                             source_revision=row['admission']['source_revision'])
                child.record('LIVE_QUEUE_DEFERRAL', 'PASS', production_queue=str(queue), dispatch_budget=0)
            try:
                if child.data['coverage'].get('ENVIRONMENT') != 'PASS':
                    child.preflight()
                if not self.data.get('shared_faults_passed'):
                    child.faults()
                    if not child.data.get('negative_dispatch'):
                        child.negative_claim()
                    deadline = time.monotonic() + 600
                    while not child.data.get('negative_claim_passed') and time.monotonic() < deadline:
                        child.observe_negative()
                        if not child.data.get('negative_claim_passed'):
                            time.sleep(20)
                    check(child.data.get('negative_claim_passed'), 'Real invalid-generation observation timed out')
                    self.data['shared_faults_passed'] = True
                child.source_rejections()
                if not child.data.get('dispatch_id'):
                    child.dispatch()
                member['state'] = 'DISPATCHED'
                children.append(child)
            except (AssertionError, GitHubError, ValueError) as exc:
                member.update(state='BLOCKED', diagnostic=str(exc))
                self.record('PIPELINE_CANDIDATE', 'OBSERVED', original=row['url'], state='BLOCKED', diagnostic=str(exc))
            finally:
                absorb(child)
            # Same per-pass dispatch budget as the production discovery workflow.
            if len(children) >= 2:
                break
        check(children, 'No eligible original reached dispatch; candidate refusals retained')

        deadline = time.monotonic() + self.args.wait_minutes * 60
        while time.monotonic() < deadline:
            for child in children:
                member = cohort[child.data['task_id']]
                if member.get('state') == 'DELIVERED':
                    continue
                try:
                    state, _ = StateStore(self.api, self.control).read(child.data['task_id'])
                    if state and state.get('dispatch_id') and state['dispatch_id'] != child.data['dispatch_id']:
                        require_evidence(state, self.api.issue_context(child.target, child.data['issue']))
                        archive = child.folder / ('generation-' + child.data['dispatch_id'] + '.json')
                        archive.write_text(json.dumps(child.data, indent=2), encoding='utf-8')
                        child.data['admitted'].update(admission=state['admission'], competition=state['competition'],
                                                      sovereign_admission=state['sovereign_admission'])
                        child.data.update(dispatch_id=state['dispatch_id'], run_search_since=state['dispatched_at'],
                                          artifacts_downloaded=False, delivered_to_pr=False)
                        member.pop('release_faults_passed', None)
                        for name in ('ACTIONS_TERMINAL', 'REAL_PUBLICATION', 'ACTUAL_RELEASE_POSITIVE_CONTROL',
                                     'MERGE_AND_RECONCILE_REPLAY', *[case for case in REQUIRED_CASES if case.startswith('LIVE_RELEASE_')]):
                            child.record(name, 'PENDING', reason='Following actual production retry', dispatch_id=state['dispatch_id'])
                    child.observe()
                    if child.data.get('delivered_to_pr') and child.data.get('checks', {}).get('state') == 'PASSED':
                        if not member.get('release_faults_passed'):
                            child.artifact_faults()
                            member['release_faults_passed'] = True
                        pr = self.api.api(f'repos/{child.target}/pulls/{child.data["pr_number"]}')
                        if pr.get('merged'):
                            # This verifies a maintainer merge; never merges an upstream PR.
                            from actions_reconcile import reconcile
                            store = ScopedStore(self.api, self.control, [child.data['task_id']])
                            reconcile(repair=False, api=self.api, store=store)
                            first, _ = store.read(child.data['task_id'])
                            reconcile(repair=False, api=self.api, store=store)
                            second, _ = store.read(child.data['task_id'])
                            check(first['status'] == second['status'] == 'DELIVERED', 'Merge/replay did not settle')
                            check(second.get('payment_status') == 'UNVERIFIED', 'Merge was treated as payment')
                            child.record('MERGE_AND_RECONCILE_REPLAY', 'PASS', pr=pr['html_url'], payment='UNVERIFIED')
                            member['state'] = 'DELIVERED'
                        else:
                            member['state'] = 'AWAITING_MAINTAINER_MERGE'
                    member.pop('diagnostic', None)
                except (AssertionError, GitHubError, ValueError) as exc:
                    member.update(state='FAILED_OR_PENDING_RECOVERY', diagnostic=str(exc))
                    self.record('PIPELINE_MEMBER', 'FAIL', original=child.data['issue_url'], diagnostic=str(exc))
                finally:
                    absorb(child)
            if all(cohort[c.data['task_id']]['state'] == 'DELIVERED' for c in children):
                self.intake()
                missing = [case for case, status in self.data['coverage'].items() if status != 'PASS']
                check(not missing, f'Pipeline coverage incomplete: {missing}')
                self.data['end_to_end_passed'] = True
                self.save()
                return
            # Aggregate exit: every dispatched original is terminal, none owes a repair and none
            # is mid-flight, so there is nothing left to wait for. Production's own retry sweep
            # is the only actor that can change these records; while a repair obligation still
            # stands the ledger says so, and while a generation is running its status is active.
            # This is a gate over ledger facts, not a heuristic: a retry that arrives later is
            # still picked up by the deadline backstop and the next observation pass.
            terminal = [c for c in children if cohort[c.data['task_id']].get('state') not in
                        ('DELIVERED', 'AWAITING_MAINTAINER_MERGE')]
            if terminal and all(cohort[c.data['task_id']].get('state') == 'FAILED_OR_PENDING_RECOVERY'
                                for c in terminal):
                from actions_reconcile import repair_obligation
                records = [StateStore(self.api, self.control).read(c.data['task_id'])[0] for c in terminal]
                active = {'DISPATCHING', 'DISPATCHED', 'CLAIMED', 'ENGINEERING', 'VERIFIED', 'PUBLISHING'}
                if (not any(repair_obligation(r) for r in records)
                        and not any(r and str(r.get('status')) in active for r in records)):
                    self.record('END_TO_END', 'INCOMPLETE', cohort=cohort,
                                reason='Every dispatched original is terminal with no remaining repair obligation')
                    raise TimeoutError('All dispatched originals failed and none owes a repair; see per-original journals')
            self.save()
            time.sleep(20)
        self.record('END_TO_END', 'INCOMPLETE', cohort=cohort, reason='Live delivery/review deadline exhausted')
        raise TimeoutError('Pipeline remains incomplete; see per-original journals, without redispatching')


class Tee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def __getattr__(self, name):
        # Production modules configure stdout on Linux. Preserve the wrapped
        # stream interface (reconfigure, encoding, fileno, isatty), not just write.
        return getattr(self.stream, name)

    def write(self, value):
        self.log.write(value)
        self.log.flush()
        return self.stream.write(value)

    def flush(self):
        self.log.flush()
        self.stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['audit', 'provision', 'admit', 'dispatch', 'observe', 'merge', 'faults',
                                        'negative-claim', 'observe-negative', 'artifact-faults', 'cleanup', 'wait', 'run', 'intake', 'failures'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--resume-run', help='Restore a completed full master campaign before continuing')
    parser.add_argument('--target', default='isearchxsolve/oss-hunter-livefire')
    parser.add_argument('--control', default='isearchxsolve/bounty-control')
    parser.add_argument('--issue', type=int, help='Use this existing original issue instead of provisioning a sandbox issue')
    parser.add_argument('--model-timeout', type=int, default=600)
    parser.add_argument('--gateway', choices=['existing', 'isolated'], default='isolated')
    parser.add_argument('--engineering-budget', type=int, default=1800)
    parser.add_argument('--wait-minutes', type=int, default=60)
    parser.add_argument('--intake-max-age-minutes', type=int, default=90)
    parser.add_argument('--merge-fixture', action='store_true')
    args = parser.parse_args()
    check(args.model_timeout > 0 and args.engineering_budget > 0 and args.wait_minutes > 0
          and args.intake_max_age_minutes > 0, 'Budgets must be positive')
    if args.resume_run:
        check(args.phase == 'run' and args.issue is None, 'Checkpoint resume keeps the full unfiltered campaign')
        from live_pipeline_resume import restore_campaign
        restore_campaign(args.resume_run, args.run_dir, args.control, args.target)
    run = LiveRun(args)
    log_path = run.folder / f'{args.phase}-{time.time_ns()}.log'
    with log_path.open('w', encoding='utf-8') as log, \
            contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
        try:
            getattr(run, args.phase.replace('-', '_'))()
        except Exception as exc:
            run.record(args.phase.upper(), 'FAIL', error=type(exc).__name__, diagnostic=str(exc)[:2000])
            return 1
        finally:
            run.publish_progress(force=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
