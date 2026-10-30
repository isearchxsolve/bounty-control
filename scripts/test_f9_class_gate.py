"""Unit tests for F9 — the class-level "does this request a repository code change?" admission gate.

Tests is_code_change_request() against the 60-issue hand-labeled sample from
scripts/f11_sample/f11_labeling_sample_60.json.

Ground truth (from F11 refusal census):
  - 45 needs_code_change   -> MUST ADMIT (zero false negatives)
  - 10 not_code_change_process -> MAY ADMIT (fail-open on unclear)
  - 5 not_code_change_external -> MAY ADMIT (fail-open on unclear)

Constraints:
  - Zero false negatives: no genuine needs_code_change may be refused.
  - Fail-open: ambiguous items must be admitted.
  - Zero heuristic sprawl: smallest deterministic classifier.
"""

import json
from pathlib import Path
import sys
import unittest

# Resolve relative to this file. The suite previously hardcoded an absolute Windows path to
# the author's checkout, so it could only ever pass on that one machine -- which is why it was
# absent from CI. Every other suite is portable; this one now is too.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from actions_dispatch import is_code_change_request  # noqa: E402

SAMPLE = HERE / 'f11_sample' / 'f11_labeling_sample_60.json'


def load_sample():
    with open(SAMPLE, encoding='utf-8', errors='replace') as f:
        return json.load(f)


class F9ClassGateTests(unittest.TestCase):
    """F9 gate must admit all needs_code_change issues (zero false negatives)."""

    @classmethod
    def setUpClass(cls):
        cls.sample = load_sample()

    def test_zero_false_negatives(self):
        """No genuine needs_code_change issue may be refused."""
        refused = []
        for item in self.sample:
            if item['hand_label'] == 'needs_code_change':
                admitted, reason = is_code_change_request(
                    item.get('title', ''),
                    item.get('body_preview', ''),
                    item.get('labels', []),
                )
                if not admitted:
                    refused.append({
                        'repo': item['repo'],
                        'number': item['number'],
                        'title': item['title'][:80],
                        'reason': reason,
                    })
        self.assertEqual(
            len(refused), 0,
            "Zero false negatives required. Refused code-change issues: {}".format(
                json.dumps(refused, indent=2, ensure_ascii=False)
            )
        )

    def test_all_needs_code_change_admitted(self):
        """Every needs_code_change issue returns admitted=True."""
        for item in self.sample:
            if item['hand_label'] == 'needs_code_change':
                admitted, reason = is_code_change_request(
                    item.get('title', ''),
                    item.get('body_preview', ''),
                    item.get('labels', []),
                )
                self.assertTrue(
                    admitted,
                    "needs_code_change issue {}#{} was refused: {}".format(
                        item['repo'], item['number'], reason
                    )
                )
                self.assertIn(
                    reason,
                    ("needs_code_change", "unclear_fail_open"),
                    "Admitted code-change issue returned unexpected reason: {}".format(reason)
                )

    def test_no_refusal_without_high_confidence(self):
        """No issue may be refused unless external/process intent is high confidence."""
        for item in self.sample:
            admitted, reason = is_code_change_request(
                item.get('title', ''),
                item.get('body_preview', ''),
                item.get('labels', []),
            )
            if not admitted:
                self.assertTrue(
                    reason.startswith("REFUSED_NOT_A_CODE_CHANGE: "),
                    "Refusal must use REFUSED_NOT_A_CODE_CHANGE prefix, got: {}".format(reason)
                )
                reason_lower = reason.lower()
                self.assertTrue(
                    "external" in reason_lower or "process" in reason_lower,
                    "Refusal reason must identify external or process: {}".format(reason)
                )

    def test_external_refusal_examples(self):
        """Confirmed external bounty-escrow ads must be refused."""
        external_expected = [
            item for item in self.sample
            if item['hand_label'] == 'not_code_change_external'
        ]
        for item in external_expected:
            admitted, reason = is_code_change_request(
                item.get('title', ''),
                item.get('body_preview', ''),
                item.get('labels', []),
            )
            # External items MAY be admitted on fail-open, but if refused,
            # the reason must cite external patterns.
            if not admitted:
                self.assertIn("external", reason.lower())


if __name__ == '__main__':
    unittest.main()