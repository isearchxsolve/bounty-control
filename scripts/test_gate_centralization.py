"""Where each gate actually runs: the entry door, or somewhere downstream.

The standing design rule is that the door decides and the delivery side executes. This module
pins that rule as executable fact rather than as a comment, by asserting for each gate which
module is allowed to call it.

Two categories, and the distinction matters:

* **Admission gates** -- is this issue real, open, funded, quoted, and uncontested. These must
  run at the door exactly once. A second run downstream is the split brain that produced zero
  published pull requests (the door admitted, the dispatcher re-argued, the delivery side
  re-argued again, and the three disagreed).
* **Execution gates** -- is this patch applicable to this base, did preparation produce a
  deliverable, was the claim accepted. These belong downstream by nature: they are facts about
  work that has already happened, not about whether the work should start.

Anything in the first category found outside the door fails here.

Run: python scripts/test_gate_centralization.py
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cline_entry_door as door  # noqa: E402
import sovereign_discovery  # noqa: E402


def callers_of(function_name):
    """Every production module that calls ``function_name``, by file name."""
    found = set()
    for path in HERE.glob("*.py"):
        if path.name.startswith(("test_", "debug_", "fix_", "migrate_", "replay_")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                if name == function_name:
                    found.add(path.name)
    return found


class AdmissionGatesLiveAtTheDoor(unittest.TestCase):
    """The gates that decide whether work should start."""

    def test_door_owns_the_admission_verdicts(self):
        for gate in ("admission_refusal", "model_admission_refusal", "competition_refusal"):
            self.assertTrue(hasattr(door, gate), gate + " is not defined in the entry door")

    def test_no_downstream_module_re_runs_admission(self):
        # The door is the only place these may be called from. ``model_admission_refusal`` is
        # passed as a value (decision_verifier=...) rather than called, so an empty caller set
        # is also correct: what matters is that nothing downstream calls it.
        for gate in ("admission_refusal", "model_admission_refusal", "competition_refusal"):
            callers = callers_of(gate)
            self.assertTrue(callers <= {"cline_entry_door.py"},
                            f"{gate} is called from {sorted(callers)}; admission belongs at "
                            f"the door only")

    def test_delivery_reads_the_door_proof_as_binding(self):
        """claim() must verify the door's proof, never re-derive one."""
        source = (HERE / "actions_delivery.py").read_text(encoding="utf-8")
        self.assertIn("require_evidence(old, context)", source,
                      "the delivery side must take the durable proof, not rebuild it")
        self.assertIn("Dispatch payload proof differs from durable evidence", source,
                      "a payload that disagrees with durable evidence must be refused")

    def test_delivery_does_not_call_admit(self):
        """Re-running admit() downstream was the split brain; it must stay gone.

        Checked against the parsed AST, not the source text: the module's comments explain the
        removal by name, and a substring search cannot tell an explanation from a call.
        """
        for forbidden in ("admit", "admission_refusal", "model_admission_refusal"):
            callers = callers_of(forbidden)
            self.assertNotIn("actions_delivery.py", callers,
                             "actions_delivery re-runs admission by calling " + forbidden)

    def test_sovereign_discovery_reverifies_rather_than_rederives(self):
        source = (HERE / "sovereign_discovery.py").read_text(encoding="utf-8")
        self.assertIn("require_evidence(row, context)", source,
                      "discovery must verify the door's stamps, not manufacture its own")


class ExecutionGatesStayDownstream(unittest.TestCase):
    """Gates that are facts about work already done, not about whether to start."""

    def test_patch_gates_live_in_delivery(self):
        for gate in ("require_baseline_relationship", "reject_preparation", "claim_denial"):
            callers = callers_of(gate)
            self.assertIn("actions_delivery.py", callers,
                          gate + " is an execution gate and belongs in delivery")

    def test_competition_race_check_survives_at_claim(self):
        """One last-minute race check is deliberate: a claimant can appear while queued."""
        source = (HERE / "actions_delivery.py").read_text(encoding="utf-8")
        self.assertIn("competition(api, repo, number", source,
                      "the last-minute competition race check was removed; a PR that appears "
                      "while a ticket waits in the queue would no longer stop the run")


class GatesNotYetAtTheDoor(unittest.TestCase):
    """Gates that are still downstream. Pinned so the gap stays visible.

    These are not execution gates. Each one decides whether work should start, which by the
    standing rule means it belongs at the door. They are listed here as known exceptions, and
    each test fails loudly if the situation changes in either direction.
    """

    def test_code_change_classification_is_still_downstream(self):
        """is_code_change_request re-decides, with a static pattern list, what the door's agent
        already decided via ``is_code_task``. That is a second opinion on an admission question.
        """
        callers = callers_of("is_code_change_request")
        self.assertIn("actions_dispatch.py", callers,
                      "the code-change classifier moved; update the declared gate map")
        self.assertNotIn("cline_entry_door.py", callers,
                         "the code-change classifier is now at the door -- remove this pin")

    def test_door_and_dispatcher_can_disagree_on_code_tasks(self):
        """The door admits on ``is_code_task``; the dispatcher refuses on its own patterns.

        A row the door admitted can therefore be refused downstream by a check the door never
        ran. This test documents that the two decisions are independent, which is the defect.
        """
        source = (HERE / "cline_entry_door.py").read_text(encoding="utf-8")
        self.assertIn('row.get("is_code_task") is not True', source,
                      "the door's own code-task gate changed")
        # The dispatcher's classifier is fail-open and pattern-based, so it is a different
        # decision function over different evidence.
        import actions_dispatch as dispatch
        self.assertTrue(callable(dispatch.is_code_change_request))

    def test_capacity_and_intent_gates_are_still_downstream(self):
        """Capacity and query-exclusion stay downstream; repository intent no longer does.

        Measured 2026-11-01: ``repository_intent`` ran nowhere on the live path. The brief told
        the agent that a repository which does not merge outside work would be refused, and
        nothing enforced it: ``admit()`` never calls it, ``sovereign_discovery`` never calls it,
        and the only caller was the dispatcher loop that the entry door bypasses. It runs at the
        door now (``intent_refusal``), so this pin is split in two.
        """
        for gate in ("precheck_repository_intent", "capacity_exclusions",
                     "query_exclusion_status", "has_not_a_defect_label"):
            callers = callers_of(gate)
            self.assertIn("actions_dispatch.py", callers,
                          gate + " moved; update the declared gate map")
            self.assertNotIn("cline_entry_door.py", callers,
                             gate + " is now at the door -- remove this pin")

    def test_repository_intent_now_runs_at_the_door(self):
        """The promise in the brief is enforced where the brief says it is."""
        self.assertTrue(hasattr(door, "intent_refusal"),
                        "the door lost its repository-intent gate")
        self.assertIn("cline_entry_door.py", callers_of("intent_refusal"),
                      "intent_refusal is defined but never called")
        source = (HERE / "cline_entry_door.py").read_text(encoding="utf-8")
        self.assertIn("INTENT_GATE", source)
        # And it is still the same rule, not a second copy of it.
        self.assertIn("from bounty_admission import repository_intent", source,
                      "the door must call admission's rule, not reimplement it")


class EscrowOnlyReachesEveryLane(unittest.TestCase):
    """The escrow-only rule is a mission invariant, not a lane setting.

    Measured 2026-11-06 by a docs-only audit that had no source tree: it found that
    ``bounty-hydration.yml`` set no ``BOUNTY_ESCROW_ONLY`` while discovery did, and
    reported the deeper question - does the check live below the env layer - as unproven.
    It did not. The rule existed only inside ``admit()``, and the hydration drain replays
    the durable queue through ``sovereign_discovery.ingest``, which never called it. Two
    lanes, one rule: adding this class is what makes the fix a fix.
    """

    def test_the_drain_lane_enforces_the_same_escrow_rule(self):
        callers = callers_of("escrow_only_refusal")
        self.assertIn("bounty_admission.py", callers,
                      "admit() must call the shared predicate, not a private copy")
        self.assertIn("sovereign_discovery.py", callers,
                      "the drain lane re-admits from the durable queue; it must enforce escrow too")

    def test_the_door_and_the_drain_import_the_one_predicate(self):
        for name in ("bounty_admission.py", "sovereign_discovery.py"):
            source = (HERE / name).read_text(encoding="utf-8")
            self.assertIn("escrow_only_refusal", source, name + " lost the escrow gate")
        # No second implementation of the rule anywhere in the tree.
        for path in HERE.glob("*.py"):
            if path.name.startswith(("test_", "debug_", "fix_", "migrate_", "replay_")):
                continue
            body = path.read_text(encoding="utf-8")
            self.assertNotIn("NO_PLATFORM_ESCROW'", body.replace(
                "return \"NO_PLATFORM_ESCROW\"", ""), path.name +
                " defines its own escrow refusal string")

    def test_the_flag_is_read_when_it_is_needed_not_at_import(self):
        import bounty_admission as admission
        with mock.patch.object(admission, "ESCROW_ONLY", False):
            with mock.patch.dict(os.environ, {"BOUNTY_ESCROW_ONLY": "1"}, clear=False):
                self.assertTrue(admission.escrow_only_enabled(),
                                "a lane that opts in must be able to, after import")
            with mock.patch.dict(os.environ, {"BOUNTY_ESCROW_ONLY": "0"}, clear=False):
                self.assertFalse(admission.escrow_only_enabled(),
                                 "a lane that opts out must be able to")
        with mock.patch.object(admission, "ESCROW_ONLY", True):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BOUNTY_ESCROW_ONLY", None)
                self.assertTrue(admission.escrow_only_enabled(),
                                "unset must still follow the import-time default")

    def test_every_workflow_that_dispatches_live_sets_the_escrow_flag(self):
        """The check a script can do that a human missed: read the workflows themselves.

        A mission invariant that one workflow forgets is not an invariant, and the failure
        is silent because the drain's refusals land in an artifact nobody reads until the
        next audit. Every job that buys work with ``--live`` declares the same rule.

        The workflow files are read as text, not through a YAML dependency the runner is
        not guaranteed to have. Jobs are the two-space keys under ``jobs:``, so a job block
        is delimited by those keys - enough structure to answer the one question asked:
        does the job that dispatches live declare the flag.
        """
        checked = 0
        for path in sorted((HERE.parent / ".github" / "workflows").glob("*.yml")):
            lines = path.read_text(encoding="utf-8").splitlines()
            start = next((i for i, line in enumerate(lines) if line.startswith("jobs:")), None)
            if start is None:
                continue
            jobs, current = [], None
            for line in lines[start + 1:]:
                if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
                    current = [line]
                    jobs.append(current)
                elif current is not None:
                    current.append(line)
            for job in jobs:
                body = "\n".join(job)
                if "actions_dispatch.py" not in body or "--live" not in body:
                    continue
                checked += 1
                self.assertIn("BOUNTY_ESCROW_ONLY", body,
                              path.name + " dispatches live without declaring escrow-only")
        self.assertEqual(2, checked, "the workflow scan matched an unexpected number of jobs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
