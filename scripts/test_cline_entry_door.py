"""The entry door trusts Cline's search and nothing else.

Each test is a way an agent can be wrong: it invents an issue, quotes a title, reports a closed
ticket, or repeats a row. All must be refused with a named reason, because a claim spent on a
row that is not real is the false positive this door exists to stop.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import cline_entry_door as door

_PROFILE_PATCH = None


def setUpModule():
    """A unit test must never run Cline auth or touch the network."""
    global _PROFILE_PATCH
    _PROFILE_PATCH = mock.patch.object(door, "prepare_profile", lambda *a, **k: True)
    _PROFILE_PATCH.start()


def tearDownModule():
    if _PROFILE_PATCH is not None:
        _PROFILE_PATCH.stop()


ISSUE = {
    "state": "open",
    "title": "Add retry to the HTTP client",
    "body": "Requests fail permanently on a transient 503. We pay a $250 bounty for a fix "
            "with bounded retries and tests.",
}


def row(**overrides):
    base = {"repo": "acme/http", "issue": 7,
            "url": "https://github.com/acme/http/issues/7", "is_code_task": True,
            "reward_quote": "We pay a $250 bounty for a fix with bounded retries and tests.",
            "reward_usd": 250, "scope_quote": "Requests fail permanently on a transient 503.",
            "why_now": "clear scope"}
    base.update(overrides)
    return base


def fetcher(document=ISSUE):
    return lambda repo, number: document


class AdmitsVerifiedRows(unittest.TestCase):
    def test_a_row_backed_by_a_real_issue_and_a_real_quote_is_admitted(self):
        result = door.verify_rows([row()], fetcher())
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["admitted"][0]["issue"], 7)
        self.assertEqual(result["refused"], [])


class RefusesUnprovenRows(unittest.TestCase):
    def test_an_issue_that_does_not_exist_is_refused(self):
        result = door.verify_rows([row()], lambda repo, number: None)
        self.assertEqual(result["refused"][0]["reason"], "ISSUE_NOT_FOUND")

    def test_a_closed_issue_is_refused(self):
        result = door.verify_rows([row()], fetcher({**ISSUE, "state": "closed"}))
        self.assertEqual(result["refused"][0]["reason"], "ISSUE_NOT_OPEN")

    def test_a_paraphrased_reward_is_refused(self):
        result = door.verify_rows([row(reward_quote="We will pay 250 dollars for this.")], fetcher())
        self.assertEqual(result["refused"][0]["reason"], "REWARD_QUOTE_NOT_IN_ISSUE")

    def test_an_invented_reward_is_refused(self):
        result = door.verify_rows([row(reward_quote="We pay a $5,000 bounty for a rewrite.")], fetcher())
        self.assertEqual(result["refused"][0]["reason"], "REWARD_QUOTE_NOT_IN_ISSUE")

    def test_a_row_the_agent_itself_called_not_a_code_task_is_refused(self):
        result = door.verify_rows([row(is_code_task=False)], fetcher())
        self.assertEqual(result["refused"][0]["reason"], "AGENT_NOT_A_CODE_TASK")

    def test_a_duplicate_row_is_only_counted_once(self):
        result = door.verify_rows([row(), row()], fetcher())
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["refused"][0]["reason"], "DUPLICATE_ROW")

    def test_a_malformed_row_is_refused_without_calling_github(self):
        calls = []
        result = door.verify_rows([{"repo": "acme/http", "issue": "seven"}],
                                  lambda r, n: calls.append((r, n)) or ISSUE)
        self.assertEqual(result["refused"][0]["reason"], "MALFORMED_ROW")
        self.assertEqual(calls, [], "no API call for a row we cannot use")

    def test_the_row_limit_is_honoured(self):
        rows = [row(issue=n) for n in range(1, 30)]
        result = door.verify_rows(rows, fetcher(), limit=5)
        self.assertEqual(len(result["admitted"]), 5)



class FakePipe:
    """The bits of a subprocess pipe the runner actually uses: readline and close."""

    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""

    def close(self):
        return None


class FakeProcess:
    """Stands in for a streaming Cline process: pipes, exit code, optional hang."""

    def __init__(self, lines=(), exit_code=0, hang=False, on_start=None):
        self._lines = list(lines)
        self._exit = exit_code
        self._hang = hang
        self.stdout = FakePipe(self._lines)
        self.stderr = FakePipe([])
        self._on_start = on_start

    def started(self):
        """Run the side effect when the process is launched, not when the double is built."""
        if self._on_start is not None:
            callback, self._on_start = self._on_start, None
            callback()
        return self

    def wait(self, timeout=None):
        if self._hang:
            raise door.subprocess.TimeoutExpired(cmd="cline", timeout=timeout)
        return self._exit

    def kill(self):
        return None


def fake_popen(process):
    return lambda *args, **kwargs: process.started() if hasattr(process, "started") else process


def offline_run(workdir, process, **kwargs):
    """Run the search with the profile and the child process both faked: no network, no auth."""
    with mock.patch.object(door, "prepare_profile", lambda *a, **k: True),             mock.patch.object(door.subprocess, "Popen", fake_popen(process)):
        return door.run_cline_search(workdir, **kwargs)


class AgentOutputContract(unittest.TestCase):
    def test_rows_are_read_from_the_file_the_agent_writes_not_from_its_prose(self):
        with tempfile.TemporaryDirectory() as workdir:
            def write_shortlist():
                with open(os.path.join(workdir, "shortlist.jsonl"), "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(row()) + "\n")
                    handle.write("this prose line must be ignored\n")

            process = FakeProcess(["working\n"], on_start=write_shortlist)
            with mock.patch.object(door.subprocess, "Popen", fake_popen(process)):
                outcome = door.run_cline_search(workdir)
            self.assertTrue(outcome["wrote_file"])
            self.assertEqual(len(outcome["rows"]), 1)
            self.assertEqual(outcome["rows"][0]["issue"], 7)

    def test_no_file_means_no_rows_even_if_the_agent_exited_cleanly(self):
        with tempfile.TemporaryDirectory() as workdir:
            fake = FakeProcess(["I found nothing\n"])
            with mock.patch.object(door.subprocess, "Popen", fake_popen(fake)):
                outcome = door.run_cline_search(workdir)
            self.assertEqual(outcome["rows"], [])
            self.assertFalse(outcome["wrote_file"])

    def test_a_stale_shortlist_from_a_previous_run_is_cleared(self):
        with tempfile.TemporaryDirectory() as workdir:
            with open(os.path.join(workdir, "shortlist.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(row(issue=999)) + "\n")
            outcome = offline_run(workdir, FakeProcess([]))
            self.assertEqual(outcome["rows"], [], "yesterday's rows must never be re-admitted")

    def test_a_timeout_is_reported_and_yields_no_rows(self):
        import subprocess as real_subprocess
        with tempfile.TemporaryDirectory() as workdir:
            outcome = offline_run(workdir, FakeProcess(hang=True), timeout=1)
            self.assertEqual(outcome["rows"], [])
            self.assertIn("timed out", outcome["tail"])


class PromptShape(unittest.TestCase):
    def test_the_prompt_tells_the_agent_to_search_and_to_write_the_file(self):
        self.assertIn("gh search issues", door.SEARCH_PROMPT)
        self.assertIn("shortlist.jsonl", door.SEARCH_PROMPT)

    def test_the_prompt_names_the_junk_measured_in_production(self):
        for phrase in ("digests", "hackathons", "design-only"):
            self.assertIn(phrase, door.SEARCH_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)


def offline_verify(rows, limit=12):
    """Verify against a fixture issue, never the network: a unit test must not call GitHub."""
    return door.verify_rows(rows, fetch=fetcher(), limit=limit)


class FeedbackLoop(unittest.TestCase):
    """Cline is not judged once and dismissed: refusals come back to it as instructions."""

    def test_a_refusal_reason_reaches_the_agents_next_round(self):
        prompts = []
        rounds = [
            {"exit_code": 0, "rows": [row(reward_quote="paraphrased money")], "tail": "", "wrote_file": True},
            {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True},
        ]

        def run(workdir, prompt=None, **kwargs):
            prompts.append(prompt)
            return rounds[len(prompts) - 1]

        result = door.iterate("W", rounds=3, run=run, verify=offline_verify)
        self.assertEqual(len(prompts), 2, "one correction round")
        self.assertIn("REWARD_QUOTE_NOT_IN_ISSUE", prompts[1])
        self.assertIn("acme/http#7", prompts[1])
        self.assertEqual(len(result["admitted"]), 1)

    def test_the_loop_stops_as_soon_as_nothing_is_refused(self):
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            return {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True}

        result = door.iterate("W", rounds=5, run=run, verify=offline_verify)
        self.assertEqual(len(calls), 1, "a clean round needs no correction")
        self.assertEqual(len(result["admitted"]), 1)

    def test_rounds_are_bounded_even_if_the_agent_never_fixes_anything(self):
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            return {"exit_code": 0, "rows": [row(reward_quote="still paraphrased")],
                    "tail": "", "wrote_file": True}

        result = door.iterate("W", rounds=3, run=run, verify=offline_verify)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["admitted"], [])
        self.assertEqual(result["refused"][0]["reason"], "REWARD_QUOTE_NOT_IN_ISSUE")

    def test_an_admitted_row_is_not_re_admitted_by_a_later_round(self):
        rounds = [
            {"exit_code": 0, "rows": [row(), row(issue=8)], "tail": "", "wrote_file": True},
            {"exit_code": 0, "rows": [row(), row(issue=8)], "tail": "", "wrote_file": True},
        ]
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            return rounds[min(len(calls) - 1, 1)]

        seen = {"n": 0}

        def verify(rows, limit=12):
            seen["n"] += 1
            if seen["n"] == 1:
                return {"admitted": [rounds[0]["rows"][0]], "refused": [{"row": row(issue=8), "reason": "ISSUE_NOT_OPEN"}]}
            return {"admitted": [rounds[1]["rows"][0], rounds[1]["rows"][1]], "refused": []}

        result = door.iterate("W", rounds=3, run=run, verify=verify)
        issues = sorted(r["issue"] for r in result["admitted"])
        self.assertEqual(issues, [7, 8], "no duplicate rows after correction")


class StreamingVisibility(unittest.TestCase):
    """Baba's order: capture Cline's thinking the way the delivery engine does."""

    def test_each_agent_line_is_echoed_and_written_to_the_log(self):
        printed = []
        with tempfile.TemporaryDirectory() as workdir:
            with mock.patch.object(door.subprocess, "Popen",
                                   fake_popen(FakeProcess(["reading issue 78\n", "budget is $900\n"]))):
                with mock.patch("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))):
                    outcome = door.run_cline_search(workdir)
            self.assertTrue(any("reading issue 78" in line for line in printed))
            self.assertTrue(any("budget is $900" in line for line in printed))
            with open(outcome["log"], encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("budget is $900", body)

    def test_the_key_is_redacted_in_the_command_preview(self):
        with tempfile.TemporaryDirectory() as workdir:
            outcome = offline_run(workdir, FakeProcess([]))
            self.assertIn("[REDACTED]", outcome["preview"])
            self.assertNotIn("nvidia-pool", outcome["preview"])


class LaunchResolution(unittest.TestCase):
    """Measured failure: 'cline' on PATH is a shim, so the agent never started (WinError 2)."""

    def test_a_cmd_launcher_is_run_through_cmd_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cline.cmd")
            open(path, "w").close()
            self.assertEqual(door.resolve_cline(path), ["cmd.exe", "/c", path])

    def test_a_plain_binary_is_used_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cline")
            open(path, "w").close()
            self.assertEqual(door.resolve_cline(path), [path])


class EncodingSurvival(unittest.TestCase):
    """Measured: a box-drawing glyph raised UnicodeEncodeError and killed the reader thread."""

    def test_a_line_with_box_glyphs_does_not_break_the_run(self):
        with tempfile.TemporaryDirectory() as workdir:
            def write_shortlist():
                with open(os.path.join(workdir, "shortlist.jsonl"), "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(row()) + "\n")

            process = FakeProcess(["\u23bf read the issue\n"], on_start=write_shortlist)
            with mock.patch.object(door.subprocess, "Popen", fake_popen(process)):
                outcome = door.run_cline_search(workdir)
            self.assertEqual(len(outcome["rows"]), 1, "the run must survive the glyph")
            with open(outcome["log"], encoding="utf-8") as handle:
                self.assertIn("read the issue", handle.read())

    def test_the_transcript_keeps_the_glyph_even_when_stdout_cannot(self):
        with tempfile.TemporaryDirectory() as workdir:
            def write_shortlist():
                with open(os.path.join(workdir, "shortlist.jsonl"), "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(row()) + "\n")

            process = FakeProcess(["\u23bf kept\n"], on_start=write_shortlist)
            with mock.patch.object(door.subprocess, "Popen", fake_popen(process)):
                outcome = door.run_cline_search(workdir)
            with open(outcome["log"], encoding="utf-8") as handle:
                self.assertIn("\u23bf", handle.read(), "the file log keeps the real bytes")


class FreshStart(unittest.TestCase):
    """Baba's order: old context is fine, so each run is told plainly to start fresh."""

    def test_the_search_prompt_opens_with_a_fresh_start_instruction(self):
        self.assertTrue(door.SEARCH_PROMPT.startswith(door.FRESH_START))

    def test_the_feedback_prompt_carries_the_same_instruction(self):
        self.assertTrue(door.FEEDBACK_PROMPT.startswith(door.FRESH_START))

    def test_the_instruction_names_what_to_ignore(self):
        self.assertIn("Ignore any earlier conversation", door.FRESH_START)
        self.assertIn("Nothing was handed to you", door.FRESH_START)

    def test_the_fresh_start_travels_into_a_real_round_prompt(self):
        prompts = []

        def run(workdir, prompt=None, **kwargs):
            prompts.append(prompt)
            return {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True}

        door.iterate("W", rounds=1, run=run, verify=offline_verify)
        self.assertTrue(prompts[0].startswith(door.FRESH_START))


class ProfileCarriesTheGateway(unittest.TestCase):
    """Measured: a profile without baseUrl sent the NVIDIA key straight to OpenAI.

    These tests fake the CLI: they check that auth is called with the gateway and that the
    readback refuses a profile whose base URL was not persisted. No network, no real auth.
    """

    def _fake_auth_that_persists(self, data_dir, base_url, model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                                 expected_url="http://127.0.0.1:8099/v1"):
        def run(command, **kwargs):
            os.makedirs(os.path.join(data_dir, "settings"), exist_ok=True)
            with open(os.path.join(data_dir, "settings", "providers.json"), "w", encoding="utf-8") as handle:
                json.dump({"providers": {"openai-compatible": {"settings": {
                    "model": model, "baseUrl": base_url, "apiKey": "nvidia-pool"}}}}, handle)
            self.assertIn("--baseurl", command)
            self.assertEqual(command[command.index("--baseurl") + 1], expected_url)
            return mock.Mock(returncode=0, stdout="", stderr="")
        return run

    def test_auth_is_called_with_the_gateway_and_the_readback_passes(self):
        with tempfile.TemporaryDirectory() as data_dir:
            fake = self._fake_auth_that_persists(data_dir, "http://127.0.0.1:8099/v1")
            with mock.patch.object(door.subprocess, "run", fake),                     mock.patch.object(door, "resolve_cline", lambda *a, **k: ["cline"]):
                self.assertTrue(door.REAL_PREPARE_PROFILE(data_dir, base_url="http://127.0.0.1:8099/v1"))

    def test_readback_refuses_a_profile_that_lost_its_base_url(self):
        with tempfile.TemporaryDirectory() as data_dir:
            fake = self._fake_auth_that_persists(data_dir, "", expected_url="http://127.0.0.1:8099/v1")
            with mock.patch.object(door.subprocess, "run", fake),                     mock.patch.object(door, "resolve_cline", lambda *a, **k: ["cline"]):
                self.assertFalse(door.REAL_PREPARE_PROFILE(data_dir, base_url="http://127.0.0.1:8099/v1"))


class FreshWorkspace(unittest.TestCase):
    """Measured: mixing separators made Windows refuse the path and the run died at once."""

    def test_the_workspace_is_a_single_clean_directory_with_one_separator_style(self):
        with tempfile.TemporaryDirectory() as root:
            path = door.fresh_workspace(root.replace("\\", "/"))
            self.assertTrue(os.path.isdir(path), path)
            self.assertNotIn("/\\", path.replace(os.sep, "/") + "/")
            os.makedirs(path, exist_ok=True)  # idempotent, no WinError 123

    def test_each_call_returns_a_different_directory(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertNotEqual(door.fresh_workspace(root), door.fresh_workspace(root))

    def test_the_prompt_forbids_exploring_the_machine(self):
        """Measured: an empty workspace inside the repo made the agent read our own source."""
        self.assertIn("Do not explore this machine", door.SEARCH_PROMPT)
        self.assertIn("STEP 1", door.SEARCH_PROMPT)
        self.assertIn("GitHub", door.SEARCH_PROMPT)


class EngineParity(unittest.TestCase):
    """The delivery engine's flag set is the one proven to work; extra flags broke runs today."""

    def _command(self, **kwargs):
        captured = []

        def fake(process_command, **other):
            captured.append(process_command)
            return FakeProcess([])

        with mock.patch.object(door, "prepare_profile", lambda *a, **k: True),                 mock.patch.object(door.subprocess, "Popen", fake):
            door.run_cline_search("W", **kwargs)
        return captured[0]

    def test_the_default_command_matches_the_engine_flag_set(self):
        command = self._command()
        for forbidden in ("--json", "--thinking", "--system"):
            self.assertNotIn(forbidden, command, forbidden + " broke a live run today")
        for required in ("--data-dir", "--provider", "--model", "--key", "--retries", "-c", "-y"):
            self.assertIn(required, command)

    def test_the_prompt_is_the_last_argument(self):
        self.assertTrue(self._command()[-1].startswith(door.SEARCH_PROMPT[:20]))

    def test_the_child_gets_the_same_provider_file_as_the_agent(self):
        seen = {}

        def fake(process_command, **kwargs):
            seen.update(kwargs.get("env") or {})
            return FakeProcess([])

        with mock.patch.object(door, "prepare_profile", lambda *a, **k: True),                 mock.patch.object(door.subprocess, "Popen", fake):
            door.run_cline_search("W")
        self.assertTrue(seen["CLINE_PROVIDER_SETTINGS_PATH"].endswith("providers.json"))


    def test_the_prompt_names_the_shell_so_commands_do_not_fail(self):
        """Measured: bash syntax in PowerShell killed every tool call in one run."""
        self.assertIn("PowerShell", door.SEARCH_PROMPT)
        self.assertIn('no "&&"', door.SEARCH_PROMPT)


class ScoutWorktree(unittest.TestCase):
    """Measured: a bare empty directory made the agent hunt for a repo and never search."""

    def test_the_workspace_carries_a_task_file_naming_the_shell_and_the_output(self):
        with tempfile.TemporaryDirectory() as root:
            path = door.scaffold_workspace(root)
            with open(os.path.join(path, "TASK.md"), encoding="utf-8") as handle:
                task = handle.read()
            self.assertIn("gh search issues", task)
            self.assertIn("PowerShell", task)
            self.assertIn("shortlist.jsonl", task)
            self.assertTrue(os.path.isdir(os.path.join(path, ".git")), "a worktree, like the engine gives")

    def test_the_first_round_can_be_given_the_worktree_prompt(self):
        prompts = []

        def run(workdir, prompt=None, **kwargs):
            prompts.append(prompt)
            return {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True}

        door.iterate("W", rounds=1, run=run, verify=offline_verify,
                     first_prompt=door.WORKTREE_PROMPT)
        self.assertEqual(prompts[0], door.WORKTREE_PROMPT)

    def test_the_prompt_points_at_the_task_file(self):
        self.assertIn("TASK.md", door.WORKTREE_PROMPT)



class AmountGuard(unittest.TestCase):
    """Measured: a bounty heading with no figure passed the literal-quote gate."""

    def test_a_heading_without_a_figure_is_refused(self):
        self.assertFalse(door.quote_states_an_amount("### Bounty:  USDC (Escrow Locked)"))

    def test_real_amounts_are_accepted(self):
        for quote in ("$250 bounty available for a verified fix",
                      "BOUNTY - $50 USD", "### Bounty: 1,250 USDC (Escrow Locked)",
                      "Budget: 900 USD", "reward of 3 ETH"):
            self.assertTrue(door.quote_states_an_amount(quote), quote)
