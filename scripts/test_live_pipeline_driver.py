"""Exercise the live logger against real Python text streams."""
from pathlib import Path
import json
from contextlib import closing
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest

from live_pipeline_integration import Tee, LiveRun, REQUIRED_CASES, drain_evidence


class JournalAcceptanceContract(unittest.TestCase):
    def test_old_green_journal_with_missing_new_cases_is_invalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'run.json')
            path.write_text(json.dumps({'target': 'owner/repo', 'control': 'owner/control',
                'events': [], 'end_to_end_passed': True}), encoding='utf-8')
            LiveRun(SimpleNamespace(run_dir=Path(directory), target='owner/repo', control='owner/control', issue=None))
            self.assertFalse(json.loads(path.read_text())['end_to_end_passed'])

    def test_later_phase_failure_revokes_green_even_if_required_cases_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = LiveRun(SimpleNamespace(run_dir=Path(directory), target='owner/repo', control='owner/control', issue=None))
            run.data['events'] = [{'case': name, 'status': 'PASS'} for name in REQUIRED_CASES]
            run.data['end_to_end_passed'] = True
            run.save()
            run.record('OBSERVE', 'FAIL', diagnostic='Later head verification failed')
            self.assertFalse(json.loads(run.path.read_text())['end_to_end_passed'])


class DrainArtifactContract(unittest.TestCase):
    def test_fresh_workflow_cannot_hide_wrong_queue_or_unexamined_cached_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = {'run_started_at': '2026-11-03T01:00:00Z'}
            census = {'door_reason': 'HYDRATE_ONLY', 'at': '2026-11-03T01:01:00+00:00'}
            with closing(sqlite3.connect(folder / 'agent-queue.sqlite3')) as con:
                con.execute('CREATE TABLE decisions(disposition TEXT, at TEXT)')
                con.execute('INSERT INTO decisions VALUES(?,?)', ('capacity_wait', '2026-11-02T12:00:00+00:00'))
                con.commit()
            (folder / 'census.jsonl').write_text(json.dumps(census), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'unexamined'):
                drain_evidence(folder, run)
            with closing(sqlite3.connect(folder / 'agent-queue.sqlite3')) as con:
                con.execute('UPDATE decisions SET at=?', (census['at'],))
                con.commit()
            self.assertEqual(drain_evidence(folder, run), census)
            census['door_reason'] = 'NO_ROWS'
            (folder / 'census.jsonl').write_text(json.dumps(census), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'agent-queue path'):
                drain_evidence(folder, run)


class LiveLoggerContract(unittest.TestCase):
    def test_production_stdout_configuration_and_evidence_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            primary, evidence = Path(directory, 'stdout'), Path(directory, 'evidence')
            with primary.open('w', encoding='ascii') as stream, evidence.open('w', encoding='utf-8') as log:
                tee = Tee(stream, log)
                tee.reconfigure(encoding='utf-8', errors='replace')
                self.assertEqual(tee.encoding, 'utf-8')
                self.assertEqual(tee.fileno(), stream.fileno())
                tee.write('Live receipt ₹ 日本語\n')
                tee.flush()
            self.assertEqual(primary.read_bytes(), evidence.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
