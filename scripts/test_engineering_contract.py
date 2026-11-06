"""The boundary gate was honoured in form and ignored in substance.

Measured 2026-11-06 against the live artifact. ``bl4ckb4ll/blackball`` has a full
scenario-matrix tree - ``tests/happy_path``, ``tests/boundary``, ``tests/negative``,
``tests/regression``, ``tests/concurrency`` - and ``tests/boundary/test_calculate.sh``
passes. It tests the boundary of the ``cover`` calculator: 40194 exactly, 0, 0.01, 40195.

The PR's own commit ``cc0b373`` introduced ``fedtax``, a piecewise function with a hard
cutoff at $103,350 and no branch above it, so ``fedtax(103350)`` returns a positive 22%
bracket tax and ``fedtax(103351)`` returns zero. ``git grep -i 'fedtax|bracket|tax'`` over
the whole test tree returns one incidental match - ``assert_not_contains ... "syntax
error"``. No test exercises the tax function at all.

That is the shape of every gate defect found on 2026-11-06: the check verified that
boundary tests exist and pass, never that they exercise the boundary of the change. The
companion-test rule was satisfied literally while the discontinuity it introduced was
never tested, and the reviewer found it in thirty seconds.

These tests pin the two facts a gate can check: that the reviewer-named inputs are absent
from the live test tree, and that a matrix missing an edge class is reported as a gap.
"""
import unittest

import engineering_contract as contract


class LiveArtifactFacts(unittest.TestCase):
    """Read from the review, not from a fixture: the reviewer named these exact inputs."""

    def test_the_reviewer_named_the_cutoff_and_one_dollar_above_it(self):
        inputs = contract.required_boundary_inputs("bl4ckb4ll/blackball", 85)
        self.assertEqual(inputs, (103349, 103350, 103351, 103352))
        self.assertIn("fedtax", contract.REVIEWER_NAMED_INPUTS[("bl4ckb4ll/blackball", 85)]["function"])

    def test_a_ticket_with_no_pinned_inputs_requires_nothing(self):
        self.assertEqual(contract.required_boundary_inputs("some/repo", 1), ())

    def test_the_reason_is_recorded_so_the_pin_is_auditable(self):
        why = contract.REVIEWER_NAMED_INPUTS[("bl4ckb4ll/blackball", 85)]["why"]
        self.assertIn("103", why)
        self.assertIn("zero", why.lower())


class BoundaryCoverageGap(unittest.TestCase):
    """A boundary claim that does not state the value is a hope, not a boundary."""

    # The live boundary suite: it covers the `cover` calculator and never the tax function.
    LIVE_BOUNDARY_TEST = (
        "full=$(bash \"$calc\" cover 40194 40194)\n"
        "assert_contains \"saving_equals_cost_share\" \"$full\" \"share_percent\\t100.00\"\n"
        "zero=$(bash \"$calc\" cover 40194 0)\n"
        "tiny=$(bash \"$calc\" cover 0.01 0.01)\n"
        "bash \"$calc\" cover 40194 40195 >/dev/null 2>&1\n"
    )

    def test_the_live_boundary_suite_misses_every_pinned_tax_input(self):
        # The gate's whole point: the suite that passes today leaves the reviewer's inputs
        # uncovered, so the ticket would still be published with its defect inside it.
        gap = contract.boundary_coverage_gap("bl4ckb4ll/blackball", 85, [self.LIVE_BOUNDARY_TEST])
        self.assertEqual(gap, (103349, 103350, 103351, 103352))

    def test_a_suite_that_names_the_values_closes_the_gap(self):
        covered = self.LIVE_BOUNDARY_TEST + (
            "assert_eq \"$tax_103350\" \"$(fedtax 103350)\"\n"
            "assert_eq \"$tax_103351\" \"$(fedtax 103351)\"\n"
            "assert_eq \"$tax_103349\" \"$(fedtax 103349)\"\n"
            "assert_eq \"$tax_103352\" \"$(fedtax 103352)\"\n"
        )
        self.assertEqual(contract.boundary_coverage_gap("bl4ckb4ll/blackball", 85, [covered]), ())

    def test_one_value_still_missing_is_still_a_gap(self):
        mostly = self.LIVE_BOUNDARY_TEST + "fedtax(103350)\nfedtax(103351)\nfedtax(103349)\n"
        self.assertEqual(contract.boundary_coverage_gap("bl4ckb4ll/blackball", 85, [mostly]), (103352,))

    def test_the_gate_matches_presence_not_assertion_and_says_so(self):
        # Stated limitation: a comment naming the value counts as covered. That is a floor,
        # not a proof, and the alternative - parsing assertions per language - is judgement
        # wearing a gate's clothes. What it does catch is the case that happened: nothing.
        comment_only = self.LIVE_BOUNDARY_TEST + "# TODO check fedtax(103350) here\n"
        self.assertEqual(contract.boundary_coverage_gap("bl4ckb4ll/blackball", 85, [comment_only]),
                         (103349, 103351, 103352))


class EdgeClassGap(unittest.TestCase):

    def test_a_complete_matrix_has_no_gap(self):
        self.assertEqual(contract.edge_class_gap(
            ["happy_path", "boundary", "negative", "regression"]), ())

    def test_the_observed_matrix_reports_exactly_what_is_missing(self):
        # What the artifact actually carried: concurrency and null, but no boundary.
        self.assertEqual(contract.edge_class_gap(["happy_path", "negative", "concurrency"]),
                         ("boundary", "regression"))

    def test_case_and_whitespace_do_not_defeat_the_check(self):
        self.assertEqual(contract.edge_class_gap([" Happy_Path ", "BOUNDARY", "Negative ",
                                                  "Regression"]), ())


if __name__ == "__main__":
    unittest.main()
