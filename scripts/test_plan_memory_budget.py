"""The verification plan must not schedule a command this runner cannot survive.

Measured 2026-10-30: preparation of Expensify/App (3.39 GB, 102,333) reached 14 GiB of the ~7 GiB
available and the host killed the job at exit 143, twice. Expensify's own CI runs the same suite on
8 and 16 vCPU runners with warm caches and documents a ~12 GB cold-worker cost, so the command is
legitimate - it is simply not legitimate here. These tests pin the budget, not the commands.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import kaggle_engine_worker as worker


def node_arch(**extra):
    arch = {"ecosystems": ["nodejs"], "package_manager": "npm",
            "has_tests": True, "has_linter": True}
    arch.update(extra)
    return arch


class WorktreeMeasurementTests(unittest.TestCase):

    def test_git_and_install_output_do_not_count(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "src.py").write_bytes(b"x" * 100)
            for ignored in (".git", "node_modules", ".venv"):
                Path(root, ignored).mkdir()
                Path(root, ignored, "blob.bin").write_bytes(b"y" * 10000)
            self.assertEqual(worker._worktree_bytes(root, limit=10 ** 9), 100)

    def test_measurement_stops_past_the_limit(self):
        with tempfile.TemporaryDirectory() as root:
            for index in range(20):
                Path(root, "f%02d.bin" % index).write_bytes(b"z" * 1000)
            # Returns past the limit without walking everything; the exact total is not a promise.
            self.assertGreater(worker._worktree_bytes(root, limit=1500), 1500)

    def test_missing_worktree_is_zero(self):
        self.assertEqual(worker._worktree_bytes(os.path.join(tempfile.gettempdir(), "nope-xyz")), 0)


class PlanBudgetTests(unittest.TestCase):

    def test_small_repository_keeps_workspace_commands(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "package.json").write_text("{}", encoding="utf-8")
            plan = worker.discover_verification_plan(node_arch(), root)
        self.assertIn(["npm", "test"], plan.baseline_tests)
        self.assertIn(["npm", "test"], plan.final_tests)
        self.assertIn(["npm", "run", "lint"], plan.linters)

    def test_heavy_repository_gets_no_workspace_command(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "package.json").write_text("{}", encoding="utf-8")
            Path(root, "big.bin").write_bytes(b"b" * 4096)
            with mock.patch.object(worker, "HEAVY_WORKTREE_BYTES", 1024):
                plan = worker.discover_verification_plan(node_arch(), root)
        self.assertEqual(plan.baseline_tests, [])
        self.assertEqual(plan.final_tests, [])
        self.assertEqual(plan.linters, [])

    def test_deferral_is_announced_not_silent(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "package.json").write_text("{}", encoding="utf-8")
            Path(root, "big.bin").write_bytes(b"b" * 4096)
            with mock.patch.object(worker, "HEAVY_WORKTREE_BYTES", 1024), \
                    mock.patch("builtins.print") as printed:
                worker.discover_verification_plan(node_arch(), root)
        payload = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("PLAN_REPO_WIDE_DEFERRED", payload)

    def test_lockfile_selects_the_frozen_install(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "package-lock.json").write_text("{}", encoding="utf-8")
            plan = worker.discover_verification_plan(node_arch(), root)
        self.assertIn(["npm", "ci", "--prefer-offline"], plan.bootstrap)

    def test_no_lockfile_falls_back_to_install(self):
        # `npm ci` refuses to run without a lockfile; falling back keeps repos that ship none.
        with tempfile.TemporaryDirectory() as root:
            plan = worker.discover_verification_plan(node_arch(), root)
        self.assertIn(["npm", "install", "--prefer-offline"], plan.bootstrap)

    def test_existing_node_modules_is_not_reinstalled(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "node_modules").mkdir()
            plan = worker.discover_verification_plan(node_arch(), root)
        self.assertEqual(plan.bootstrap, [])

    def test_heavy_module_go_test_targets_current_package_only(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "go.mod").write_text("module x\n", encoding="utf-8")
            Path(root, "big.bin").write_bytes(b"b" * 4096)
            with mock.patch.object(worker, "HEAVY_WORKTREE_BYTES", 1024):
                plan = worker.discover_verification_plan(
                    {"ecosystems": ["go"], "has_tests": True, "has_linter": True}, root)
        self.assertIn(["go", "test", "./"], plan.baseline_tests)
        self.assertNotIn("...", " ".join(plan.baseline_tests[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
