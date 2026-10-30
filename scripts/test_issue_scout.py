"""The scout's contract: the agent judges, code verifies, and failure refuses.

Fixtures are real shapes from the pipeline, including the two junk dispatches measured on
2026-10-30 and a reward the agent invented.
"""

import json
import unittest

import issue_scout as scout

BOUNTY = {
    "title": "Add retry to the HTTP client",
    "body": "Requests fail permanently on a transient 503. We pay a $250 bounty for a fix "
            "that adds bounded retries with tests.",
    "labels": [{"name": "bounty"}],
}
BOUNTY_REWARD_QUOTE = "We pay a $250 bounty for a fix that adds bounded retries with tests."

DAILY_DIGEST = {
    "title": "[daily information feed] 2026-09-03",
    "body": "Generated automatically each day. 12 new items were posted to the feed.",
    "labels": [{"name": "daily"}],
}
HACKATHON = {
    "title": "Hack Human incentives",
    "body": "# Hack Human (incentives) - win prizes\n\n## Prize Bounty\n"
            "#### Winners will split $7,500 paid out in ETH\n\n## Challenge Description\n"
            "Algorithms alone cannot do the job of preventing fraudulent activity.",
    "labels": [],
}


def reply(**overrides):
    base = {"is_code_task": True, "code_reason": "a fix is requested", "has_stated_reward": True,
            "reward_quote": BOUNTY_REWARD_QUOTE,
            "scope_quote": "Requests fail permanently on a transient 503.", "confidence": "high"}
    base.update(overrides)
    return json.dumps(base)


def asker(document):
    return lambda prompt, text: document


class AdmitsRealWork(unittest.TestCase):
    def test_a_funded_code_issue_is_admitted_with_its_quotes(self):
        result = scout.assess(BOUNTY, asker(reply()))
        self.assertTrue(result["admit"], result)
        self.assertEqual(result["reward_quote"], BOUNTY_REWARD_QUOTE)
        self.assertTrue(result["scope_verified"])

    def test_quote_check_survives_cosmetic_differences(self):
        text = "We pay a $250 bounty for a fix \u2014 with  tests."
        self.assertTrue(scout.quote_is_present("We pay a $250 bounty for a fix - with tests.", text))


class RefusesWithoutAFalsePositive(unittest.TestCase):
    """Every path here must refuse: a claim spent on junk is the failure being eliminated."""

    def test_a_daily_digest_is_refused(self):
        result = scout.assess(DAILY_DIGEST, asker(reply(
            is_code_task=False, has_stated_reward=False, code_reason="automated digest")))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "AGENT_NOT_A_CODE_TASK")

    def test_a_hackathon_announcement_is_refused(self):
        result = scout.assess(HACKATHON, asker(reply(
            is_code_task=False, has_stated_reward=True,
            reward_quote="Winners will split $7,500 paid out in ETH",
            code_reason="a contest, not a request to change code")))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "AGENT_NOT_A_CODE_TASK")

    def test_an_invented_reward_is_refused(self):
        """The agent claims money that is not in the text: no claim may be spent on it."""
        result = scout.assess(BOUNTY, asker(reply(
            reward_quote="We pay a $5,000 bounty for a complete rewrite of the client.")))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "REWARD_QUOTE_NOT_FOUND")

    def test_an_empty_reward_quote_is_refused(self):
        result = scout.assess(BOUNTY, asker(reply(reward_quote="")))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "REWARD_QUOTE_NOT_FOUND")

    def test_a_short_quote_cannot_prove_anything(self):
        result = scout.assess(BOUNTY, asker(reply(reward_quote="$250")))
        self.assertFalse(result["admit"], "a fragment is not evidence of a stated reward")

    def test_an_unavailable_agent_refuses_rather_than_admits(self):
        result = scout.assess(BOUNTY, asker(None))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "AGENT_UNAVAILABLE")

    def test_an_unparseable_reply_refuses(self):
        result = scout.assess(BOUNTY, asker("I think this one is probably fine to work on."))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "AGENT_UNPARSEABLE")

    def test_low_confidence_refuses(self):
        result = scout.assess(BOUNTY, asker(reply(confidence="low")))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "LOW_CONFIDENCE")

    def test_an_issue_without_text_is_refused(self):
        result = scout.assess({"title": "", "body": "", "labels": []}, asker(reply()))
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "EMPTY_ISSUE")


LINK_ONLY_BOUNTY = {
    "title": "\U0001f4b0 Bounty Seguro (Ver enlace): [Web3] bounty: [level:critical]",
    "body": "Bounty Seguro (Ver enlace): [Web3] bounty: [level:critical] Agentic Self-Healing",
    "labels": [],
}


class RefusesUnprovableRewards(unittest.TestCase):
    """Measured false positive: a title that says 'see link' was quoted as proof of payment."""

    def test_a_link_only_reward_is_refused(self):
        result = scout.assess(LINK_ONLY_BOUNTY, asker(reply(
            reward_quote="\U0001f4b0 Bounty Seguro (Ver enlace): [Web3] bounty: [level:critical]")))
        self.assertFalse(result["admit"], result)
        self.assertIn(result["reason"], ("REWARD_IS_LINK_ONLY", "REWARD_IS_TITLE_ONLY"))

    def test_a_reward_that_is_only_the_title_is_refused(self):
        issue = {"title": "Fix the parser [bounty]",
                 "body": "Fix the parser [bounty]\n\nIt fails on empty input.", "labels": []}
        result = scout.assess(issue, asker(reply(reward_quote="Fix the parser [bounty]")))
        self.assertFalse(result["admit"], result)
        self.assertEqual(result["reason"], "REWARD_IS_TITLE_ONLY")

    def test_a_real_sentence_is_still_admitted(self):
        self.assertTrue(scout.assess(BOUNTY, asker(reply()))["admit"])


class RepairRound(unittest.TestCase):
    """Measured false negatives: $900 and $3,000 bounties lost because the quote was paraphrased."""

    def test_a_paraphrased_quote_is_repaired_and_admitted(self):
        calls = []

        def ask(prompt, text):
            calls.append(prompt)
            if len(calls) == 1:
                return reply(reward_quote="We offer a $250 reward for adding retries.")
            return reply()

        result = scout.assess(BOUNTY, ask)
        self.assertTrue(result["admit"], result)
        self.assertEqual(len(calls), 2, "exactly one repair round")
        self.assertIn("does not appear in the issue", calls[1])

    def test_a_quote_that_stays_wrong_after_repair_is_refused(self):
        calls = []

        def ask(prompt, text):
            calls.append(prompt)
            return reply(reward_quote="We offer a $250 reward for adding retries.")

        result = scout.assess(BOUNTY, ask)
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "REWARD_QUOTE_NOT_FOUND")
        self.assertEqual(len(calls), 2, "no second repair")

    def test_an_agent_that_withdraws_the_reward_on_repair_is_believed(self):
        calls = []

        def ask(prompt, text):
            calls.append(prompt)
            if len(calls) == 1:
                return reply(reward_quote="invented")
            return reply(has_stated_reward=False, reward_quote="")

        result = scout.assess(BOUNTY, ask)
        self.assertFalse(result["admit"])
        self.assertEqual(result["reason"], "AGENT_WITHDREW_REWARD")

    def test_an_unavailable_repair_does_not_admit(self):
        calls = []

        def ask(prompt, text):
            calls.append(prompt)
            return reply(reward_quote="invented") if len(calls) == 1 else None

        self.assertFalse(scout.assess(BOUNTY, ask)["admit"])


class PromptHonesty(unittest.TestCase):
    def test_the_prompt_forbids_paraphrasing_quotes(self):
        self.assertIn("CHARACTER FOR CHARACTER", scout.PROMPT)
        self.assertIn("Do not paraphrase", scout.PROMPT)

    def test_the_prompt_names_the_junk_classes_measured_today(self):
        for phrase in ("hackathons", "daily digests", "marketing"):
            self.assertIn(phrase, scout.PROMPT)


class RouterAdaptation(unittest.TestCase):
    def test_a_failed_call_becomes_none_so_the_issue_is_refused(self):
        class DeadRouter:
            def chat_completion(self, payload, timeout=600, max_attempts=None):
                return False, {}, "nvidia/model", "Every NVIDIA key failed"
        self.assertIsNone(scout.nim_asker(DeadRouter())("p", "t"))

    def test_a_successful_call_returns_the_content(self):
        class LiveRouter:
            def chat_completion(self, payload, timeout=600, max_attempts=None):
                return True, {"choices": [{"message": {"content": "{\"ok\": true}"}}]}, "m", ""
        self.assertEqual(scout.nim_asker(LiveRouter())("p", "t"), "{\"ok\": true}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class MarkdownEscapes(unittest.TestCase):
    """Live receipt: issue body held ``Budget: \$900``; a faithful quote was refused."""

    def test_an_escaped_dollar_still_matches_a_plain_quote(self):
        body = "## Overview\n\nBudget: \$900\n\nImplement Uniswap V3 integration."
        self.assertTrue(scout.quote_is_present("Budget: $900", body))

    def test_another_escape_class_matches(self):
        self.assertTrue(scout.quote_is_present("Fix the picker_today bug", "Fix the picker\_today bug"))

    def test_a_genuinely_absent_quote_is_still_refused(self):
        self.assertFalse(scout.quote_is_present("Budget: $9,000", "Budget: \$900"))
