"""Exercise the live logger against real Python text streams."""
from pathlib import Path
import tempfile
import unittest

from live_pipeline_integration import Tee


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
