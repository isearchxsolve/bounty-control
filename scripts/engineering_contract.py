"""The engineering contracts a reviewer pins on an issue, as data a gate can check.

Measured 2026-11-06. Three of our open PRs were refused by maintainers for reasons that were
visible in the artifacts before we published:

- ``bl4ckb4ll/blackball#182`` -- CHANGES_REQUESTED: ``fedtax(103350)`` returns a positive tax
  and ``fedtax(103351)`` returns zero. The function has no bracket above $103,350; it falls
  through to ``return (0)``. The reviewer also flagged 2025 federal inputs in a 2026 model and
  assumed wage/rent where the pinned methodology on issue #85 requires local posted figures.
- ``fyne-io/fyne#6637`` -- the native upload-queue check fails in three of four cases on our
  branch while the base passes all four.
- ``geekinasuit/obolus#131`` -- a failing test after our own fix.

Each of those was findable without a reviewer. The pipeline has gates for money, competition,
capacity, vitality and freshness and none for "does this change meet what the issue asked
for". The engineer receives the issue as context and nothing checks that it honoured it.

This module holds two kinds of fact and one rule:

* ``REVIEWER_NAMED_INPUTS`` -- inputs a reviewer named on a live PR. These are facts from a
  review, not model judgement, so they are pinned here where a gate can require them instead
  of relying on the agent to think of the same value.
* ``required_boundary_inputs`` -- the boundary values the issue or a reviewer names, so a
  companion test can be checked for actually exercising them.

Law 85: whether a change satisfies a contract is judgement and belongs to the model. Whether
a named input appears in the test that claims to cover it is a fact, and that belongs here.
"""

# Inputs a reviewer named on a live PR. Keyed by (owner/repo, issue number).
REVIEWER_NAMED_INPUTS = {
    ("bl4ckb4ll/blackball", 85): {
        "function": "fedtax",
        "inputs": (103349, 103350, 103351, 103352),
        "why": ("review found federal tax collapsing to zero one dollar above the $103350 "
                "cutoff: fedtax(103350) is a positive 22% bracket tax and fedtax(103351) "
                "returns 0, because the function's last branch is `return (0)`"),
    },
}

# The edge-case classes a companion test must enumerate before publication. The categories
# already exist in kaggle_engine_worker.ScenarioCase; nothing enforced that they are present.
REQUIRED_EDGE_CLASSES = ("happy_path", "boundary", "negative", "regression")


def required_boundary_inputs(repo, issue):
    """The boundary inputs a reviewer or the issue pinned for this ticket, or an empty tuple."""
    return REVIEWER_NAMED_INPUTS.get((repo, int(issue)), {}).get("inputs", ())


def boundary_coverage_gap(repo, issue, test_sources):
    """Named boundary inputs the test sources never exercise, in reviewer order.

    ``test_sources`` is every test file's text for this ticket. A match is the literal input
    appearing in the text, because a boundary claim that does not state the value is not a
    boundary claim - it is a hope.

    Stated limitation, deliberately: this matches *presence of the value in text*, not that a
    test asserts an expectation on it. A comment reading ``# TODO check 103350`` would count
    as covered here. That is a floor, not a proof, and it is honest about it - the alternative
    would be parsing assertions per language, which is judgement dressed as a gate. It still
    catches the case that actually happened: the value appears nowhere at all.
    """
    missing = []
    for value in required_boundary_inputs(repo, issue):
        if not any(str(value) in text for text in test_sources):
            missing.append(value)
    return tuple(missing)


def edge_class_gap(categories_present):
    """Which required edge-case classes are absent from the scenario matrix."""
    present = {str(category).strip().lower() for category in categories_present}
    return tuple(name for name in REQUIRED_EDGE_CLASSES if name not in present)
