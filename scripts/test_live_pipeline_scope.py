"""Contract regression: an unfiltered master run starts the whole pipeline."""
from types import SimpleNamespace
import unittest

from live_pipeline_integration import LiveRun


class FullPipelineDefault(unittest.TestCase):
    def test_empty_issue_does_not_enter_fixture_or_single_issue_path(self):
        run = LiveRun.__new__(LiveRun)
        run.args = SimpleNamespace(issue=None)
        run.data = {}
        entered = []
        def pipeline():
            entered.append('production-entry-door')
            return 'full-pipeline'
        run.pipeline = pipeline
        self.assertEqual(run.run(), 'full-pipeline')
        self.assertEqual(entered, ['production-entry-door'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
