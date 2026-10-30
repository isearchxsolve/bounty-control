"""F2: a non-default base can be declared truthfully, and a false claim still refused.

Measured need. Run ``40729296273`` (``librepods-org/librepods#878``) prepared on the right
branch and labelled it ``main``. The harness refused -- correctly, because the SHA was not on
``main`` -- and there was then no way forward at all: declaring the truth was not expressible
in the contract. The fix is a first-class ``base_branch`` field with the ancestry rule
applied to that branch, so the honest declaration is verifiable and the dishonest one is
still caught by the same code path.

The live payloads that decide tests 6 and 7 were read from the API, not assumed::

    gh api repos/librepods-org/librepods/compare/3d4d2703da...main
    -> status "diverged", ahead_by 41, behind_by 54, head 89356c08ce
    gh api repos/librepods-org/librepods/compare/3d4d2703da...android/rewrite
    -> status "identical", ahead_by 0, behind_by 0, no commits

So the same artefact refuses against ``main`` and is admitted against ``android/rewrite``.

Tests 6 and 7 must pass together. A fix that only achieves 7 has merely allowed a claim; it
has not kept the false one out, which is why test 6 must never be deleted.

Everything here drives the real gate (``baseline_relationship``): resolve the declaration
server-side, measure the compare, write the receipt, then decide. No re-implementation.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import actions_delivery  # noqa: E402  (path must be set first)
from actions_github import GitHubError  # noqa: E402

REPO = "owner/repo"
COMPONENT = "internal/painter/atlas.go"

# The librepods artefact, verbatim, and the live branch map read on 2026-10-29.
LIBREPODS_BASE = "3d4d2703da39e9903e9789484b838bd5a0930207"
LIBREPODS_MAIN = "89356c08cea3db0b6b54792d9329d09a87cc85fa"
LIBREPODS_ANDROID = LIBREPODS_BASE

DIVERGED = {"status": "diverged", "ahead_by": 41, "behind_by": 54,
            "commits": [{"sha": LIBREPODS_MAIN}], "files": [{"filename": "app/build.gradle"}]}
IDENTICAL_MAIN = {"status": "identical", "ahead_by": 0, "behind_by": 0,
                  "commits": [{"sha": LIBREPODS_MAIN}], "files": []}
# 3d4d2703da IS the head of android/rewrite, so that comparison is identical with no commits.
IDENTICAL_ANDROID = {"status": "identical", "ahead_by": 0, "behind_by": 0,
                     "commits": [], "files": []}


class FakeApi:
    """The two endpoints the gate touches: branch lookup and compare."""

    def __init__(self, branches, comparisons):
        self.branches = dict(branches)
        self.comparisons = dict(comparisons)
        self.calls = []
        self.failures = {}

    def api(self, path, method="GET", payload=None):
        self.calls.append(path)
        if path in self.failures:
            raise self.failures[path]
        if "/branches/" in path:
            name = path.split("/branches/", 1)[1]
            if name not in self.branches:
                raise GitHubError("gh api repos/{}/branches/{}: HTTP 404 Not Found".format(REPO, name))
            return {"name": name, "commit": {"sha": self.branches[name]}}
        if "/compare/" in path:
            spec = path.split("/compare/", 1)[1]
            if spec not in self.comparisons:
                raise AssertionError("unexpected compare " + spec)
            return self.comparisons[spec]
        raise AssertionError("unexpected path " + path)

    @property
    def compared(self):
        return [call for call in self.calls if "/compare/" in call]


def prepared_for(base_sha, base_branch=None, default_branch="main"):
    prepared = {"base_sha": base_sha, "default_branch": default_branch,
                "plan": {"component": COMPONENT},
                "regression_plan": {"component": COMPONENT}}
    if base_branch is not None:
        prepared["base_branch"] = base_branch
    return prepared


class BaseBranchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipt = Path(self.tmp.name) / "baseline-relationship.json"

    def gate(self, api, prepared):
        return actions_delivery.baseline_relationship(api, REPO, prepared, self.receipt)

    def test_1_absent_field_behaves_exactly_as_before(self):
        """No ``base_branch``: the declaration defaults to ``default_branch``."""
        api = FakeApi({"main": "a" * 40}, {"{}...main".format("a" * 40): IDENTICAL_MAIN})
        record = self.gate(api, prepared_for("a" * 40))
        self.assertEqual(record["base_branch"], "main")
        self.assertEqual(api.calls[0], "repos/{}/branches/main".format(REPO))

    def test_2_field_equal_to_default_is_the_same_outcome(self):
        api = FakeApi({"main": "a" * 40}, {"{}...main".format("a" * 40): IDENTICAL_MAIN})
        record = self.gate(api, prepared_for("a" * 40, base_branch="main"))
        self.assertEqual(record["base_branch"], "main")
        self.assertEqual(record["status"], "identical")

    def test_3_real_non_default_branch_at_its_head_is_admitted_and_recorded(self):
        """At its own head on the declared feature branch: the work belongs there."""
        api = FakeApi({"android/rewrite": LIBREPODS_ANDROID},
                      {"{}...android/rewrite".format(LIBREPODS_ANDROID): IDENTICAL_ANDROID})
        prepared = prepared_for(LIBREPODS_ANDROID, base_branch="android/rewrite")
        record = self.gate(api, prepared)
        self.assertEqual(record["base_branch"], "android/rewrite")
        self.assertEqual(record["branch_head"], LIBREPODS_ANDROID)
        self.assertEqual(record["status"], "identical")
        self.assertEqual(record["live_sha"], LIBREPODS_ANDROID)
        self.assertEqual(prepared["base_branch"], "android/rewrite")
        self.assertEqual(json.loads(self.receipt.read_text(encoding="utf-8"))["base_branch"],
                         "android/rewrite")

    def test_4_wrong_branch_for_the_sha_is_refused(self):
        """Declaring ``main`` while holding a SHA from elsewhere: still a refusal."""
        api = FakeApi({"main": LIBREPODS_MAIN, "android/rewrite": LIBREPODS_ANDROID},
                      {"{}...main".format(LIBREPODS_ANDROID): DIVERGED})
        with self.assertRaises(ValueError) as raised:
            self.gate(api, prepared_for(LIBREPODS_ANDROID, base_branch="main"))
        self.assertIn("not the current upstream default", str(raised.exception))

    def test_5_a_branch_that_does_not_exist_never_reaches_a_diff(self):
        """An invented branch is refused before any compare, so no diff can name it."""
        api = FakeApi({"main": "a" * 40}, {})
        invented = "feature/does-not-exist"
        with self.assertRaises(ValueError) as raised:
            self.gate(api, prepared_for("a" * 40, base_branch=invented))
        self.assertIn("does not exist", str(raised.exception))
        self.assertEqual(api.compared, [], "no compare may run for a branch the server lacks")
        self.assertEqual(len(api.calls), 1, "only the branch probe may be issued")
        self.assertNotIn(invented, str(self.receipt), "nothing may be written naming it")

    def test_6_librepods_false_base_is_still_refused(self):
        """Regression guard -- this test must never be deleted (F2 acceptance)."""
        api = FakeApi({"main": LIBREPODS_MAIN, "android/rewrite": LIBREPODS_ANDROID},
                      {"{}...main".format(LIBREPODS_ANDROID): DIVERGED})
        with self.assertRaises(ValueError) as raised:
            self.gate(api, prepared_for(LIBREPODS_ANDROID, base_branch="main"))
        self.assertIn("not the current upstream default", str(raised.exception))
        # The refusal must still be auditable even though no verdict was reached.
        written = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "diverged")
        self.assertEqual(written["base_branch"], "main")

    def test_7_librepods_truthful_base_is_admitted(self):
        """The same artefact, declared honestly, is deliverable -- the point of F2."""
        api = FakeApi({"main": LIBREPODS_MAIN, "android/rewrite": LIBREPODS_ANDROID},
                      {"{}...android/rewrite".format(LIBREPODS_ANDROID): IDENTICAL_ANDROID})
        record = self.gate(api, prepared_for(LIBREPODS_ANDROID, base_branch="android/rewrite"))
        self.assertEqual(record["base_branch"], "android/rewrite")
        self.assertEqual(record["base"], LIBREPODS_ANDROID)
        self.assertEqual(record["status"], "identical")
        # Test 6 and test 7 are the same artefact under two declarations: only the honest
        # one may reach a deliverable verdict, and the dishonest one must not.
        self.assertEqual(api.compared, ["repos/{}/compare/{}...android/rewrite".format(
            REPO, LIBREPODS_ANDROID)])

    def test_a_transient_api_error_is_not_recorded_as_a_bad_declaration(self):
        """A slow server must never be reported as an invented branch."""
        api = FakeApi({"main": "a" * 40}, {})
        api.failures["repos/{}/branches/main".format(REPO)] = GitHubError(
            "gh api: HTTP 502 Bad Gateway")
        with self.assertRaises(GitHubError):
            self.gate(api, prepared_for("a" * 40))
        self.assertFalse(self.receipt.exists(), "no receipt may claim a relationship was measured")

    def test_a_branch_without_a_head_commit_is_refused(self):
        api = FakeApi({"main": "a" * 40}, {})
        api.api = lambda path, method="GET", payload=None: {"name": "main", "commit": {}}
        with self.assertRaises(ValueError) as raised:
            self.gate(api, prepared_for("a" * 40))
        self.assertIn("no head commit", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
