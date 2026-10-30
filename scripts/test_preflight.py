#!/usr/bin/env python3
"""F7 contract: runner preflight assertions and their classification.

The check helpers must return ``(subsystem, ok, detail)``. They previously returned
``(ok, detail)`` while ``preflight`` unpacked three values, so every delivery run that reached
preflight raised ``ValueError`` before Cline started -- and a ValueError is recorded as an
enginering failure. That shape is now asserted directly.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_delivery import (  # noqa: E402
    InfrastructureFault, check_disk_space, check_executable, check_free_memory,
    check_git_version, preflight)


class PreflightShapeTests(unittest.TestCase):
    def test_every_check_returns_a_subsystem_ok_detail_triple(self):
        for check in (check_disk_space("."), check_free_memory(), check_executable("git"),
                      check_git_version()):
            self.assertEqual(len(check), 3, "check must be (subsystem, ok, detail)")
            subsystem, ok, detail = check
            self.assertIsInstance(subsystem, str)
            self.assertTrue(subsystem)
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(detail, str)

    def test_preflight_accepts_the_real_checks_without_unpacking_errors(self):
        # The regression guard: this raised ValueError before the shape was fixed.
        try:
            preflight([check_git_version("0.1")])
        except InfrastructureFault as exc:  # a genuinely failing check is a different case
            self.assertIn(exc.subsystem, ("git", "disk", "memory", "executable"))
        except ValueError as exc:
            self.fail("preflight unpacked its checks wrongly: " + str(exc))


class PreflightClassificationTests(unittest.TestCase):
    def test_all_checks_passing_raises_nothing(self):
        preflight([("disk", True, "9.0 GB free"), ("memory", True, "4096 MB free"),
                   ("executable", True, "git 2.43.0"), ("git", True, "git 2.43.0")])

    def test_disk_below_floor_names_the_disk_subsystem_and_the_measured_figure(self):
        subsystem, ok, detail = check_disk_space(".", min_free_gb=10 ** 9)
        self.assertFalse(ok)
        self.assertIn("GB free", detail)
        with self.assertRaises(InfrastructureFault) as raised:
            preflight([(subsystem, ok, detail)])
        self.assertEqual(raised.exception.subsystem, "disk")
        self.assertIn("GB free", str(raised.exception))

    def test_a_missing_executable_names_the_executable_subsystem(self):
        subsystem, ok, detail = check_executable("definitely-not-installed-xyzq")
        self.assertFalse(ok)
        with self.assertRaises(InfrastructureFault) as raised:
            preflight([(subsystem, ok, detail)])
        self.assertEqual(raised.exception.subsystem, "executable")

    def test_git_version_floor_is_enforced_in_both_directions(self):
        self.assertTrue(check_git_version("0.1")[1])
        subsystem, ok, detail = check_git_version("99.0")
        self.assertFalse(ok)
        self.assertEqual(subsystem, "git")
        self.assertIn("99.0", detail)

    def test_a_failure_is_never_a_plain_value_error_for_the_host_to_misclassify(self):
        with self.assertRaises(InfrastructureFault):
            preflight([("memory", False, "12 MB free (need 512 MB)")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
