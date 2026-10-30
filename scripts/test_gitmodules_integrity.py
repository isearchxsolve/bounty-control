"""A committed gitlink with no .gitmodules entry breaks every workflow at checkout.

Measured 2026-10-30: commit `b1cfd41` recorded `_bp_audit/_h` and `_proof_repo` as submodule
gitlinks with no matching `.gitmodules` stanza, so `actions/checkout` died before any job could run:

    fatal: No url found for submodule path '_bp_audit/_h' in .gitmodules

Discovery had been failing every 20 minutes since. This is the second occurrence of the same class
(`_bounty_repo` did it earlier and was only ignored by hand), so the rule is pinned here instead of
being remembered: every mode-160000 entry in the index must have a `.gitmodules` path, and every
`.gitmodules` path must exist in the index with that mode.
"""
import subprocess
import unittest


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)


def repo_available():
    result = git("rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def index_gitlinks():
    result = git("ls-files", "-s")
    if result.returncode != 0:
        raise unittest.SkipTest("cannot read the index: " + (result.stderr or "")[:200])
    links = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "160000":
            links.add(parts[3])
    return links


def declared_submodules():
    result = git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$")
    if result.returncode != 0:
        return set()
    return {line.split(None, 1)[1].strip() for line in result.stdout.splitlines() if line.strip()}


@unittest.skipUnless(repo_available(), "not a git work tree")
class GitmodulesIntegrityTests(unittest.TestCase):

    def test_every_gitlink_is_declared_or_absent(self):
        undeclared = sorted(index_gitlinks() - declared_submodules())
        self.assertEqual(
            [], undeclared,
            "these paths are committed as submodules with no .gitmodules url, so "
            "actions/checkout fails for every workflow: " + ", ".join(undeclared))

    def test_every_declared_submodule_is_actually_a_gitlink(self):
        dangling = sorted(declared_submodules() - index_gitlinks())
        self.assertEqual([], dangling,
                         "declared in .gitmodules but not a gitlink in the index: "
                         + ", ".join(dangling))


if __name__ == "__main__":
    unittest.main()
