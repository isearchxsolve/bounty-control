"""Reviewer-named boundary inputs must block publication, not sit in an unused module.

Measured 2026-11-06 on bl4ckb4ll/blackball#85: the repo carried a full scenario matrix -
tests/happy_path, tests/boundary, tests/negative, tests/regression - and
tests/boundary/test_calculate.sh passed. It tested the boundary of the ``cover``
calculator (40194 exactly, 0, 0.01, 40195). Our own commit introduced ``fedtax``, a
piecewise function whose last branch is ``return (0)``, so ``fedtax(103350)`` is a positive
22% bracket tax and ``fedtax(103351)`` is zero. ``git grep -i 'fedtax|bracket|tax'`` over the
whole test tree returned one incidental match.

So the boundary gate was honoured in form - a green boundary suite existed - and ignored in
substance: it checked that boundary tests exist, never that they exercise the boundary of the
code that changed. ``engineering_contract`` pins those inputs as data; this file is what
makes them load-bearing.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import actions_delivery as delivery


COVERED = """
full=$(bash "$calc" cover 40194 40194)
assert_contains "share" "$full" "share_percent\\t100.00"
fedtax(103350) -> 46247.75
fedtax(103351) -> 46271.01
fedtax(103349) -> 46224.49
fedtax(103352) -> 46294.27
"""

UNCOVERED = """
full=$(bash "$calc" cover 40194 40194)
assert_contains "share" "$full" "share_percent\\t100.00"
"""


class BoundaryContractRefusal(unittest.TestCase):

    def _artifacts(self, test_files):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "regression.json"
        path.write_text(json.dumps({"test_files": test_files}), encoding="utf-8")
        return path

    def test_an_uncovered_reviewer_input_refuses_publication(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "tests").mkdir()
            (Path(root) / "tests" / "test_calc.py").write_text(UNCOVERED, encoding="utf-8")
            with mock.patch.object(delivery, "artifacts",
                                   return_value=Path(self._artifacts(["tests/test_calc.py"])).parent):
                refusal = delivery.boundary_contract_refusal(
                    {}, root, "bl4ckb4ll/blackball", 85)
        self.assertIn("103350", refusal)
        self.assertIn("not exercised", refusal)

    def test_a_covered_reviewer_input_lets_publication_through(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "tests").mkdir()
            (Path(root) / "tests" / "test_calc.py").write_text(COVERED, encoding="utf-8")
            with mock.patch.object(delivery, "artifacts",
                                   return_value=Path(self._artifacts(["tests/test_calc.py"])).parent):
                refusal = delivery.boundary_contract_refusal(
                    {}, root, "bl4ckb4ll/blackball", 85)
        self.assertIsNone(refusal)

    def test_a_ticket_with_no_pinned_inputs_requires_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(delivery, "artifacts",
                                   return_value=Path(self._artifacts([])).parent):
                self.assertIsNone(delivery.boundary_contract_refusal({}, root, "a/b", 1))

    def test_an_unreadable_bundle_is_not_evidence_of_coverage(self):
        # No regression.json and nothing readable: the gate must not invent a pass.
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(delivery, "artifacts", return_value=Path(root)):
                refusal = delivery.boundary_contract_refusal(
                    {}, root, "bl4ckb4ll/blackball", 85)
        self.assertIn("not exercised", refusal)

    def test_the_gate_is_wired_into_publish(self):
        with open(delivery.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("boundary_contract_refusal(context, root, repo, number)", source,
                      "the gate exists but nothing calls it - a dead gate reads as a fix")


if __name__ == "__main__":
    unittest.main()
