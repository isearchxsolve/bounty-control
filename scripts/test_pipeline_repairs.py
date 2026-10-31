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
from delivery_supervisor import validate_plan_review
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

    def test_native_plan_requires_exact_independent_review(self):
        plan = VerificationPlan(builds=[['sh','-c','exit 0']],baseline_tests=[['sh','-c','exit 0']],final_tests=[['sh','-c','exit 0']])
        with self.assertRaises(ValueError): validate_plan_review(None,plan,[])
        sources = [{'path':'package.json','sha256':'abc'}]
        review = {'approved':True,'reason':'Native manifest inspected','plan_sha256':digest(asdict(plan)),'sources':sources}
        validate_plan_review(review,plan,sources)
        plan.builds.append(['different'])
        with self.assertRaisesRegex(ValueError,'digest mismatch'): validate_plan_review(review,plan,sources)

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


if __name__=='__main__': unittest.main()
