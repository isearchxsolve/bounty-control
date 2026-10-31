"""The entry door trusts Cline's search and nothing else.

Each test is a way an agent can be wrong: it invents an issue, quotes a title, reports a closed
ticket, or repeats a row. All must be refused with a named reason, because a claim spent on a
row that is not real is the false positive this door exists to stop.
"""

import json
import os
import re
import shutil
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
    if os.path.exists("W"):
        shutil.rmtree("W", ignore_errors=True)


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
        self.assertEqual(result["unpriced"], [])


class UnpricedIntentIsQuarantinedNotRefused(unittest.TestCase):
    """A real buyer who names no figure is a lead, not an error.

    Measured live: Rooner-Plugins/bank-value-changes#3 ("I'm willing to pay for this to be
    added") and boxbilling/boxbilling#889 ("[WILL PAY FOR CODE]") are genuine intent with no
    amount. Sending them back through FEEDBACK_PROMPT told the agent to drop them, and the
    prompt says so explicitly ("drop the row").
    """

    WILLING = {**ISSUE,"body": "I'm willing to pay for this to be added."}

    def test_intent_without_a_figure_is_unpriced_and_never_refused(self):
        result = door.verify_rows(
            [row(reward_quote="I'm willing to pay for this to be added.")],
            fetcher(self.WILLING))
        self.assertEqual(result["refused"], [], "a real buyer must not be refused")
        self.assertEqual(len(result["unpriced"]), 1)
        self.assertEqual(result["unpriced"][0]["reason"], "REWARD_QUOTE_HAS_NO_AMOUNT")
        self.assertEqual(result["unpriced"][0]["issue"], 7)

    def test_unpriced_rows_carry_their_url_and_quote_for_follow_up(self):
        result = door.verify_rows(
            [row(reward_quote="I'm willing to pay for this to be added.")],
            fetcher(self.WILLING))
        entry = result["unpriced"][0]
        self.assertEqual(entry["url"], "https://github.com/acme/http/issues/7")
        self.assertIn("willing to pay", entry["reward_quote"])

    def test_a_fabricated_quote_is_still_refused_not_quarantined(self):
        """The quarantine must not become a way for invented money to survive."""
        result = door.verify_rows(
            [row(reward_quote="We pay a $9000 bounty, guaranteed.")], fetcher())
        self.assertEqual(result["unpriced"], [])
        self.assertEqual(result["refused"][0]["reason"], "REWARD_QUOTE_NOT_IN_ISSUE")

    def test_unpriced_rows_survive_a_mixed_shortlist_without_blocking_it(self):
        documents = {7: ISSUE, 8: self.WILLING}
        result = door.verify_rows(
            [row(), row(issue=8, reward_quote="I'm willing to pay for this to be added.")],
            lambda repo, number: documents.get(number))
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["admitted"][0]["issue"], 7)
        self.assertEqual(result["refused"], [])
        self.assertEqual(len(result["unpriced"]), 1)


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
    def test_the_prompt_does_not_script_the_search(self):
        """Baba, 2026-10-30: full autonomy, the gates guard and report. A prompt that names the
        queries is a script, and a script cannot find what its author did not think of."""
        self.assertNotIn("gh search", door.SEARCH_PROMPT)
        self.assertNotIn("--label", door.SEARCH_PROMPT)
        self.assertIn("shortlist.jsonl", door.SEARCH_PROMPT)

    def test_the_junk_taxonomy_lives_in_the_gates_not_the_prompt(self):
        """The prompt used to list digests, hackathons and design-only asks. That list is a
        judgement, so it was removed: the gates refuse a row and the feedback says why."""
        for phrase in ("digests", "hackathons", "design-only"):
            self.assertNotIn(phrase, door.SEARCH_PROMPT)


CALIBRATION = ("Do not exclude a row to be safe: submit anything that plausibly meets "
               "these criteria, and the gates will verify it exactly and report the "
               "failures.")


class RecallOverPrecision(unittest.TestCase):
    """The agent owns recall; the gates own precision.

    Measured live: once the agent was given the domain and the exact gate list, it
    over-calibrated. It self-eliminated candidates to be safe and recall collapsed to a
    single row. The gates are exact and cheap; a row the agent never writes down is a lead
    nobody can recover. The brief therefore has to say so explicitly, in both the task file
    and the correction prompt, or the agent re-learns timidity every round.
    """

    def test_the_task_file_carries_the_calibration_sentence_verbatim(self):
        self.assertIn(CALIBRATION, door.TASK_FILE)

    def test_the_feedback_prompt_carries_it_too(self):
        """A correction round must not quietly teach the agent to submit less."""
        self.assertIn(CALIBRATION, door.FEEDBACK_PROMPT)

    def test_the_task_file_states_the_division_of_labour(self):
        self.assertIn("recall", door.TASK_FILE.lower())
        self.assertIn("gates", door.TASK_FILE.lower())

    def test_uncertainty_is_named_as_a_reason_to_submit(self):
        text = door.TASK_FILE.lower()
        self.assertIn("when you are unsure, submit it", text)

    def test_the_gate_list_is_still_present_so_precision_is_not_lost(self):
        """Recall must not be bought by hiding the gates from the agent."""
        for code, _meaning in door.GATE_CHECKS:
            self.assertIn(code, door.TASK_FILE)

    def test_a_code_task_refusal_stays_hard(self):
        """Recall is widened, not the deliverable: we only take verified code changes."""
        result = door.verify_rows([row(is_code_task=False)], fetcher())
        self.assertEqual(result["admitted"], [])
        self.assertEqual(result["unpriced"], [])
        self.assertEqual(result["refused"][0]["reason"], "AGENT_NOT_A_CODE_TASK")


class UnpricedLeadStream(unittest.TestCase):
    """The unpriced rows must survive the run as a file, not just a printed line."""

    def _workdir(self):
        workdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(workdir, ignore_errors=True))
        return workdir

    def test_leads_are_written_to_their_own_file(self):
        import json
        workdir = self._workdir()
        unpriced = [{"row": {}, "reason": "REWARD_QUOTE_HAS_NO_AMOUNT", "repo": "acme/http",
                     "issue": 3, "url": "https://github.com/acme/http/issues/3",
                     "reward_quote": "I'm willing to pay for this to be added."}]
        path = door.write_unpriced_leads(workdir, unpriced)
        self.assertTrue(path.endswith(door.UNPRICED_LEADS))
        written = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["issue"], 3)
        self.assertEqual(written[0]["repo"], "acme/http")

    def test_the_lead_file_is_separate_from_the_shortlist(self):
        self.assertNotEqual(door.UNPRICED_LEADS, "shortlist.jsonl")

    def test_repeated_rounds_do_not_duplicate_a_lead(self):
        import json
        workdir = self._workdir()
        entry = {"row": {}, "reason": "REWARD_QUOTE_HAS_NO_AMOUNT", "repo": "acme/http",
                 "issue": 3, "url": "u", "reward_quote": "willing to pay"}
        door.write_unpriced_leads(workdir, [entry])
        path = door.write_unpriced_leads(workdir, [entry])
        written = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        self.assertEqual(len(written), 1, "the stream must not inflate across rounds")

    def test_no_unpriced_rows_writes_nothing(self):
        workdir = self._workdir()
        self.assertEqual(door.write_unpriced_leads(workdir, []), "")
        self.assertFalse(os.path.exists(os.path.join(workdir, door.UNPRICED_LEADS)))


if __name__ == "__main__":
    unittest.main(verbosity=2)


def offline_verify(rows, limit=12):
    """Verify against a fixture issue, never the network: a unit test must not call GitHub."""
    return door.verify_rows(rows, fetch=fetcher(), limit=limit)


class FeedbackLoop(unittest.TestCase):
    """Cline is not judged once and dismissed: refusals come back to it as instructions."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.workdir, ignore_errors=True))

    def test_a_refusal_reason_reaches_the_agents_next_round(self):
        prompts = []
        rounds = [
            {"exit_code": 0, "rows": [row(reward_quote="paraphrased money")], "tail": "", "wrote_file": True},
            {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True},
        ]

        def run(workdir, prompt=None, **kwargs):
            prompts.append(prompt)
            return rounds[min(len(prompts), len(rounds)) - 1]

        result = door.iterate(self.workdir, rounds=3, run=run, verify=offline_verify)
        self.assertEqual(len(prompts), 3, "every configured round runs; refusals still reach the next")
        self.assertIn("REWARD_QUOTE_NOT_IN_ISSUE", prompts[1])
        self.assertIn("acme/http#7", prompts[1])
        self.assertEqual(len(result["admitted"]), 1)

    def test_a_clean_round_continues_searching_instead_of_ending_the_round(self):
        """Baba 2026-10-31: no quota, no early finish.

        Measured on run 41183429400 (first quota-free brief): the agent returned four rows,
        nothing was refused, and the second configured round never ran - the extra round was
        wired as a repair round only. Time left on the clock is time to search, so a clean round
        now continues the search. The old policy is deliberately retired here, not loosened:
        rounds stay bounded and a repeated row is never admitted twice.
        """
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            return {"exit_code": 0, "rows": [row()], "tail": "", "wrote_file": True}

        result = door.iterate(self.workdir, rounds=5, run=run, verify=offline_verify)
        self.assertEqual(len(calls), 5, "a clean round is a reason to search more, not to stop")
        self.assertIn("no quota", calls[1].lower())
        self.assertEqual(len(result["admitted"]), 1, "the same row is never admitted twice")

    def test_rounds_are_bounded_even_if_the_agent_never_fixes_anything(self):
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            return {"exit_code": 0, "rows": [row(reward_quote="still paraphrased")],
                    "tail": "", "wrote_file": True}

        result = door.iterate(self.workdir, rounds=3, run=run, verify=offline_verify)
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

        result = door.iterate(self.workdir, rounds=3, run=run, verify=verify)
        issues = sorted(r["issue"] for r in result["admitted"])
        self.assertEqual(issues, [7, 8], "no duplicate rows after correction")

    def test_a_round_that_rewrites_the_shortlist_cannot_erase_a_row_already_won(self):
        """Measured: round 2 admitted 1 of 9 because the agent rewrote the file from scratch.

        The agent is told to write shortlist.jsonl again each round, so every row won in
        round 1 disappeared before round 2 was verified. Feedback was resetting, not
        compounding. The loop now re-appends admitted rows before the next round runs.
        """
        import json

        workdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(workdir, ignore_errors=True))
        shortlist = os.path.join(workdir, "shortlist.jsonl")
        calls = []

        def run(workdir, prompt=None, **kwargs):
            calls.append(prompt)
            # The agent rewrites the file from scratch every round: round 2 keeps only #8.
            with open(shortlist, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(row(issue=8)) + "\n")
            return {"exit_code": 0, "rows": [row(issue=8)], "tail": "", "wrote_file": True}

        def verify(rows, limit=12):
            if len(calls) == 1:
                return {"admitted": [row()], "refused": [{"row": row(issue=8), "reason": "ISSUE_NOT_OPEN"}]}
            return {"admitted": [row(issue=8)], "refused": []}

        result = door.iterate(workdir, rounds=3, run=run, verify=verify)
        issues = sorted(r["issue"] for r in result["admitted"])
        self.assertEqual(issues, [7, 8], "round 1's row must survive round 2's rewrite")
        on_disk = [json.loads(line) for line in open(shortlist, encoding="utf-8") if line.strip()]
        self.assertIn(7, [r["issue"] for r in on_disk],
                      "the won row must still be in the file the next round reads")

    def test_the_merge_does_not_duplicate_a_row_the_agent_resubmits(self):
        import json

        workdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(workdir, ignore_errors=True))
        shortlist = os.path.join(workdir, "shortlist.jsonl")
        with open(shortlist, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(row()) + "\n")
        door._merge_shortlist(workdir, [row(), row(issue=9)])
        on_disk = [json.loads(line) for line in open(shortlist, encoding="utf-8") if line.strip()]
        self.assertEqual(sorted(r["issue"] for r in on_disk), [7, 9])


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

        with tempfile.TemporaryDirectory() as tmp_w:
            door.iterate(tmp_w, rounds=1, run=run, verify=offline_verify)
        self.assertTrue(prompts[0].startswith(door.FRESH_START))


class ProfileCarriesTheGateway(unittest.TestCase):
    """Measured: a profile without baseUrl sent the NVIDIA key straight to OpenAI.

    These tests fake the CLI: they check that auth is called with the gateway and that the
    readback refuses a profile whose base URL was not persisted. No network, no real auth.
    """

    def _fake_auth_that_persists(self, data_dir, base_url, model=door.DEFAULT_ENTRY_MODEL,
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

    def test_the_brief_says_the_machine_has_nothing_to_explore(self):
        self.assertIn("no source code", door.TASK_FILE)
        self.assertNotIn("STEP 1", door.TASK_FILE)


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

        with tempfile.TemporaryDirectory() as tmp_w:
            with mock.patch.object(door, "prepare_profile", lambda *a, **k: True),                     mock.patch.object(door.subprocess, "Popen", fake):
                door.run_cline_search(tmp_w)
        self.assertTrue(seen["CLINE_PROVIDER_SETTINGS_PATH"].endswith("providers.json"))


    def test_the_shell_is_named_in_the_brief_as_an_environment_fact(self):
        """PowerShell is a fact about the machine, not a judgement about the work."""
        self.assertIn("PowerShell", door.TASK_FILE)


class ScoutWorktree(unittest.TestCase):
    """The brief states facts and the output contract. Judgement is the agent's, and the gates
    refuse and explain - they are the guardrail, not a recipe in the prompt."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="door-scaffold-")
        self.workdir = door.scaffold_workspace(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_brief_is_written_into_the_worktree(self):
        task = os.path.join(self.workdir, "TASK.md")
        self.assertTrue(os.path.isfile(task))

    def test_the_brief_names_the_output_contract(self):
        text = open(os.path.join(self.workdir, "TASK.md"), encoding="utf-8").read()
        for field in ("shortlist.jsonl", "reward_quote", "reward_usd", "repo", "issue"):
            self.assertIn(field, text)

    def test_the_brief_states_the_workspace_has_no_code(self):
        text = open(os.path.join(self.workdir, "TASK.md"), encoding="utf-8").read()
        self.assertIn("no source code", text)

    def test_the_brief_carries_the_domain(self):
        """Baba: how will the agent know the gates unless it is told the domain and the
        constraints. Autonomy is about the method, never about the acceptance criteria."""
        text = open(os.path.join(self.workdir, "TASK.md"), encoding="utf-8").read()
        self.assertIn("The domain", text)
        self.assertIn("engineering", text)
        self.assertIn("Do not exclude a row to be safe", text)

    def test_every_gate_that_can_fire_is_named_in_the_brief(self):
        """The brief is rendered from GATE_CHECKS/DOWNSTREAM_CHECKS, so a new refusal cannot be
        added to the gate without appearing in front of the agent."""
        text = open(os.path.join(self.workdir, "TASK.md"), encoding="utf-8").read()
        for code, _ in door.GATE_CHECKS + door.DOWNSTREAM_CHECKS:
            self.assertIn(code, text, code)

    def test_every_reason_the_gate_emits_is_in_the_table(self):
        """Anti-drift: scrape the reason strings out of verify_rows and require each to be
        documented. Catches a reason added to the code but not to the brief."""
        import inspect
        source = inspect.getsource(door.verify_rows)
        emitted = set(re.findall(r'"reason": "([A-Z_]+)"', source))
        documented = {code for code, _ in door.GATE_CHECKS}
        self.assertTrue(emitted, "no reason strings found - the scrape is wrong")
        self.assertEqual(emitted - documented, set())

    def test_the_brief_prescribes_no_search_recipe(self):
        """Measured handcuffs, removed on Baba's order: a numbered first step, a list of search
        commands and a taxonomy of what counts as money. Those are judgements."""
        text = open(os.path.join(self.workdir, "TASK.md"), encoding="utf-8").read()
        self.assertNotIn("STEP 1", text)
        self.assertNotIn("--label bounty", text)
        self.assertNotIn("gh search issues", text)
        self.assertNotIn("Skip and do not report", text)

    def test_the_worktree_is_a_git_repository(self):
        self.assertTrue(os.path.isdir(os.path.join(self.workdir, ".git")))

    def test_the_prompt_points_at_the_brief_and_nothing_else(self):
        self.assertIn("TASK.md", door.WORKTREE_PROMPT)
        self.assertIn("shortlist.jsonl", door.WORKTREE_PROMPT)
        self.assertLess(len(door.SEARCH_PROMPT), 700, "a long prompt is a script in disguise")

    def test_the_feedback_reports_checks_not_a_repair_script(self):
        self.assertIn("{refusals}", door.FEEDBACK_PROMPT)
        self.assertIn("REWARD_QUOTE_HAS_NO_AMOUNT", door.FEEDBACK_PROMPT)
        self.assertNotIn("Do this now:", door.FEEDBACK_PROMPT)


class AmountGuard(unittest.TestCase):
    """Measured: a bounty heading with no figure passed the literal-quote gate."""

    def test_a_heading_without_a_figure_is_refused(self):
        self.assertFalse(door.quote_states_an_amount("### Bounty:  USDC (Escrow Locked)"))

    def test_real_amounts_are_accepted(self):
        for quote in ("$250 bounty available for a verified fix",
                      "BOUNTY - $50 USD", "### Bounty: 1,250 USDC (Escrow Locked)",
                      "Budget: 900 USD", "reward of 3 ETH",
                      # measured live: this real bounty was refused by the first version
                      "[BOUNTY] RCS Support [14999$]", "-> /bounty $700"):
            self.assertTrue(door.quote_states_an_amount(quote), quote)


class QuotaIsNotAVerdict(unittest.TestCase):
    """Measured: a 403 rate limit was stamped ISSUE_NOT_FOUND on a live issue."""

    def _run(self, completed):
        with mock.patch.object(door.subprocess, "run", return_value=completed):
            return door.fetch_issue("a/b", 1)

    def test_a_404_is_still_a_missing_issue(self):
        done = mock.Mock(returncode=1, stderr="gh: Not Found (HTTP 404)", stdout="")
        self.assertIsNone(self._run(done))

    def test_a_rate_limit_raises_instead_of_claiming_missing(self):
        done = mock.Mock(returncode=1, stdout="API rate limit exceeded for user ID 1",
                         stderr="")
        with self.assertRaises(door.IssueUnreadable):
            self._run(done)

    def test_an_unreadable_row_is_refused_under_its_own_reason(self):
        rows = [{"repo": "a/b", "issue": 1, "reward_quote": "$50"}]
        with mock.patch.object(door, "fetch_issue", side_effect=door.IssueUnreadable("403")):  # noqa: E501
            result = door.verify_rows(rows)
        self.assertEqual(result["admitted"], [])
        self.assertEqual(result["refused"][0]["reason"], "ISSUE_UNREADABLE")

    def test_the_reason_is_documented_in_the_brief(self):
        self.assertIn("ISSUE_UNREADABLE", door.TASK_FILE)


def fetcher_verify(rows, limit=12):
    """verify_rows bound to the fixed ISSUE, so iterate() can be driven without a network."""
    return door.verify_rows(rows, fetcher(), limit=limit)


class RowsSurviveTheBudget(unittest.TestCase):
    """Baba 2026-10-31: do not wait for the agent to finish, ingest what it writes on the go.

    Measured on run 41178595784: the agent had verified candidates inside its narration and the
    round was killed at the wall-clock budget, so `rows=0` and a whole search was thrown away.
    A shortlist read only after `process.wait()` turns every timeout into a total loss.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="door-stream-")
        self.path = os.path.join(self.workdir, "shortlist.jsonl")

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_a_half_written_line_is_not_parsed_and_waits_for_its_newline(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write('{"repo": "acme/http", "issue": 7}\n{"repo": "acme/http", "iss')
        rows, offset = door.new_rows(self.path)
        self.assertEqual(len(rows), 1, "the complete line must be read, the partial one held")
        self.assertEqual(rows[0]["issue"], 7)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write('ue": 8}\n')
        rows, offset = door.new_rows(self.path, offset)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["issue"], 8, "the completed line is read exactly once")

    def test_nothing_is_read_twice_when_the_agent_keeps_appending(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write('{"repo": "a/one", "issue": 1}\n')
        first, offset = door.new_rows(self.path)
        second, offset = door.new_rows(self.path, offset)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [], "an unchanged file must yield nothing new")

    def test_a_row_banked_mid_round_is_kept_when_the_agent_is_killed(self):
        """The exact failure: the run ends -1 with rows=[] because the file was never re-read."""
        written = {"repo": "acme/http", "issue": 7, "reward_usd": 250,
                   "reward_quote": ISSUE["body"], "is_code_task": True}

        def killed_run(workdir, prompt=None, on_row=None, **kwargs):
            with open(os.path.join(workdir, "shortlist.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(written) + "\n")
            if on_row is not None:
                on_row(written)          # what the tailer does while the agent is still alive
            return {"exit_code": -1, "rows": [], "timed_out": True}

        result = door.iterate(self.workdir, rounds=1, run=killed_run, verify=fetcher_verify)
        self.assertEqual([row["issue"] for row in result["admitted"]], [7])
        self.assertEqual(result["history"][0]["agent_exit"], -1)
        stream = os.path.join(self.workdir, "admitted-stream.jsonl")
        self.assertTrue(os.path.exists(stream), "a banked row must land in the ingest file")
        with open(stream, encoding="utf-8") as handle:
            self.assertEqual(json.loads(handle.readline())["issue"], 7)


class TheSearcherIsSovereign(unittest.TestCase):
    """Baba 2026-10-31: the entry door agent is the sovereign sole searcher.

    Measured failure: the brief called it an "auditor", named the gates as "acceptance criteria;
    aim every row at them", and ordered "Target 2 to 4 verified candidates ... finish immediately".
    The agent obeyed the quota exactly - it wrote 2 then 4 rows, stopped, and never reached the
    1,999 funding issues GitHub was publishing that week. Scarcity was the brief's, not the
    world's, so the brief must not be able to say it again.
    """

    def test_the_brief_never_caps_the_search(self):
        text = door.TASK_FILE
        for quota in ("Target 2 to 4", "finish immediately", "Then finish"):
            self.assertNotIn(quota, text, "a quota turns the searcher into a sampler")
        self.assertIn("no quota", text.lower())

    def test_the_searcher_is_not_titled_an_auditor(self):
        self.assertNotIn("Auditor", door.TASK_FILE)
        self.assertIn("only pair of hands", door.TASK_FILE)

    def test_the_brief_says_the_world_is_real_and_nothing_is_planted(self):
        text = door.TASK_FILE.lower()
        self.assertIn("nothing is planted", text)
        self.assertIn("no grader", text)

    def test_the_gates_are_checks_not_acceptance_criteria_to_aim_at(self):
        text = door.TASK_FILE
        self.assertNotIn("acceptance criteria; aim", text)
        self.assertIn("how a claim is verified, never the goal", text)

    def test_a_live_unpriced_row_is_not_counted_twice(self):
        """Measured on run 41181814578: 4 rows reported as unpriced: 8, because the merge only
        skipped rows the stream had ADMITTED, so every live-unpriced row was verified again."""
        workdir = tempfile.mkdtemp(prefix="door-dedupe-")
        self.addCleanup(shutil.rmtree, workdir, True)
        bare = {"repo": "acme/http", "issue": 9, "is_code_task": True,
                "reward_quote": "Requests fail permanently on a transient 503.",
                "reward_usd": None, "scope_quote": "Requests fail on a transient 503.",
                "why_now": "owner report"}

        def run(workdir, prompt=None, on_row=None, **kwargs):
            if on_row is not None:
                on_row(bare)
            return {"exit_code": 0, "rows": [bare], "timed_out": False}

        result = door.iterate(workdir, rounds=1, run=run, verify=fetcher_verify)
        self.assertEqual(len(result["unpriced"]), 1, "one row, one receipt")
        self.assertEqual(result["history"][0]["unpriced"], 1)

    def test_the_brief_states_the_real_budget_it_is_given(self):
        """Run 41182050385 spent the whole 800s and wrote nothing: the agent was never told its
        own budget, so it had no way to know it was out of time. The number is a fact about the
        harness, so the brief must carry the real one instead of a vague 'fixed budget'."""
        with mock.patch.dict(os.environ, {"BOUNTY_AGENT_TIMEOUT": "800"}):
            text = door.render_task_file()
        self.assertIn("800 seconds of wall clock", text)
        self.assertNotIn("{clock}", text)
        self.assertIn("an empty file has delivered nothing", text)

    def test_a_big_harvest_is_not_silently_truncated(self):
        """The door's own default verified only the first 12 rows per round. A sovereign
        searcher that brought back 20 verified rows lost 8 of them without a word - the same
        upside-down bucket as the quota, one layer down. limit=0 now means no ceiling; an
        explicit positive limit still truncates (the row-limit test above pins that)."""
        rows = [row(issue=n) for n in range(1, 21)]
        self.assertEqual(len(door.verify_rows(rows, fetcher(), limit=0)["admitted"]), 20)
        self.assertEqual(len(door.verify_rows(rows, fetcher(), limit=5)["admitted"]), 5)

    def test_the_brief_gives_direction_in_first_principles_language(self):
        """Baba 2026-10-31, after watching the live stream: "it lacks direction" - and then, on
        how to say it: "you cannot express the direction using technical terms. You have to use
        first-principle language - world, garden, best fruits, pluck it, hands. Tell it to pluck
        the best fruits in the garden. World is not in drought, world is full of good fruits."

        Measured over one watched round: the winning idea appeared in its thinking at 70.6s and
        was first executed at 242.8s, and no row was written in 300s. Knowledge was never the
        deficit - it named Algora, Opire, Polar and BountyHub unprompted. What it lacked was a
        plain reason to act, so the brief is now written in the plainest words available: a
        garden, ripe fruit, hands, a basket. No engineering vocabulary, and no method dictated.
        """
        text = door.TASK_FILE
        for plain in ("garden", "ripe fruit", "pair of hands", "pluck", "basket"):
            self.assertIn(plain, text, "the direction must be said in first-principle words")
        self.assertIn("not in drought", text)
        for jargon in ("deliberation", "objective function", "priority queue", "heuristic"):
            self.assertNotIn(jargon, text.lower())
        self.assertNotIn("First run", text)
        self.assertNotIn("Step 1", text)

    def test_the_brief_tells_it_a_failed_row_costs_nothing(self):
        """Watched live, twice: 0 attempts to write a row in 300s each. It opened a genuinely
        funded issue (microg/GmsCore#2843, bountyhub-bot, $2,340) at 54s and never banked it -
        it carried fruit from tree to tree and put nothing in the basket. The asymmetry has to be
        said in plain words, because that is the only reason it is holding back."""
        text = door.TASK_FILE
        self.assertIn("An empty basket is the only thing that costs the round", text)
        self.assertIn("Do not walk from tree to tree carrying nothing", text)

    def test_the_brief_carries_no_mojibake(self):
        """A broken em dash reached the agent as a replacement char; keep the file ASCII."""
        bad = sorted({c for c in door.TASK_FILE if ord(c) > 127})
        self.assertEqual(bad, [], "the task file must be pure ASCII")
