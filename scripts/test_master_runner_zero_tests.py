"""A manifest entry that discovers zero tests is a failure, not a clean OK.

Measured 2026-11-06 on run 42240749100: the contracts job failed 1 of 83 suites on
``test_discovery_queries.py``. Its log read ``Ran 0 tests in 0.000s`` - a module with a
``test_`` prefix that asserts nothing and shells out to ``gh search issues``, which refuses to
run in a GitHub Actions workflow without GH_TOKEN. It was recorded green from the workstation
where I added it, because that ``gh`` is authenticated; the runner blanks GH_CONFIG_DIR, but a
local login is exactly what CI does not have. ``test_normalise_rest.py``, excluded the same
morning for what I believed was the same reason, turned out to be a different defect - one
live-network test that errors without credentials - which is why this file tests the gate as
a pure function on the log rather than through a suite I had already misdiagnosed twice.
"""
import unittest

import run_pipeline_master as master


class ZeroTestDetectionTests(unittest.TestCase):

    def test_unittest_reporting_no_tests_is_detected(self):
        self.assertTrue(master.discovered_no_tests(
            "----------------------------------------------------------------------\n"
            "Ran 0 tests in 0.000s\n"
            "\n"
            "NO TESTS RAN\n"))

    def test_the_suites_own_banner_is_detected_too(self):
        self.assertTrue(master.discovered_no_tests("NO TESTS RAN"))

    def test_a_suite_that_actually_ran_is_not_flagged(self):
        self.assertFalse(master.discovered_no_tests(
            "----------------------------------------------------------------------\n"
            "Ran 12 tests in 0.115s\n"
            "\n"
            "OK\n"))

    def test_a_failing_suite_is_not_what_this_gate_guards(self):
        self.assertFalse(master.discovered_no_tests(
            "FAILED (errors=1)\n"
            "Ran 1 test in 0.001s\n"))

    def test_an_empty_or_broken_log_is_not_a_claim_of_zero_tests(self):
        for body in ("", "ERROR: gh: no credential", "Traceback (most recent call last):"):
            with self.subTest(body=body):
                self.assertFalse(master.discovered_no_tests(body))


if __name__ == "__main__":
    unittest.main()
