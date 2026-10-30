#!/usr/bin/env python3
"""F10 contract: the patch download path must never be blocked by submodule machinery.

The recorded failure is ``fatal: No url found for submodule path during repo in .gitmodules``.
Every case here is either a pure parse or a real local git repository, so nothing is asserted
by inspecting source text.
"""
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions_delivery import (  # noqa: E402
    InfrastructureFault, download_patch, malformed_submodules, submodule_without_url)

VALID = '[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = https://example.invalid/lib.git\n'
NO_URL = '[submodule "vendor/lib"]\n\tpath = vendor/lib\n'


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], check=check,
                          capture_output=True, text=True)


class ParserTests(unittest.TestCase):
    def test_a_valid_gitmodules_has_no_broken_section(self):
        self.assertIsNone(submodule_without_url(VALID))

    def test_an_entry_without_a_url_is_named(self):
        self.assertEqual(submodule_without_url(NO_URL), '[submodule "vendor/lib"]')

    def test_a_second_valid_entry_does_not_mask_a_broken_first_one(self):
        text = NO_URL + '[submodule "b"]\n\tpath = b\n\turl = https://example.invalid/b.git\n'
        self.assertEqual(submodule_without_url(text), '[submodule "vendor/lib"]')

    def test_a_commented_url_does_not_count_as_a_url(self):
        text = '[submodule "x"]\n\tpath = x\n\t# url = https://example.invalid/x.git\n'
        self.assertEqual(submodule_without_url(text), '[submodule "x"]')

    def test_no_gitmodules_at_all_is_not_a_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(malformed_submodules(directory))

    def test_a_malformed_file_is_reported_with_its_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".gitmodules").write_text(NO_URL, encoding="utf-8")
            self.assertEqual(malformed_submodules(directory), '[submodule "vendor/lib"]')
            with self.assertRaises(InfrastructureFault) as raised:
                download_patch(directory, {"owned_pr_number": 1, "owned_head": "0" * 40},
                               directory, "0" * 40, "owner/repo")
            self.assertEqual(raised.exception.subsystem, "submodule")
            self.assertIn("owner/repo", str(raised.exception))
            self.assertIn("no url", str(raised.exception).lower())


class RealRepositoryTests(unittest.TestCase):
    def _fixture(self, directory, gitmodules=None):
        """A clone with an ``upstream`` remote holding ``refs/pull/1/head``."""
        upstream = Path(directory, "upstream.git")
        git(directory, "init", "--bare", "-q", str(upstream))
        work = Path(directory, "work")
        git(directory, "clone", "-q", str(upstream), str(work))
        git(work, "config", "user.email", "unit@example.invalid")
        git(work, "config", "user.name", "Unit Fixture")
        Path(work, "package.json").write_text('{"name":"unit"}', encoding="utf-8")
        git(work, "add", "package.json")
        git(work, "commit", "-qm", "base")
        base = git(work, "rev-parse", "HEAD").stdout.strip()
        if gitmodules is not None:
            Path(work, ".gitmodules").write_text(gitmodules, encoding="utf-8")
            git(work, "add", ".gitmodules")
        Path(work, "product.txt").write_text("fixed\n", encoding="utf-8")
        git(work, "add", "product.txt")
        git(work, "commit", "-qm", "change")
        head = git(work, "rev-parse", "HEAD").stdout.strip()
        git(work, "push", "-q", "origin", "HEAD:refs/pull/1/head")
        # The delivery worktree already has the base commit checked out, so clone and reset to
        # it; an empty init would not contain the base object and merge-base would fail.
        root = Path(directory, "root")
        git(directory, "clone", "-q", str(upstream), str(root))
        git(root, "remote", "rename", "origin", "upstream")
        git(root, "reset", "-q", "--hard", base)
        return root, base, head

    def test_a_valid_gitmodules_does_not_initialise_submodules(self):
        # The url is deliberately unreachable: if recursion were on, git would try to fetch it
        # and fail, so a clean apply proves the download path stayed top-level.
        with tempfile.TemporaryDirectory() as directory:
            root, base, head = self._fixture(
                directory, '[submodule "vendor/lib"]\n\tpath = vendor/lib\n'
                           '\turl = https://127.0.0.1:1/never.git\n')
            patch = download_patch(root, {"owned_pr_number": 1, "owned_head": head},
                                   Path(directory), base, "owner/repo")
            self.assertTrue(Path(patch).is_file())
            self.assertTrue(Path(root, "product.txt").is_file())

    def test_a_repository_with_no_submodules_behaves_as_before(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base, head = self._fixture(directory)
            download_patch(root, {"owned_pr_number": 1, "owned_head": head},
                           Path(directory), base, "owner/repo")
            self.assertEqual(Path(root, "product.txt").read_text(encoding="utf-8"), "fixed\n")

    def test_a_changed_owned_head_is_still_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base, head = self._fixture(directory)
            with self.assertRaisesRegex(ValueError, "Owned PR changed"):
                download_patch(root, {"owned_pr_number": 1, "owned_head": "1" * 40},
                               Path(directory), base, "owner/repo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
