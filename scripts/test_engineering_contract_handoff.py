"""The actual prompt builder must carry the post-intake host contract intact."""
import json
from pathlib import Path
import re
import tempfile
import unittest

import kaggle_engine_worker as worker


class EngineeringContractHandoff(unittest.TestCase):
    def test_complete_contract_survives_context_pointer_on_every_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            original = worker.PACKET_DIR
            worker.PACKET_DIR = directory
            try:
                intake = Path(directory, 'intake.context.json')
                intake.write_text(json.dumps({'body': 'Original issue only'}), encoding='utf-8')
                body = ('Full issue ₹ 日本語\n' * 6000 +
                        '\nDelivery contract: write /tmp/fleet-artifacts/regression.json as JSON with '
                        'test_files, argv, expected_failure. Do not commit, push, create a fork or publish.')
                paths = []
                for feedback in (None, 'Missing regression.json; preserve the completed fix'):
                    prompt = worker.build_cline_engineering_prompt(
                        'unit/project', 1, 'Fix conversion', body,
                        {'full_delivery_context': str(intake)}, [], feedback)
                    self.assertIn(str(intake), prompt)
                    self.assertLess(len(prompt), 12000)
                    path = Path(re.search(r'artifact contract from (.+\.txt)\.', prompt)[1])
                    self.assertEqual(path.read_text(encoding='utf-8'), body)
                    self.assertEqual(json.loads(intake.read_text())['body'], 'Original issue only')
                    paths.append(path)
                self.assertNotEqual(paths[0], paths[1])
            finally:
                worker.PACKET_DIR = original


if __name__ == '__main__':
    unittest.main(verbosity=2)
