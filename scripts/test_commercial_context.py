"""Commercial risk is source-bound agent review, not a word-based fraud verdict."""
import base64
import copy
from datetime import datetime, timezone
import unittest

from actions_github import GitHubError
from commercial_context import collect, review_refusal, review_revision, revalidate
from delivery_errors import CommercialReviewRequired
from payment_gates import funding_freshness_refusal
import cline_entry_door as door


def context():
    return {'repo': 'acme/http', 'issue_number': 7, 'complete_comments': True,
            'repository': {'owner': {'login': 'owner'}}, 'comments': [],
            'issue': {'html_url': 'https://github.com/acme/http/issues/7',
                      'title': 'Retry fails', 'state': 'open', 'user': {'login': 'owner'},
                      'author_association': 'OWNER',
                      'body': 'We pay $250 for a fix. Fix the retry in src/retry.py.'}}


def review(ctx):
    documents = [ctx['issue'], *ctx.get('comments', []), *ctx.get('commercial_sources', [])]
    return {'decision': 'proceed', 'reason': 'Controlled test assessment of the cited evidence, not a payment receipt.',
            'source_revision': review_revision(ctx),
            'evidence': [{'source_url': d['html_url'], 'quote': d['body']}
                         for d in documents if d.get('body')]}


class CommercialReviewTests(unittest.TestCase):
    def test_warning_in_related_pr_cannot_bypass_model_door(self):
        ctx = context()
        ctx['commercial_sources'] = [{'html_url': 'https://github.com/acme/http/pull/9#issuecomment-1',
                                     'body': "They didn't pay me; it might be a scam."}]
        reason, _, proof = door.model_admission_refusal({'repo': 'acme/http', 'issue': 7}, lambda *a: ctx)
        self.assertEqual(reason, 'COMMERCIAL_REVIEW_REQUIRED')
        self.assertIsNone(proof)

    def test_negated_or_resolved_warning_is_reviewable_not_permanent_rejection(self):
        ctx = context()
        ctx['comments'] = [{'html_url': ctx['issue']['html_url'] + '#issuecomment-1',
                           'body': "An old post said 'is a scam'; the current payment evidence resolves that allegation."}]
        self.assertEqual(review_refusal(ctx)[0], 'COMMERCIAL_REVIEW_REQUIRED')
        self.assertEqual(review_refusal(ctx, review(ctx)), (None, None))

    def test_review_cannot_ignore_another_warning_or_change_with_sources(self):
        ctx = context()
        ctx['comments'] = [{'html_url': ctx['issue']['html_url'] + '#issuecomment-1', 'body': 'I was never paid.'}]
        decision = review(ctx)
        decision['evidence'] = [decision['evidence'][0]]
        self.assertEqual(review_refusal(ctx, decision)[0], 'COMMERCIAL_REVIEW_EVIDENCE_MISSING')
        decision = review(ctx)
        ctx['comments'][0]['body'] += ' New material evidence.'
        self.assertEqual(review_refusal(ctx, decision)[0], 'COMMERCIAL_REVIEW_STALE')

    def test_hold_missing_review_or_unknown_context_never_passes(self):
        ctx = context()
        ctx['commercial_context_complete'] = True
        self.assertEqual(review_refusal(ctx)[0], 'COMMERCIAL_REVIEW_REQUIRED')
        decision = review(ctx)
        decision['decision'] = 'hold'
        self.assertEqual(review_refusal(ctx, decision)[0], 'COMMERCIAL_REVIEW_NOT_APPROVED')
        ctx['commercial_context_complete'] = False
        self.assertEqual(review_refusal(ctx, review(ctx))[0], 'COMMERCIAL_CONTEXT_UNAVAILABLE')

    def test_fabricated_quote_is_not_verified_review(self):
        ctx = context(); ctx['commercial_context_complete'] = True
        decision = review(ctx); decision['evidence'][0]['quote'] = 'Escrow funds have been independently settled'
        self.assertEqual(review_refusal(ctx, decision)[0], 'COMMERCIAL_REVIEW_EVIDENCE_MISSING')

    def test_legacy_admission_is_held_for_review_instead_of_grandfathered(self):
        with self.assertRaises(CommercialReviewRequired) as raised:
            revalidate(None, context(), {'commercial_scope': 'primary-only'})
        self.assertEqual(raised.exception.reason, 'COMMERCIAL_REVIEW_REQUIRED')

    def test_collector_never_marks_an_incomplete_primary_thread_complete(self):
        from test_pipeline_repairs import Transport
        ctx = context(); ctx['complete_comments'] = False
        snapshot = collect(Transport(), ctx)
        self.assertFalse(snapshot['commercial_context_complete'])
        self.assertIn('Primary issue comment collection is incomplete', snapshot['commercial_context_errors'])

    def test_changed_review_is_nonretryable_and_preserves_the_failed_phase(self):
        import json
        import os
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import actions_delivery as delivery
        from actions_reconcile import repair_obligation
        for phase in ('claim', 'publish'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                with patch.dict(os.environ, {'FLEET_ARTIFACT_DIR': temp}), \
                     patch('sys.argv', ['actions_delivery.py', phase]), \
                     patch.object(delivery, phase, side_effect=CommercialReviewRequired('COMMERCIAL_REVIEW_STALE')):
                    with self.assertRaises(CommercialReviewRequired):
                        delivery.main()
                result = json.loads((Path(temp) / (phase + '-failure.json')).read_text())
                self.assertEqual(result['status'], 'REJECTED_COMMERCIAL_REVIEW')
                self.assertEqual(result['resume_phase'], phase)
                self.assertFalse(repair_obligation(result))

    def test_claim_review_hold_is_durable_without_spending_an_attempt_or_changing_identity(self):
        from test_pipeline_repairs import Store
        from actions_delivery import revalidate_commercial
        from actions_github import task_id
        from actions_reconcile import repair_obligation
        store = Store(); ctx = context(); identity = task_id(ctx['repo'], ctx['issue_number'])
        proof = {'commercial_scope': 'primary-only'}
        original = {'task_id': identity, 'dispatch_id': 'generation-7', 'status': 'DISPATCHED',
                    'admission': proof, 'attempt': 2, 'failures': [{'diagnostic': 'prior failure'}],
                    'pr_url': 'retained-pr', 'head_sha': 'retained-head'}
        store.rows[identity] = copy.deepcopy(original)
        with self.assertRaises(CommercialReviewRequired):
            revalidate_commercial(None, ctx, proof, store, identity, 'claim', dispatch_id='generation-7')
        held = store.read(identity)[0]
        for field in ('task_id', 'dispatch_id', 'attempt', 'failures', 'pr_url', 'head_sha', 'admission'):
            self.assertEqual(held[field], original[field], field)
        self.assertEqual(held['status'], 'REJECTED_COMMERCIAL_REVIEW')
        self.assertFalse(repair_obligation(held))

    def test_old_dispatch_cannot_put_a_new_generation_on_hold(self):
        from test_pipeline_repairs import Store
        from actions_delivery import revalidate_commercial
        store = Store(); proof = {}; original = {'dispatch_id': 'new', 'status': 'DISPATCHED', 'admission': proof}
        store.rows['id'] = copy.deepcopy(original)
        with self.assertRaisesRegex(ValueError, 'lost its dispatch generation'):
            revalidate_commercial(None, context(), proof, store, 'id', 'claim', dispatch_id='old')
        self.assertEqual(store.rows['id'], original)

    def test_collector_reads_linked_pr_comments_and_policy_not_just_target_thread(self):
        class Wire:
            def pages(self, path):
                if path.endswith('/timeline'):
                    return [{'source': {'issue': {'html_url': 'https://github.com/acme/http/pull/9'}}}]
                return [{'html_url': 'https://github.com/acme/http/pull/9#issuecomment-1', 'body': 'I was never paid.'}]
            def api(self, path, *args, **kwargs):
                if path == 'graphql':
                    return {'data': {'repository': {'merged': {'totalCount': 1, 'nodes': []},
                                                  'all': {'totalCount': 2}}}}
                if path.endswith('/issues/9'):
                    return {'html_url': 'https://github.com/acme/http/pull/9', 'body': 'Previous contribution', 'comments': 1}
                if path.endswith('/README.md'):
                    return {'html_url': 'https://github.com/acme/http/blob/main/README.md', 'sha': 'observed-blob',
                            'type': 'file', 'encoding': 'base64', 'content': base64.b64encode(b'Actual fixture terms').decode()}
                raise GitHubError('HTTP 404')
        ctx = collect(Wire(), context())
        self.assertTrue(ctx['commercial_context_complete'])
        self.assertTrue(any('never paid' in d['body'] for d in ctx['commercial_sources']))
        self.assertEqual(review_refusal(ctx)[0], 'COMMERCIAL_REVIEW_REQUIRED')


class FundingFreshnessTests(unittest.TestCase):
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)

    def test_unrelated_activity_does_not_renew_old_offer(self):
        ctx = context(); ctx['issue'].update(created_at='2025-01-01T00:00:00Z', updated_at=self.now.isoformat())
        ctx['comments'] = [{'html_url': ctx['issue']['html_url'] + '#issuecomment-2',
                           'body': 'Thanks', 'author_association': 'OWNER', 'created_at': self.now.isoformat()}]
        self.assertEqual(funding_freshness_refusal(ctx, {'source_url': ctx['issue']['html_url']}, now=self.now),
                         'FUNDING_FRESHNESS_REVIEW_REQUIRED')

    def test_cited_new_offer_allows_old_issue_without_claiming_escrow(self):
        ctx = context(); ctx['issue']['created_at'] = '2025-01-01T00:00:00Z'
        url = ctx['issue']['html_url'] + '#issuecomment-2'
        ctx['comments'] = [{'html_url': url, 'created_at': self.now.isoformat(), 'body': 'We pay $250 for a fix.'}]
        self.assertIsNone(funding_freshness_refusal(ctx, {'source_url': url}, now=self.now))

    def test_bad_missing_or_future_dates_are_unknown_not_fresh(self):
        for stamp in ('bad', '2025-01-01', '2030-01-01T00:00:00Z'):
            with self.subTest(stamp=stamp):
                ctx = context(); ctx['issue']['created_at'] = stamp
                self.assertEqual(funding_freshness_refusal(ctx, {'source_url': ctx['issue']['html_url']}, now=self.now),
                                 'FUNDING_FRESHNESS_UNVERIFIED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
