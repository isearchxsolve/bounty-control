"""Checkpoint plumbing and exact generation provenance; no live service calls."""
import json
from pathlib import Path
import tempfile
import unittest

from live_pipeline_resume import restore_files
from live_pipeline_integration import delivery_harness


class CampaignRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'source'
        self.source.mkdir()
        self.destination = Path(self.temporary.name) / 'restored'
        self.original = {'mode': 'PIPELINE', 'id': 'same-campaign', 'control': 'owner/control',
                         'target': 'owner/target', 'deployed_sha': 'a' * 40,
                         'events': [{'case': 'LIVE_INTAKE', 'status': 'PASS'}],
                         'pipeline_admitted': True, 'end_to_end_passed': False}
        (self.source / 'run.json').write_text(json.dumps(self.original), encoding='utf-8')
        self.run = {'id': 123, 'html_url': 'https://github.com/owner/control/actions/runs/123',
                    'head_sha': 'a' * 40}

    def restore(self):
        return restore_files(self.source, self.destination, source_run=self.run,
                             control='owner/control', target='owner/target', driver_sha='b' * 40)

    def test_actual_journal_and_child_attempt_history_are_preserved(self):
        child = self.source / 'originals' / 'identity'
        (child / 'queue').mkdir(parents=True)
        state = {'attempt': 3, 'dispatch_id': 'same-generation', 'queue_dir': '/old/path/queue',
                 'events': [{'case': 'ACTIONS_TERMINAL', 'status': 'FAIL'}]}
        (child / 'run.json').write_text(json.dumps(state), encoding='utf-8')
        result = self.restore()
        self.assertEqual(result['id'], self.original['id'])
        self.assertEqual(result['events'], self.original['events'])
        self.assertTrue(result['pipeline_admitted'])
        self.assertFalse(result['end_to_end_passed'])
        archived = json.loads((self.destination / 'continuations/123/run.json').read_text())
        self.assertEqual(archived, self.original)
        recovered = json.loads((self.destination / 'originals/identity/run.json').read_text())
        self.assertEqual(recovered['attempt'], 3)
        self.assertEqual(recovered['dispatch_id'], 'same-generation')
        self.assertEqual(recovered['events'], state['events'])
        self.assertEqual(recovered['queue_dir'], str((self.destination / 'originals/identity/queue').resolve()))

    def test_incomplete_entry_is_not_promoted_to_admission(self):
        self.original.pop('pipeline_admitted')
        (self.source / 'run.json').write_text(json.dumps(self.original))
        result = self.restore()
        self.assertNotIn('pipeline_admitted', result)
        self.assertTrue((self.destination / 'entry-scout/discovery-memory/CONTINUATION.json').exists())

    def test_different_campaign_is_rejected(self):
        self.original['target'] = 'different/target'
        (self.source / 'run.json').write_text(json.dumps(self.original))
        with self.assertRaises(ValueError):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_existing_journal_is_never_overwritten(self):
        self.destination.mkdir()
        (self.destination / 'run.json').write_text('do not overwrite')
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual((self.destination / 'run.json').read_text(), 'do not overwrite')


class GenerationProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.run = {'head_sha': 'b' * 40, 'id': 321, 'run_attempt': 2,
                    'html_url': 'https://github.com/owner/control/actions/runs/321'}
        self.state = {'harness_sha': 'b' * 40, 'owner': '321:2', 'run_url': self.run['html_url']}

    def test_default_campaign_still_refuses_a_changed_harness(self):
        with self.assertRaisesRegex(AssertionError, 'Deployed harness changed'):
            delivery_harness(self.run, self.state, 'a' * 40)

    def test_explicit_continuation_accepts_exact_actual_execution_identity(self):
        self.assertEqual(delivery_harness(self.run, self.state, 'a' * 40, continuation=True), 'b' * 40)

    def test_continuation_never_accepts_mismatched_execution_evidence(self):
        for field in ('harness_sha', 'owner', 'run_url'):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                delivery_harness(self.run, {**self.state, field: 'wrong'}, 'a' * 40, continuation=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
