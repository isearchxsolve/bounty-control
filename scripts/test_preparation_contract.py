"""The preparation prompt must not conflate the defect with a broken environment.

Measured 2026-10-29, run 40873893992: a proof repository whose own test suite is red because
the reported bug exists was classified BLOCKED_BASELINE, with a correct diagnosis --

  "the remaining baseline failure is a genuine upstream product defect, not an
   environment/tooling problem ... per the baseline policy an upstream product/test
   defect is BLOCKED_BASELINE and must not be fixed to manufacture a green baseline"

The reasoning was sound and the contract was not: ``verify_baseline`` runs
``plan.baseline_tests`` and treats any non-zero exit as an unhealthy environment, while the
prompt separately asks for ``regression_plan.expected_failure`` -- a command that fails on the
untouched base. The two requirements pointed at the same command, so any repository with a
pre-existing failing test was undeliverable, which is the normal shape of a bug report.

The gate is unchanged: ``baseline_tests`` must still be green. What changed is the instruction,
which now says which commands belong where.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_delivery  # noqa: E402


class PromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "kaggle_engine_worker.py").read_text(encoding="utf-8-sig")

    def test_the_prompt_separates_baseline_tests_from_the_reproduction(self):
        self.assertIn("TWO KINDS OF BASELINE COMMAND", self.source)
        self.assertIn("`baseline_tests` MUST pass on the untouched base", self.source)
        self.assertIn("`regression_plan.command` is the reproduction", self.source)

    def test_the_prompt_says_a_red_baseline_stops_the_run(self):
        # The consequence has to be stated, or an agent will keep putting the defect there.
        self.assertIn("a red `baseline_tests` is read as a broken environment", self.source)
        self.assertIn("BLOCKED_BASELINE", self.source)

    def test_the_prompt_says_the_reproduction_is_expected_to_fail_on_base(self):
        self.assertIn("It MUST fail on the untouched", self.source)
        self.assertIn("expected evidence of the defect, not a blocker", self.source)

    def test_the_prompt_covers_a_suite_that_is_already_red(self):
        self.assertIn("put the green subset in `baseline_tests`", self.source)


class PublicationTargetTests(unittest.TestCase):
    """Publication must recognise a repository the bounty account already owns.

    Run 40880332646 engineered and verified a correct commit and then refused to publish with
    ``ValueError: Fork parent mismatch``: the fixture has no fork, and the gate demanded one.
    """

    @classmethod
    def setUpClass(cls):
        # staticmethod: a bare function attribute would bind as a method and take self.
        cls.is_self_owned = staticmethod(actions_delivery.is_self_owned)

    def test_a_self_owned_repository_is_recognised(self):
        self.assertTrue(self.is_self_owned("isearchxsolve", "isearchxsolve/bounty-proof"))

    def test_a_third_party_repository_is_not(self):
        self.assertFalse(self.is_self_owned("isearchxsolve", "Expensify/App"))

    def test_a_name_prefix_does_not_impersonate_the_owner(self):
        # A repository named after the owner but owned by someone else is not ours.
        self.assertFalse(self.is_self_owned("isearchx", "isearchxsolve/bounty-proof"))
        self.assertFalse(self.is_self_owned("isearchxsolve", "isearchxsolveextra/x"))

    def test_case_is_ignored(self):
        self.assertTrue(self.is_self_owned("ISearchXSolve", "isearchxsolve/bounty-proof"))

    def test_the_fork_gate_is_skipped_only_for_self_owned_repositories(self):
        source = (HERE / "actions_delivery.py").read_text(encoding="utf-8-sig")
        self.assertIn("if not is_self_owned(account, repo):", source)
        self.assertIn('raise ValueError("Fork parent mismatch")', source)


class ReportPathWiringTests(unittest.TestCase):
    """The adapter must read the path the worker actually used.

    Run 40876500657 failed with ``NameError: name 'report_path' is not defined`` -- the
    adapter's release loop read a document whose path it never resolved. No earlier run had
    reached that line, so the defect sat in production behind a gate it could not pass.
    """

    def test_the_worker_publishes_the_report_path_it_used(self):
        worker = (HERE / "kaggle_engine_worker.py").read_text(encoding="utf-8-sig")
        self.assertIn("report['report_path'] = report_path", worker)

    def test_the_adapter_reads_the_path_from_the_prepared_document(self):
        delivery = (HERE / "actions_delivery.py").read_text(encoding="utf-8-sig")
        self.assertIn('report_path = Path(prepared["report_path"])', delivery)

    def test_no_undefined_name_survives_on_the_scheduled_modules(self):
        """Whatever else changes, the scheduled modules must parse without undefined names.

        The workflow runs ``ruff --select F821`` over exactly these files; this test proves
        the source of that list is clean so a local run fails before the gate does.
        """
        import subprocess
        modules = [
            "actions_github.py", "actions_dispatch.py", "actions_delivery.py",
            "actions_reconcile.py", "actions_release.py", "bounty_admission.py",
            "bounty_fx.py", "kaggle_engine_worker.py", "delivery_supervisor.py",
            "delivery_errors.py", "discovery_heartbeat.py", "failure_digest.py",
            "f11_refusal_census.py",
        ]
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--select", "F821",
                 *[str(HERE / name) for name in modules]],
                capture_output=True, text=True, timeout=120)
        except (FileNotFoundError, OSError):  # pragma: no cover - ruff is a dev tool
            self.skipTest("ruff is not installed")
        if result.returncode == 127 or "No module named ruff" in result.stderr:
            self.skipTest("ruff is not installed")
        self.assertEqual(result.returncode, 0,
                         "undefined names on the scheduled modules:\n" + result.stdout[-2000:])


class GateUnchangedTests(unittest.TestCase):
    """The instruction changed; the verification did not."""

    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "kaggle_engine_worker.py").read_text(encoding="utf-8-sig")

    def test_baseline_verification_still_requires_a_green_suite(self):
        self.assertIn("def verify_baseline(worktree: str, plan: VerificationPlan)", self.source)
        self.assertIn("Baseline test failure on untouched upstream", self.source)

    def test_the_blocked_path_still_refuses_to_manufacture_a_green_baseline(self):
        delivery = (HERE / "actions_delivery.py").read_text(encoding="utf-8-sig")
        self.assertIn('raise RuntimeError("BLOCKED_BASELINE: " + diagnostic)', delivery)
        supervisor = (HERE / "delivery_supervisor.py").read_text(encoding="utf-8-sig")
        # The invariant is kept and the case is narrowed (2026-11-01 directive audit): editing
        # the tree to manufacture a green baseline still erases the evidence the delivery exists
        # to produce, and a failing test is never repaired by changing the source. The sentence
        # used to continue "an upstream product/test defect is a finding to record as
        # BLOCKED_BASELINE", which contradicted the preparation directive that the same defect
        # is the regression target: SMALLBETS/userbase#305, a ticket about a broken build, was
        # blocked as an environment fault for exactly that reason.
        self.assertIn("Manufacturing a green baseline by editing that tree erases", supervisor)
        self.assertIn("a failing test is never repaired by changing the source", supervisor)
        self.assertNotIn("An upstream product/test defect is a finding to record as BLOCKED_BASELINE",
                         supervisor)
        self.assertIn("BLOCKED_BASELINE is for what no amount of engineering", supervisor)
        self.assertIn("BLOCKED_BASELINE", supervisor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
