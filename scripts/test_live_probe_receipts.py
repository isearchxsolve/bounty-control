"""Truthful verdicts and evidence-preserving continuation of the live runner."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from run_pipeline_live_probes import (Receipts, archive_receipts, campaign_passed,
                                      reusable_methods)


class ReceiptGates(unittest.TestCase):
    def report(self):
        return {'planned_tests': ['m.C.one', 'm.C.two'], 'source_files': {'gate.py': 'old'},
                'results': [{'test': 'm.C.one', 'status': 'PASS'},
                            {'test': 'm.C.two', 'status': 'PASS'}]}

    def test_blocked_missing_empty_or_failed_receipts_never_certify_success(self):
        for status in ('BLOCKED', 'FAIL', 'ERROR', 'NOT_RUN'):
            report = self.report(); report['results'][1]['status'] = status
            self.assertFalse(campaign_passed(report), status)
        report = self.report(); report['results'].pop()
        self.assertFalse(campaign_passed(report))
        self.assertFalse(campaign_passed({'planned_tests': [], 'results': []}))
        self.assertTrue(campaign_passed(self.report()))

    def test_passing_sibling_does_not_skip_failed_or_missing_parent(self):
        report = self.report()
        report['results'] += [{'test': "m.C.one (case='bad')", 'status': 'FAIL'},
                              {'test': "m.C.one (case='good')", 'status': 'PASS'}]
        self.assertEqual(reusable_methods(report, report['source_files']), {'m.C.two'})
        self.assertFalse(campaign_passed(report))
        report['results'] = [r for r in report['results'] if r['test'] != 'm.C.one']
        self.assertEqual(reusable_methods(report, report['source_files']), {'m.C.two'})

    def test_blocked_requires_retry_and_changed_or_legacy_source_requires_revalidation(self):
        report = self.report(); report['results'][1]['status'] = 'BLOCKED'
        self.assertEqual(reusable_methods(report, report['source_files']), {'m.C.one'})
        self.assertEqual(reusable_methods(report, {'gate.py': 'repaired'}), set())
        report.pop('source_files')
        self.assertEqual(reusable_methods(report, {'gate.py': 'repaired'}), set())

    def test_repair_archives_failed_attempt_and_siblings_without_erasing_other_success(self):
        report = self.report()
        report['results'] += [{'test': 'm.C.one (case=1)', 'status': 'FAIL'}]
        original = copy.deepcopy(report['results'])
        archive_receipts(report, {'m.C.one'}, 'repair r2')
        self.assertEqual(report['results'], [original[1]])
        self.assertEqual(report['receipt_history'][0]['results'], [original[0], original[2]])
        self.assertEqual(report['receipt_history'][0]['source_files'], {'gate.py': 'old'})

    def test_class_setup_block_is_superseded_only_by_its_rerun(self):
        report = self.report()
        report['results'].append({'test': 'setUpClass (m.C)', 'status': 'BLOCKED'})
        archive_receipts(report, {'m.C.one', 'm.C.two'}, 'retry fixture')
        self.assertEqual(report['results'], [])
        self.assertEqual(len(report['receipt_history'][0]['results']), 3)

    def test_real_unittest_failed_subtest_reruns_as_a_whole_and_retains_history(self):
        class Cases(unittest.TestCase):
            repaired = False
            def runTest(self):
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertTrue(self.repaired or value != 2)
        case = Cases()
        report = {'planned_tests': [case.id()], 'source_files': {'gate': 'sha'}, 'results': []}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            def run():
                unittest.TextTestRunner(stream=io.StringIO(), resultclass=lambda *a, **kw:
                    Receipts(*a, **kw, report=report, path=path)).run(unittest.TestSuite([Cases()]))
            run()
            self.assertFalse(campaign_passed(report))
            self.assertEqual(reusable_methods(report, report['source_files']), set())
            archive_receipts(report, {case.id()}, 'actual repair')
            Cases.repaired = True
            run()
            self.assertTrue(campaign_passed(report))
            self.assertTrue(any(r['status'] == 'FAIL' for r in report['receipt_history'][0]['results']))
            self.assertTrue(json.loads(path.read_text())['receipt_history'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
