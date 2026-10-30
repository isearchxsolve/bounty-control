"""The engine must know which account it is.

Two production failures on 2026-10-29, both from a compiled-in account name:

  * ``discovery-heartbeat`` run 40865557648 probed ``niloydassana-maker`` while running in
    ``isearchxsolve``, found that account's stale run, tried to dispatch there and died with
    ``HTTP 403: Must have admin rights to Repository`` -- so the loop that exists to cover a
    stalled cron was itself dark, by construction.
  * the delivery path builds the PR head as ``{BOUNTY_ACCOUNT}:{branch}`` and the fork URL as
    ``https://github.com/{BOUNTY_ACCOUNT}/{repo}``, so the first real PR from the survivor
    would have been opened as the retired account.

Each module reads its default at import time, so the contract is checked in a subprocess with
the environment Actions actually provides.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import discovery_heartbeat  # noqa: E402


def resolve(module, repository, extra=None):
    """Import ``module`` in a fresh interpreter and print its resolved BOUNTY_ACCOUNT."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOUNTY_ACCOUNT", "BOUNTY_REPOSITORY", "GITHUB_REPOSITORY")}
    if repository is not None:
        env["GITHUB_REPOSITORY"] = repository
    env.update(extra or {})
    code = ("import sys; sys.path.insert(0, %r); import %s as m; "
            "print(getattr(m, 'BOUNTY_ACCOUNT', '') or getattr(m, '_ACCOUNT', ''))"
            % (str(HERE), module))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, cwd=str(HERE.parent), timeout=120)
    if result.returncode != 0:
        raise AssertionError(result.stderr[-800:])
    return result.stdout.strip()


class EngineIdentityTests(unittest.TestCase):
    MODULES = ("actions_github", "bounty_admission", "kaggle_engine_worker")

    def test_each_module_resolves_the_owning_account_from_the_workflow_repo(self):
        for module in self.MODULES:
            with self.subTest(module=module):
                self.assertEqual(
                    resolve(module, "isearchxsolve/anonym-family-archive"), "isearchxsolve")

    def test_the_resolved_account_follows_the_repo_it_runs_in(self):
        for module in self.MODULES:
            with self.subTest(module=module):
                self.assertEqual(
                    resolve(module, "some-other-owner/anonym-family-archive"), "some-other-owner")

    def test_an_explicit_override_still_wins(self):
        for module in self.MODULES:
            with self.subTest(module=module):
                self.assertEqual(
                    resolve(module, "isearchxsolve/anonym-family-archive",
                            {"BOUNTY_ACCOUNT": "deliberate-account"}),
                    "deliberate-account")

    def test_no_module_defaults_to_the_retired_account(self):
        """The literal must be gone, not merely overridden by the workflow environment."""
        for module in self.MODULES:
            source = (HERE / (module + ".py")).read_text(encoding="utf-8-sig")
            with self.subTest(module=module):
                self.assertNotIn('"niloydassana-maker"', source)


class HeartbeatTargetTests(unittest.TestCase):
    def test_the_heartbeat_watches_the_repository_it_runs_in(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BOUNTY_REPOSITORY", "GITHUB_REPOSITORY")}
        env["GITHUB_REPOSITORY"] = "isearchxsolve/anonym-family-archive"
        code = ("import sys; sys.path.insert(0, %r); import discovery_heartbeat as m; "
                "print(m.DEFAULT_REPO)" % str(HERE))
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                env=env, cwd=str(HERE.parent), timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertEqual(result.stdout.strip(), "isearchxsolve/anonym-family-archive")


class VerdictReportingTests(unittest.TestCase):
    """A refused dispatch must not be reported as a healthy hold."""

    def _run(self, dispatch_result):
        args = mock.Mock(repo="o/r", workflow="bounty-discovery.yml", ref="master",
                         max_age_minutes=20, cooldown_minutes=20, state="")
        with tempfile.TemporaryDirectory() as tmp:
            args.state = str(Path(tmp) / "state.jsonl")
            out = StringIO()
            with mock.patch.object(discovery_heartbeat, "probe", return_value=[]), \
                    mock.patch.object(discovery_heartbeat, "dispatch",
                                      return_value=dispatch_result), \
                    mock.patch.object(discovery_heartbeat, "record"), \
                    mock.patch.object(discovery_heartbeat, "last_fire", return_value=None), \
                    redirect_stdout(out):
                status = discovery_heartbeat.evaluate(args, dry_run=False)
        return status, out.getvalue()

    def test_a_refused_dispatch_is_reported_as_a_dispatch_failure(self):
        status, output = self._run((False, "HTTP 403: Must have admin rights to Repository"))
        self.assertEqual(status, 2, "a refused dispatch must fail the beat")
        self.assertIn("DISPATCH_FAILED", output)
        self.assertIn("Must have admin rights", output)
        self.assertNotIn("VERDICT: HOLD stale", output)

    def test_a_successful_dispatch_is_reported_as_fired(self):
        status, output = self._run((True, "ok"))
        self.assertEqual(status, 0)
        self.assertIn("VERDICT: FIRED bounty-discovery.yml", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
