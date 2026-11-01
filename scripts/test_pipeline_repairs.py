"""Cross-boundary forensic regressions. All transport and model execution are offline."""
import copy
import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
import subprocess

import actions_delivery as delivery
import actions_dispatch as dispatch
from actions_github import GitHub, GitHubError, StateStore, task_id
from actions_reconcile import reconcile, sweep_stale_runs
import cline_entry_door as door
from kaggle_engine_worker import VerificationPlan
from pipeline_evidence import bind_proof, digest, require_evidence
from sovereign_discovery import discover


def context():
    return {"repo": "acme/http", "issue_number": 7, "title": "Retry fails", "body": "Fix src/retry.py",
            "issue": {"state": "open", "title": "Retry fails", "body": "Bounty $250. Fix src/retry.py"},
            "comments": [], "complete_comments": True,
            "repository": {"full_name": "acme/http", "default_branch": "main"}}


def row(ctx=None):
    ctx = ctx or context()
    return {"repo": ctx["repo"], "issue": ctx["issue_number"], "lane": "bounty", "source_lane": "normal",
            "sovereign_admission": True,
            "admission": bind_proof({"funding": {"amount": "250", "usd_value": "250"}}, ctx),
            "competition": {"blocking": False, "nominal": []}}


class Transport:
    def __init__(self): self.posts = []
    def api(self, endpoint, method="GET", data=None, **kwargs):
        if endpoint.endswith('/dispatches'):
            self.posts.append(data)
            return None
        return {"size": 10}
    def issue_context(self, repo, number): return context()
    def workflow_runs(self, repo, status=None): return []


class Store(StateStore):
    def __init__(self):
        self.repo = "unit/control"
        self.rows = {}
    def mutate(self, identity, change):
        result = change(copy.deepcopy(self.rows.get(identity)))
        result['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.rows[identity] = result
        return result
    def read(self, identity): return copy.deepcopy(self.rows.get(identity)), None
    def records(self): return list(copy.deepcopy(self.rows).values())


class DispatchOwnershipTests(unittest.TestCase):
    def test_old_unbound_refusal_requires_explicit_model_reconsideration(self):
        api,store,r=Transport(),Store(),row()
        identity=task_id('acme/http',7)
        store.rows[identity]={'status':'REJECTED_PREPARATION','attempt':1,'updated_at':'old-revision'}
        with self.assertRaisesRegex(ValueError,'Existing durable'):
            dispatch.dispatch(api,store,context(),r['admission'],['normal'],competition=r['competition'])
        r['admission']['reconsideration']={'previous_updated_at':'old-revision',
                                          'reason':'Read original diagnosis and current source'}
        dispatch.dispatch(api,store,context(),r['admission'],['normal'],competition=r['competition'])
        self.assertEqual(len(api.posts),1)
    def test_pending_dispatch_is_not_sent_twice(self):
        api, store, r = Transport(), Store(), row()
        dispatch.dispatch(api, store, context(), r['admission'], ['normal'], competition=r['competition'])
        with self.assertRaisesRegex(ValueError, 'Existing durable'):
            dispatch.dispatch(api, store, context(), r['admission'], ['normal'], competition=r['competition'])
        self.assertEqual(len(api.posts), 1)
        self.assertEqual(next(iter(store.rows.values()))['attempt'], 0)

    def test_old_generation_cannot_claim_new_dispatch(self):
        store = Store()
        identity = task_id('acme/http', 7)
        store.rows[identity] = {'dispatch_id': 'new', 'status': 'DISPATCHED', 'attempt': 0}
        with self.assertRaisesRegex(ValueError, 'generation mismatch'):
            store.claim('acme/http', 7, '123:1', 'url', 'sha', dispatch_id='old')

    def test_revoked_owner_cannot_resume_publication(self):
        store = Store()
        identity = task_id('acme/http', 7)
        store.rows[identity] = {'owner': '123:1', 'owner_revoked': '123:1', 'status': 'FAILED_RUNNER_SHUTDOWN'}
        with self.assertRaisesRegex(ValueError, 'ownership lost'):
            store.owned_update(identity, '123:1', status='PUBLISHING')
        with self.assertRaisesRegex(ValueError, 'ownership lost'):
            store.assert_owner(identity, '123:1')

    def test_changed_refusal_is_reconsidered_without_erasing_history(self):
        api, store, r = Transport(), Store(), row()
        identity = task_id('acme/http', 7)
        store.rows[identity] = {'status': 'REJECTED_PREPARATION', 'attempt': 1,
                                'admission': {'source_revision': 'old'}, 'reason': 'old evidence'}
        dispatch.dispatch(api, store, context(), r['admission'], ['normal'], competition=r['competition'])
        self.assertEqual(store.rows[identity]['refusal_history'][0]['reason'], 'old evidence')


class EvidenceAndHandoffTests(unittest.TestCase):
    def test_real_offer_and_source_author_do_not_require_a_second_authority_quote(self):
        ctx=context()
        ctx['issue'].update(html_url='url',user={'login':'maintainer'},author_association='COLLABORATOR')
        candidate={'repo':'acme/http','issue':7,'reward_quote':'Bounty $250.',
            'scope_quote':'Fix src/retry.py','admission_reason':'Maintainer offers payment for the described change',
            'funding':{'amount':'250','currency':'USD','payer':'maintainer','source_url':'url'},
            'code_evidence':{'path':'src/retry.py','sha':'a'*40,'quote':'def retry():','is_product_code':True}}
        blob={'type':'file','sha':'a'*40,'encoding':'base64','content':base64.b64encode(b'def retry():\n    pass\n').decode()}
        reason,_,proof=door.model_admission_refusal(candidate,lambda *a:ctx,source_reader=lambda *a:blob)
        self.assertIsNone(reason)
        self.assertEqual(proof['funding']['source_author_association'],'COLLABORATOR')
        self.assertEqual(proof['funding']['source_author_login'],'maintainer')
        candidate['funding']['payer']='someone-else'
        reason,_,proof=door.model_admission_refusal(candidate,lambda *a:ctx,source_reader=lambda *a:blob)
        self.assertEqual(reason,'PAYER_SOURCE_MISMATCH')
        self.assertIsNone(proof)

    def test_model_path_preserves_unpriced_owner_incidents_without_inventing_payment(self):
        ctx=context()
        statement='Production retry is failing; fix src/retry.py.'
        ctx['issue'].update(body=statement,html_url='https://github.com/acme/http/issues/7',
                            author_association='OWNER',user={'login':'owner'})
        candidate={'repo':'acme/http','issue':7,'is_code_task':True,'is_founder_wound':True,
            'reward_quote':statement,'scope_quote':'fix src/retry.py.',
            'admission_reason':'Owner reports the current failure and requests a bounded source fix',
            'funding':{'source_url':ctx['issue']['html_url'],'payer':'owner','authority_quote':statement},
            'code_evidence':{'path':'src/retry.py','sha':'a'*40,'quote':'def retry():','is_product_code':True}}
        blob={'type':'file','sha':'a'*40,'encoding':'base64','content':base64.b64encode(b'def retry():\n    pass\n').decode()}
        api=SimpleNamespace(pages=lambda *a,**k:[])
        with patch.object(GitHub,'api',return_value=blob):
            result=door.verify_model_rows([candidate],fetch=lambda *a:ctx['issue'],
                                         context_builder=lambda *a:ctx,admission_client=api)
        self.assertEqual(len(result['admitted']),1)
        proof=result['admitted'][0]['admission']
        self.assertEqual(proof['funding_status'],'UNPRICED_OWNER_REQUEST')
        self.assertEqual(proof['funding']['currency'],'FOUNDER')
        require_evidence(result['admitted'][0],ctx)
        ctx['issue']['author_association']='NONE'
        reason,_,_=door.model_admission_refusal(candidate,lambda *a:ctx)
        self.assertEqual(reason,'FOUNDER_OWNERSHIP_UNVERIFIED')

    def test_production_door_checks_model_citations_without_regex_readmission(self):
        ctx = context()
        ctx['issue'].update(html_url='https://github.com/acme/http/issues/7', user={'login':'payer'})
        candidate = {'repo':'acme/http','issue':7,'is_code_task':True,'reward_quote':'Bounty $250.',
            'scope_quote':'Fix src/retry.py','admission_reason':'Read current payer commitment and bounded source change',
            'funding':{'amount':'250','currency':'USD','payer':'payer',
                       'source_url':ctx['issue']['html_url'],'authority_quote':'Bounty $250.'}}
        candidate['code_evidence']={'path':'src/retry.py','sha':'a'*40,'quote':'def retry():','is_product_code':True}
        api = SimpleNamespace(pages=lambda *a, **k: [])
        blob={'type':'file','sha':'a'*40,'encoding':'base64','content':base64.b64encode(b'def retry():\n    pass\n').decode()}
        with patch('bounty_admission.admit', side_effect=AssertionError('second judgement')), \
             patch.object(GitHub,'api',return_value=blob):
            result = door.verify_model_rows([candidate], fetch=lambda *a:ctx['issue'],
                context_builder=lambda *a:ctx, admission_client=api)
        self.assertEqual(len(result['admitted']),1)
        require_evidence(result['admitted'][0],ctx)
        candidate['funding']['payer']='stranger'
        result=door.verify_model_rows([candidate],fetch=lambda *a:ctx['issue'],
            context_builder=lambda *a:ctx,admission_client=api)
        self.assertEqual(result['refused'][0]['reason'],'PAYER_SOURCE_MISMATCH')

    def test_empty_repository_cannot_satisfy_model_source_claim(self):
        ctx=context(); ctx['issue'].update(html_url='url',user={'login':'payer'})
        candidate={'repo':'acme/http','issue':7,'reward_quote':'Bounty $250.',
            'scope_quote':'Fix src/retry.py','admission_reason':'Inspect the implementation',
            'funding':{'amount':'250','currency':'USD','payer':'payer','source_url':'url','authority_quote':'Bounty $250.'}}
        reason,_,proof=door.model_admission_refusal(candidate,lambda *a:ctx)
        self.assertEqual(reason,'PRODUCT_SOURCE_EVIDENCE_MISSING')
        self.assertIsNone(proof)

    def test_missing_provenance_never_becomes_approval(self):
        with self.assertRaises(ValueError): delivery.sovereign_admission({}, {})
        with self.assertRaises(ValueError): delivery.sovereign_competition({}, {})
        with self.assertRaises(ValueError): require_evidence({'sovereign_admission': False})

    def test_source_change_requires_agent_reconsideration(self):
        ctx, r = context(), row()
        ctx['comments'].append({'body': 'Funding withdrawn'})
        with self.assertRaisesRegex(ValueError, 'source changed'):
            require_evidence(r, ctx)

    def test_streamed_row_dispatches_before_search_returns_and_claim_preserves_proof(self):
        api, store, r = Transport(), Store(), row()
        def finder(**kwargs):
            kwargs['on_admitted'](r)
            self.assertEqual(len(api.posts), 1, 'handoff must happen during the agent turn')
            return {'rows': [r], 'refused': [], 'reason': 'OK'}
        with tempfile.TemporaryDirectory() as tmp:
            result = discover(['normal'], 2, True, tmp, finder=finder, api=api, store=store)
            self.assertEqual(len(result['dispatched']), 1)
            payload = api.posts[0]['client_payload']
            event = Path(tmp) / 'event.json'
            event.write_text(json.dumps({'client_payload': payload}))
            with patch.dict(os.environ, {'FLEET_ARTIFACT_DIR': tmp, 'GITHUB_RUN_ID': '123',
                 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'f'*40, 'GITHUB_OUTPUT': str(Path(tmp)/'outputs')}):
                with patch.object(delivery, 'GitHub', return_value=api), patch.object(delivery, 'StateStore', return_value=store), patch.object(delivery, 'competition'):
                    delivery.claim(event)
            claim = json.loads((Path(tmp)/'claim.json').read_text())
            self.assertEqual(claim['context']['admission'], r['admission'])
            self.assertEqual(payload['competition'], r['competition'])

    def test_quiet_cycle_still_writes_receipt_and_census(self):
        with tempfile.TemporaryDirectory() as tmp:
            discover(['normal'], state_dir=tmp, finder=lambda **kw: {'rows': [], 'reason': 'NO_ROWS'},
                     api=Transport(), store=Store())
            self.assertTrue((Path(tmp)/'receipts.jsonl').exists())
            self.assertTrue((Path(tmp)/'census.jsonl').exists())

    def test_partition_does_not_change_model_selected_lane(self):
        r = row(); r['source_lane'] = 'programs'
        api = Transport()
        with tempfile.TemporaryDirectory() as tmp:
            result = discover(['programs'], 2, True, tmp,
                finder=lambda **kw: {'rows': [r]}, api=api, store=Store())
        self.assertEqual(len(result['dispatched']), 1)
        self.assertEqual(api.posts[0]['client_payload']['lanes'], ['programs'])


class SearchRepairTests(unittest.TestCase):
    def test_issue_age_uses_utc_and_honors_source_timezone_offset(self):
        now=datetime(2026,1,3,tzinfo=timezone.utc).timestamp()
        self.assertEqual(door.issue_age_days({'updated_at':'2026-01-02T05:30:00+05:30'},now),1)
        self.assertEqual(door.issue_age_days({'updated_at':'2026-01-02T00:00:00Z'},now),1)

    def test_stream_rewrite_longer_than_old_file_is_read_from_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shortlist.jsonl'
            path.write_text('{"issue":1}\n')
            stream=door.ShortlistStream(path)
            self.assertEqual(stream.read()[0]['issue'],1)
            path.write_text('{"issue":2,"reason":"replacement is longer"}\n')
            self.assertEqual(stream.read()[0]['issue'],2)

    def test_corrected_quote_is_reverified_and_prior_refusal_cleared(self):
        calls, turns = [], []
        def verify(rows, **kwargs):
            calls.extend(rows)
            return {'admitted': [r for r in rows if r['reward_quote']=='fixed'],
                    'refused': [{'row':r,'reason':'BAD_QUOTE'} for r in rows if r['reward_quote']!='fixed'], 'unpriced': []}
        def run(workdir, prompt, on_row, **kw):
            current = {'repo':'acme/http','issue':7,'reward_quote':'bad' if not turns else 'fixed'}
            turns.append(current); on_row(current)
            return {'rows':[current], 'exit_code':0}
        with tempfile.TemporaryDirectory() as tmp:
            result = door.iterate(tmp, rounds=2, run=run, verify=verify)
            self.assertEqual(len((Path(tmp)/'decisions.jsonl').read_text().splitlines()), 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['admitted'][0]['reward_quote'], 'fixed')
        self.assertEqual(result['refused'], [])


class RecoveryTests(unittest.TestCase):
    def test_search_throttle_does_not_wait_for_an_unrelated_core_reset(self):
        limits={'resources':{'search':{'remaining':1,'reset':100},'core':{'remaining':0,'reset':1000}}}
        done=subprocess.CompletedProcess([],0,json.dumps(limits).encode(),b'')
        environment={'GH_TOKEN':'unit-transport-token'}
        with patch('actions_github.subprocess.run',return_value=done) as run:
            self.assertEqual(GitHub.rate_limit_wait('search/issues?q=x','rate limit exceeded',environment),65)
        self.assertEqual(run.call_args.kwargs['env'],environment)

    def test_throttle_cannot_sleep_past_observation_deadline(self):
        denied=subprocess.CompletedProcess([],1,b'',b'API rate limit exceeded')
        limits=subprocess.CompletedProcess([],0,json.dumps({'resources':{
            'core':{'remaining':0,'reset':1000}}}).encode(),b'')
        api=GitHub(deadline=20)
        with patch('actions_github.subprocess.run',side_effect=[denied,limits]), \
             patch('actions_github.time.monotonic',return_value=0), \
             patch('actions_github.time.time',return_value=0), patch('actions_github.time.sleep') as sleep:
            with self.assertRaisesRegex(GitHubError,'remaining observation budget'):
                api.api('repos/unit/control')
        sleep.assert_not_called()

    def test_cached_capacity_fact_is_applied_without_another_probe(self):
        payload=json.dumps({'repository_url':'https://api.github.com/repos/acme/http'})
        cache={}
        with patch.object(dispatch,'repository_size_kb',side_effect=AssertionError('unnecessary probe')):
            excluded=dispatch.capacity_exclusions(None,[('task',payload)],cache,
                known={'acme/http':(dispatch.CAPACITY_MAX_REPOSITORY_KB+1, __import__('time').time())})
        self.assertEqual(excluded,{'acme/http'})

    def test_native_commands_share_the_delivery_deadline(self):
        import kaggle_engine_worker as worker
        from delivery_errors import ClineBudgetExhausted
        with patch.object(worker,'_CLINE_EXECUTION_DEADLINE',11), patch.object(worker.time,'monotonic',return_value=10), \
             patch.object(worker,'run_streamed_process',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            worker.run_command_safe(['native','test'],'.',timeout=3600)
            self.assertEqual(run.call_args.kwargs['timeout'],1)
        with patch.object(worker,'_CLINE_EXECUTION_DEADLINE',9), patch.object(worker.time,'monotonic',return_value=10):
            with self.assertRaises(ClineBudgetExhausted): worker.run_command_safe(['native','test'],'.')

    def test_credential_scan_reports_locations_without_values(self):
        from check_tracked_secrets import scan
        with tempfile.TemporaryDirectory() as tmp:
            credential='github_'+'pat_'+'x'*70
            (Path(tmp)/'fixture.py').write_text('token='+repr(credential))
            with patch('check_tracked_secrets.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'fixture.py\0',b'')):
                findings=scan(Path(tmp))
            self.assertEqual(findings[0]['line'],1)
            self.assertNotIn(credential,json.dumps(findings))
    def test_rejected_cancellation_never_releases_live_owner(self):
        store = Store(); identity = 'a'*32
        store.rows[identity] = {'task_id':identity,'owner':'123:1','status':'ENGINEERING',
            'claimed_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}
        class API:
            def api(self, endpoint, method='GET', data=None):
                if method=='POST': raise GitHubError('403 forbidden')
                return {'status':'in_progress'}
        self.assertEqual(sweep_stale_runs(API(), store, 1, 0), [])
        self.assertEqual(store.rows[identity]['status'], 'ENGINEERING')

    def test_unconfirmed_cancellation_never_releases_live_owner(self):
        store = Store(); identity = 'a'*32
        store.rows[identity] = {'task_id':identity,'owner':'123:1','status':'ENGINEERING',
            'claimed_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}
        api = SimpleNamespace(api=lambda *a, **k: {'status':'in_progress'})
        self.assertEqual(sweep_stale_runs(api, store, 1, 0), [])

    def test_publication_failure_has_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'engineering-result.json').write_text('{"status":"VERIFIED"}')
            (Path(tmp)/'publish-failure.json').write_text('{"status":"FAILED_PUBLISH","diagnostic":"timeout"}')
            self.assertEqual(delivery.terminal_result(tmp,'failure')['diagnostic'], 'timeout')

    def test_malformed_task_does_not_stop_later_reconciliation(self):
        store = Store()
        store.rows['bad'] = {'task_id':'bad','status':'DISPATCHED'}
        store.rows['good'] = {'task_id':'good','status':'CLAIMED','owner':'123:1'}
        api = SimpleNamespace(api=lambda *a: {'status':'completed','conclusion':'failure','html_url':'url'})
        receipts = reconcile(api=api,store=store)
        self.assertTrue(any(r.get('phase')=='RECONCILE_DEFERRED' for r in receipts))
        self.assertEqual(store.rows['good']['status'], 'FAILED_MISSING_TERMINAL_RECEIPT')

    def test_bundle_uses_execution_receipts_without_second_model_approval(self):
        """A new regression target needs no pre-implementation approval stamp."""
        plan = VerificationPlan(builds=[['mix','compile']],
            baseline_tests=[['mix','test','existing_test.exs']],
            final_tests=[['mix','test','new_regression_test.exs']])
        commands = plan.builds + plan.baseline_tests + plan.final_tests
        receipt = {'status':'VERIFIED', 'harness_sha':'harness',
            'repo':'acme/http', 'issue_number':7, 'task_id':task_id('acme/http',7),
            'head_sha':'head', 'base_sha':'base', 'tree_sha':'tree',
            'files':{'src/retry.py':{'sha256':digest('unused')}},
            'sources':[], 'plan':asdict(plan),
            'baseline':[{'argv':plan.baseline_tests[0], 'exit_code':0, 'stdout':'1 test passed'}],
            'verification':[{'argv':c, 'exit_code':0, 'stdout':'1 test passed'} for c in commands],
            'regression':{'red_exit':1, 'green_exit':0}}
        import hashlib
        receipt['files']['src/retry.py']['sha256'] = hashlib.sha256(b'fixed').hexdigest()
        def git_result(root, *args, **kwargs):
            values = {('rev-parse','FETCH_HEAD'):b'head',
                ('rev-list','--count','base..head'):b'1',
                ('show','-s','--format=%P','head'):b'base',
                ('rev-parse','head^{tree}'):b'tree',
                ('diff','--name-only','-z','base','head'):b'src/retry.py\0',
                ('show','head:src/retry.py'):b'fixed',
                ('ls-tree','head','--','src/retry.py'):b'100644 blob content'}
            return SimpleNamespace(stdout=values.get(args,b''),returncode=0)
        with patch.dict(os.environ,{'GITHUB_SHA':'harness'}), \
                patch.object(delivery.subprocess,'run'), \
                patch.object(delivery,'git',side_effect=git_result), \
                patch.object(delivery,'protect_baseline_tests'):
            self.assertEqual(delivery.validate_bundle(receipt,'bundle',Path('checkout')),
                             ('acme/http',7,'head'))
            receipt['verification'][-1]['exit_code'] = 1
            with self.assertRaisesRegex(ValueError,'native command failed'):
                delivery.validate_bundle(receipt,'bundle',Path('checkout'))

    def test_workflow_run_pagination_is_complete(self):
        api = GitHub()
        calls=[]
        def get(endpoint):
            calls.append(endpoint)
            page = parse_qs(endpoint.split('?')[1])['page'][0]
            return {'workflow_runs':[{'id':i} for i in range(100)] if page == '1' else [{'id':100}]}
        api.api=get
        self.assertEqual(len(api.workflow_runs('unit/control')),101)
        self.assertEqual(len(calls),2)


class DeliverySideObservationTests(unittest.TestCase):
    """Measured 2026-11-01: the pipeline could not see a held workflow or a reviewer verdict.

    15 of 18 open PRs had no executed checks, and two repositories returned action_required on
    every run. Both facts were invisible: action_required was folded into PENDING, so a PR
    waiting on a human read as "CI still running" and never aged into an obligation. Separately,
    blackball#182 carried CHANGES_REQUESTED and fyne#6637 a reviewer report of a failing native
    check, and no pipeline record held either.
    """

    def test_workflow_held_for_approval_is_not_pending(self):
        from actions_reconcile import classify_checks
        api = GitHub()
        api.api = lambda endpoint: {'check_runs': [
            {'id': 1, 'name': 'CI', 'status': 'completed', 'conclusion': 'action_required',
             'app': {'id': 7}}]}
        api.pages = lambda endpoint: []
        proof = classify_checks(api, 'unit/control', 'a' * 40)
        self.assertEqual(proof['state'], 'HELD')
        self.assertEqual(len(proof['held']), 1)
        # A held workflow is not a failure: it never ran, so nothing failed.
        self.assertEqual(proof['failures'], [])

    def test_running_workflow_is_still_pending(self):
        from actions_reconcile import classify_checks
        api = GitHub()
        api.api = lambda endpoint: {'check_runs': [
            {'id': 1, 'name': 'CI', 'status': 'in_progress', 'conclusion': None,
             'app': {'id': 7}}]}
        api.pages = lambda endpoint: []
        self.assertEqual(classify_checks(api, 'unit/control', 'a' * 40)['state'], 'PENDING')

    def test_changes_requested_becomes_a_durable_obligation(self):
        from actions_reconcile import review_verdict
        api = GitHub()
        api.pages = lambda endpoint: [
            {'state': 'COMMENTED', 'user': {'login': 'first'}, 'submitted_at': '2026-10-27T00:00:00Z'},
            {'state': 'CHANGES_REQUESTED', 'user': {'login': 'reviewer'},
             'submitted_at': '2026-10-31T19:58:48Z'}]
        verdict = review_verdict(api, 'unit/control', 182)
        self.assertEqual(verdict['verdict'], 'CHANGES_REQUESTED')
        self.assertEqual(verdict['review_count'], 2)
        self.assertEqual(verdict['latest_reviewer'], 'reviewer')

    def test_no_reviews_is_not_an_approval(self):
        from actions_reconcile import review_verdict
        api = GitHub()
        api.pages = lambda endpoint: []
        verdict = review_verdict(api, 'unit/control', 1)
        self.assertEqual(verdict['verdict'], 'NONE')
        self.assertEqual(verdict['review_count'], 0)

    def test_failed_claim_is_retried(self):
        from actions_reconcile import retry_claim
        posted = []
        api = GitHub()
        api.api = lambda endpoint, method=None, payload=None: posted.append((endpoint, payload))
        result = retry_claim(api, {'repo': 'unit/control', 'pr_number': 182,
                                   'claim_command': '/claim #182', 'claim_retry_required': True})
        self.assertEqual(result['claim_retry'], 'SUBMITTED_UNCONFIRMED')
        self.assertFalse(result['claim_retry_required'])
        self.assertEqual(posted[0][1]['body'], '/claim #182')

    def test_unconfirmed_claim_is_not_reposted(self):
        # An unconfirmed submission may already have been read by the platform; a second
        # identical command is noise on someone else's PR.
        from actions_reconcile import retry_claim
        posted = []
        api = GitHub()
        api.api = lambda endpoint, method=None, payload=None: posted.append(endpoint)
        self.assertIsNone(retry_claim(api, {'repo': 'unit/control', 'pr_number': 1,
                                            'claim_command': '/claim #1',
                                            'claim_retry_required': False}))
        self.assertEqual(posted, [])

    def test_change_request_is_retryable_but_a_merge_is_not(self):
        from actions_dispatch import retry_eligible
        self.assertTrue(retry_eligible({'status': 'CHANGES_REQUESTED'}))
        self.assertTrue(retry_eligible({'status': 'FAILED_REMOTE_CHECKS'}))
        self.assertFalse(retry_eligible({'status': 'DELIVERED'}))
        self.assertFalse(retry_eligible({'status': 'AWAITING_REVIEW'}))

    def test_change_request_can_be_claimed_again(self):
        # The claim gate refuses a PR that is merely pending, but a reviewer's change request is
        # exactly the case where another engineering run is the right next step.
        store = Store()
        store.claim('unit/control', 182, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 182),
                     lambda old: {**old, 'status': 'CHANGES_REQUESTED'})
        claimed = store.claim('unit/control', 182, '1:1', 'run', 'sha')
        self.assertEqual(claimed['status'], 'CLAIMED')


class EndToEndFlowTests(unittest.TestCase):
    """Every non-terminal status must have a path forward, all the way to DELIVERED.

    Measured 2026-11-01: the pipeline could publish a PR and then never reach a terminal
    outcome. Three separate dead ends existed at once -- a held workflow read as "still
    running", a reviewer's CHANGES_REQUESTED was refused by the claim gate, and a failed claim
    was recorded as an obligation that nothing ever retried. Each looked fine in isolation and
    together they meant a published PR could sit forever.

    This walks the chain and asserts each link exists, so a future change that reintroduces a
    dead end fails here instead of in production.
    """

    # Statuses from which no further progress is expected or possible.
    TERMINAL = {'DELIVERED', 'CLOSED_UNMERGED'}

    def test_every_status_is_terminal_or_has_a_way_forward(self):
        from actions_dispatch import retry_eligible
        from actions_reconcile import classify_checks, review_verdict

        # The forward path, in order, that a healthy task takes.
        chain = ['DISPATCHED', 'CLAIMED', 'ENGINEERING', 'VERIFIED', 'PUBLISHING',
                 'PUBLISHED_PENDING_CHECKS', 'AWAITING_REVIEW', 'DELIVERED']
        self.assertEqual(chain[-1], 'DELIVERED')

        # A reviewer's change request must be reachable from the review observation and must
        # itself be retryable, or the chain ends at the first human who asks for a change.
        api = GitHub()
        api.pages = lambda endpoint: [{'state': 'CHANGES_REQUESTED', 'user': {'login': 'r'},
                                       'submitted_at': '2026-10-31T19:58:48Z'}]
        self.assertEqual(review_verdict(api, 'unit/control', 1)['verdict'], 'CHANGES_REQUESTED')
        self.assertTrue(retry_eligible({'status': 'CHANGES_REQUESTED'}))

        # A held workflow must be observable as held rather than as a run in progress.
        api.api = lambda endpoint: {'check_runs': [
            {'id': 1, 'name': 'CI', 'status': 'completed', 'conclusion': 'action_required',
             'app': {'id': 1}}]}
        api.pages = lambda endpoint: []
        self.assertEqual(classify_checks(api, 'unit/control', 'a' * 40)['state'], 'HELD')

        # The terminal states must refuse further work, or "delivered" is not terminal.
        for status in self.TERMINAL:
            self.assertFalse(retry_eligible({'status': status}), status)

    def test_change_request_survives_the_claim_gate(self):
        store = Store()
        store.claim('unit/control', 7, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 7),
                     lambda old: {**old, 'status': 'CHANGES_REQUESTED'})
        # Reachable: the engineer can pick the work back up.
        self.assertEqual(store.claim('unit/control', 7, '1:1', 'run', 'sha')['status'], 'CLAIMED')

    def test_merge_records_payment_as_unverified_not_paid(self):
        # A merge is not a payment. The chain must end at DELIVERED with payment still unknown.
        from actions_reconcile import reconcile
        api = GitHub()
        api.api = lambda endpoint, method=None, payload=None: {
            'head': {'sha': 'a' * 40}, 'merged': True, 'merged_at': '2026-11-01T00:00:00Z',
            'html_url': 'https://example.invalid/pr/1', 'state': 'closed'}
        api.pages = lambda endpoint, **kw: []
        store = Store()
        store.claim('unit/control', 7, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 7), lambda old: {
            **old, 'status': 'AWAITING_REVIEW', 'pr_number': 1, 'head_sha': 'a' * 40,
            'proposed_head': 'a' * 40})
        reconcile(repair=False, api=api, store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'DELIVERED')
        self.assertEqual(record['payment_status'], 'UNVERIFIED')


    def test_every_status_the_loop_writes_is_observed(self):
        """A status the reconcile loop writes but does not observe is a terminal state by accident.

        This is the exact defect the previous commit introduced: CHECKS_HELD_FOR_APPROVAL and
        CHANGES_REQUESTED were written by the observation branch, which is gated on the status
        the record already had. Neither new status was in that gate, so both were written once
        and never read again -- silently terminal, and invisible to the very loop meant to
        rescue them.
        """
        from actions_reconcile import PR_OBSERVATION_STATUSES

        # Every status this loop can write back to a record that still has an open PR.
        written = {'PUBLISHED_PENDING_CHECKS', 'AWAITING_REVIEW', 'FAILED_REMOTE_CHECKS',
                   'CHECKS_HELD_FOR_APPROVAL', 'CHANGES_REQUESTED', 'BLOCKED_HEAD_CHANGED'}
        for status in written - {'BLOCKED_HEAD_CHANGED'}:
            self.assertIn(status, PR_OBSERVATION_STATUSES,
                          status + ' is written but never observed')

    def test_held_pr_progresses_on_the_next_pass(self):
        # End to end: a held PR must be re-observed, and must reach DELIVERED when merged.
        from actions_reconcile import reconcile
        store = Store()
        store.claim('unit/control', 7, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 7), lambda old: {
            **old, 'status': 'CHECKS_HELD_FOR_APPROVAL', 'pr_number': 1,
            'head_sha': 'a' * 40, 'proposed_head': 'a' * 40})

        seen = []

        def api_call(endpoint, method=None, payload=None):
            seen.append(endpoint)
            return {'head': {'sha': 'a' * 40}, 'merged': True,
                    'merged_at': '2026-11-01T00:00:00Z',
                    'html_url': 'https://example.invalid/pr/1', 'state': 'closed'}

        api = GitHub()
        api.api = api_call
        api.pages = lambda endpoint, **kw: []
        reconcile(repair=False, api=api, store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'DELIVERED')
        self.assertTrue(any('/pulls/1' in e for e in seen),
                        'the held PR was never read back from GitHub')

    def test_change_requested_pr_is_re_observed(self):
        from actions_reconcile import reconcile
        store = Store()
        store.claim('unit/control', 8, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 8), lambda old: {
            **old, 'status': 'CHANGES_REQUESTED', 'pr_number': 2,
            'head_sha': 'b' * 40, 'proposed_head': 'b' * 40})
        api = GitHub()
        api.api = lambda endpoint, method=None, payload=None: {
            'head': {'sha': 'b' * 40}, 'merged': False, 'state': 'open',
            'html_url': 'https://example.invalid/pr/2'}
        api.pages = lambda endpoint, **kw: []
        reconcile(repair=False, api=api, store=store)
        record, _ = store.read(task_id('unit/control', 8))
        # Still observed, still actionable: it must not have been frozen as terminal.
        self.assertIn(record['status'], ('CHANGES_REQUESTED', 'AWAITING_REVIEW',
                                         'PUBLISHED_PENDING_CHECKS',
                                         'CHECKS_HELD_FOR_APPROVAL'))


class FullLifecycleTests(unittest.TestCase):
    """Walk one task from dispatch to DELIVERED through the real reconcile loop.

    The graph tests prove no status is an orphan. This proves the loop actually moves a task
    from one end to the other, including the two states that used to strand it: a CI held for
    maintainer approval, and a reviewer asking for changes.
    """

    def _store_with(self, status, **extra):
        store = Store()
        store.claim('unit/control', 7, '1:1', 'run', 'sha')
        store.mutate(task_id('unit/control', 7), lambda old: {
            **old, 'status': status, 'pr_number': 1, 'head_sha': 'a' * 40,
            'proposed_head': 'a' * 40, **extra})
        return store

    def _api(self, *, merged=False, state='open', conclusion='success', reviews=()):
        class Api:
            def api(self, endpoint, method=None, payload=None):
                if '/pulls/1' in endpoint and '/reviews' not in endpoint:
                    return {'head': {'sha': 'a' * 40}, 'merged': merged,
                            'merged_at': '2026-11-01T00:00:00Z' if merged else None,
                            'html_url': 'https://example.invalid/pr/1', 'state': state}
                return {'check_runs': [{'id': 1, 'name': 'CI', 'status': 'completed',
                                        'conclusion': conclusion, 'app': {'id': 1}}]}

            def pages(self, endpoint, **kw):
                if '/reviews' in endpoint:
                    return [{'state': s, 'user': {'login': 'r'},
                             'submitted_at': '2026-11-01T00:00:00Z'} for s in reviews]
                return []
        return Api()

    def test_held_ci_then_merge_reaches_delivered(self):
        from actions_reconcile import reconcile
        store = self._store_with('PUBLISHED_PENDING_CHECKS')

        # Pass 1: CI is held for maintainer approval. The task must be observed, not stranded.
        reconcile(repair=False, api=self._api(conclusion='action_required'), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'CHECKS_HELD_FOR_APPROVAL')

        # Pass 2: the maintainer approved, CI ran, the PR merged.
        reconcile(repair=False, api=self._api(merged=True, state='closed'), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'DELIVERED')
        self.assertEqual(record['payment_status'], 'UNVERIFIED')

    def test_change_request_then_merge_reaches_delivered(self):
        from actions_reconcile import reconcile
        store = self._store_with('AWAITING_REVIEW')

        reconcile(repair=False, api=self._api(reviews=['CHANGES_REQUESTED']), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'CHANGES_REQUESTED')
        self.assertEqual(record['review_obligation'], 'address_review')

        # The engineer fixed it, the reviewer approved, it merged.
        reconcile(repair=False, api=self._api(merged=True, state='closed'), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'DELIVERED')

    def test_failed_ci_is_retryable_and_reaches_delivered(self):
        from actions_reconcile import reconcile
        store = self._store_with('AWAITING_REVIEW')
        reconcile(repair=False, api=self._api(conclusion='failure'), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'FAILED_REMOTE_CHECKS')
        from actions_dispatch import retry_eligible
        self.assertTrue(retry_eligible(record))

    def test_closed_unmerged_is_terminal(self):
        from actions_reconcile import reconcile
        store = self._store_with('AWAITING_REVIEW')
        reconcile(repair=False, api=self._api(state='closed'), store=store)
        record, _ = store.read(task_id('unit/control', 7))
        self.assertEqual(record['status'], 'CLOSED_UNMERGED')

    def test_no_pass_ever_leaves_a_task_unobservable(self):
        # Whatever the loop writes, the next pass must still be able to read it.
        from actions_reconcile import PR_OBSERVATION_STATUSES, reconcile
        for conclusion in ('success', 'failure', 'action_required'):
            for reviews in ((), ('CHANGES_REQUESTED',), ('APPROVED',)):
                store = self._store_with('AWAITING_REVIEW')
                reconcile(repair=False, api=self._api(conclusion=conclusion, reviews=reviews),
                          store=store)
                record, _ = store.read(task_id('unit/control', 7))
                status = record['status']
                self.assertTrue(
                    status in PR_OBSERVATION_STATUSES or status in ('DELIVERED', 'CLOSED_UNMERGED'),
                    f'conclusion={conclusion} reviews={reviews} produced unobservable {status}')


if __name__=='__main__': unittest.main()
