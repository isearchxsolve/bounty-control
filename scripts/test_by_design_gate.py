"""The declared-by-design gate, pinned at both edges.

Measured need (2026-10-27): Expensify/App#105153 was dispatched, a full Cline session ran,
and the verified result was ``action=blocked`` -- "documented by the repository's own
maintainer analysis as expected/by-design" (comment id 6447058391). Re-admitting the same
issue every discovery cycle spends a delivery run to relearn a written verdict.

Two edges matter, and the second is the dangerous one:

* A declaration only counts from a party that speaks for the repository. ``trusted()``
  refuses the issuing automation account (``MelvinBot``, author_association CONTRIBUTOR), so
  the programme's documented automation identities are honoured -- and only for that
  repository.
* ``Expected Behaviour`` is the heading every bug report carries, and it states the
  *opposite* of this verdict. It is never a marker. A gate that reads it rejects the entire
  funded backlog, which would look like progress while producing nothing.
"""
import unittest

from bounty_admission import declared_by_design, admit as _admit

# The fixtures carry Expensify's real [$250] title. The admission floor moved from 80 to
# 2000 on 2026-10-29, which is a separate policy knob from the by-design gate; pinning it
# keeps this suite measuring whether a declaration was read and by whom, instead of
# failing every assertion on an unrelated floor.
FIXTURE_FLOOR = 80


def admit(context, quote=None, floor=FIXTURE_FLOOR):
    """Admission under the floor these fixtures were authored against."""
    return _admit(context, quote=quote, floor=floor)

HARD_TITLE = "[$250] Fix race condition in the report composer"
HARD_BODY = ("The composer sends a duplicate request when two tabs submit at once. "
             "See src/pages/Report/ReportComposer.tsx and the useSubmit hook.")

# The real declaring sentence, read live from
# repos/Expensify/App/issues/105153/comments (id 6447058391, 2026-10-27T16:09:17Z).
DECLARATION = ("**Root Cause:** This works as designed. It is not a bug. Turning on "
               "\"Simulate failing network requests\" does not send a new search request.")


def repository(full_name="Expensify/App", owner="Expensify"):
    return {"owner": {"login": owner}, "full_name": full_name,
            "archived": False, "disabled": False}


def issue(title=HARD_TITLE, body=HARD_BODY, labels=(), url="https://github.com/Expensify/App/issues/1"):
    return {"title": title, "body": body, "state": "open", "html_url": url,
            "labels": [{"name": name} for name in labels]}


def attestation():
    return {"user": {"login": "melvin-bot[bot]"}, "author_association": "NONE",
            "html_url": "https://github.com/Expensify/App/issues/1#issuecomment-1",
            "body": "Job added to Upwork: https://www.upwork.com/jobs/~022108002387844305757",
            "created_at": "2026-10-27T00:00:00Z"}


def comment(body, login="MelvinBot", association="CONTRIBUTOR", number=2):
    return {"user": {"login": login}, "author_association": association, "body": body,
            "html_url": f"https://github.com/Expensify/App/issues/1#issuecomment-{number}",
            "created_at": "2026-10-27T16:09:17Z"}


def context(comments=(), labels=(), repo="Expensify/App", owner="Expensify"):
    return {"repo": repo, "issue_number": 1, "repository": repository(repo, owner),
            "issue": issue(labels=labels), "comments": [attestation(), *comments],
            "complete_comments": True, "fetched_at": "unit fixture"}


class DeclarationIsReadTests(unittest.TestCase):
    def test_documented_automation_declaration_is_read(self):
        verdict = declared_by_design(context([comment(DECLARATION)]))
        self.assertEqual(verdict["verdict"], "BY_DESIGN")
        self.assertEqual(verdict["authority"], "MelvinBot")
        self.assertIn("works as designed", verdict["quote"])
        self.assertTrue(verdict["source_url"].endswith("#issuecomment-2"))

    def test_admission_refuses_the_declared_behaviour(self):
        proof, reason = admit(context([comment(DECLARATION)]))
        self.assertIsNone(proof)
        self.assertEqual(reason, "REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN")

    def test_maintainer_association_declaration_is_read(self):
        verdict = declared_by_design(context(
            [comment("Closing this: the banner behaviour is by design.", login="maintainer",
                     association="MEMBER", number=3)]))
        self.assertEqual(verdict["authority"], "maintainer")

    def test_repository_owner_declaration_is_read(self):
        verdict = declared_by_design(context(
            [comment("Won't fix - no code change is warranted here.", login="Expensify",
                     association="NONE", number=4)]))
        self.assertIsNotNone(verdict)

    def test_quote_is_the_declaring_line_not_the_whole_comment(self):
        long_tail = "\n".join("line %d of unrelated analysis" % index for index in range(60))
        verdict = declared_by_design(context([comment(DECLARATION + "\n" + long_tail)]))
        self.assertLess(len(verdict["quote"]), 260)
        self.assertNotIn("line 0 of unrelated analysis", verdict["quote"])

    def test_declaration_returns_the_reason_helper_only_on_declaration(self):
        self.assertEqual(admit(context([comment(DECLARATION)]))[1],
                         "REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN")
        self.assertEqual(admit(context())[1], "")


class AuthorityIsRequiredTests(unittest.TestCase):
    def test_untrusted_stranger_agreement_cannot_establish_it(self):
        """The measured payload had a stranger (author_association NONE) merely agreeing."""
        proof, reason = admit(context([
            comment("Agreed, this is not a bug - works as designed.", login="camesenin",
                    association="NONE", number=5)]))
        self.assertIsNotNone(proof)
        self.assertEqual(reason, "")

    def test_automation_login_is_scoped_to_its_own_repository(self):
        """The same login on an unrelated repository establishes nothing."""
        verdict = declared_by_design(context(
            [comment(DECLARATION)], repo="Other/Project", owner="Other"))
        self.assertIsNone(verdict)

    def test_a_foreign_bot_is_not_an_authority(self):
        verdict = declared_by_design(context([
            comment(DECLARATION, login="helpful-bot[bot]", association="NONE", number=6)]))
        self.assertIsNone(verdict)


class FalsePositiveTests(unittest.TestCase):
    """The edge that would silently empty the funded backlog."""

    def test_expected_behaviour_heading_is_never_a_marker(self):
        # Every bug report carries this heading and it states the opposite of this verdict.
        # Written by an authority on purpose: authority alone must not convert a routine
        # report into a declaration, or the gate empties the funded backlog.
        report = ("Steps: open Settings, toggle the network simulator.\n\n"
                  "Expected Behaviour\nThe refresh banner should reappear.\n\n"
                  "Actual Behaviour\nIt does not.")
        proof, reason = admit(context())
        self.assertIsNotNone(proof, reason)
        self.assertIsNone(declared_by_design(context([comment(report)])))

    def test_ordinary_analysis_that_mentions_design_is_not_a_declaration(self):
        analysis = ("The composer design routes both tabs through useSubmit, so the "
                    "second request races the first. Expected Behaviour is one request.")
        verdict = declared_by_design(context([
            comment(analysis, login="maintainer", association="MEMBER", number=7)]))
        self.assertIsNone(verdict)

    def test_maintainer_naming_the_intended_behaviour_is_not_a_declaration(self):
        verdict = declared_by_design(context([
            comment("The intended behaviour is that the banner refreshes after a failed "
                    "request; it is not doing that.", login="maintainer",
                    association="MEMBER", number=8)]))
        self.assertIsNone(verdict)

    def test_a_normal_funded_report_is_admitted_untouched(self):
        proof, reason = admit(context())
        self.assertIsNotNone(proof, reason)
        self.assertEqual(proof["funding"]["amount"], "250")
        self.assertEqual(proof["funding"]["payer"], "melvin-bot[bot]")


class WithdrawalTests(unittest.TestCase):
    def test_later_authoritative_bug_statement_clears_the_verdict(self):
        proof, reason = admit(context([
            comment(DECLARATION, number=9),
            comment("This is a real bug after all - reopening.", login="maintainer",
                    association="MEMBER", number=10)]))
        self.assertIsNotNone(proof, reason)

    def test_explicit_withdrawal_of_the_by_design_call_clears_it(self):
        verdict = declared_by_design(context([
            comment(DECLARATION, number=11),
            comment("Correction: this is not by design.", login="MelvinBot", number=12)]))
        self.assertIsNone(verdict)

    def test_a_later_declaration_overrides_an_earlier_bug_statement(self):
        verdict = declared_by_design(context([
            comment("This is a real bug.", login="maintainer", association="MEMBER", number=13),
            comment(DECLARATION, number=14)]))
        self.assertIsNotNone(verdict)


class LabelTests(unittest.TestCase):
    def test_a_by_design_label_rejects_when_no_comment_settles_it(self):
        verdict = declared_by_design(context(labels=["wontfix"]))
        self.assertEqual(verdict["author_association"], "LABEL")
        self.assertEqual(verdict["quote"], "labels: wontfix")
        self.assertIsNone(admit(context(labels=["wontfix"]))[0])

    def test_an_authoritative_bug_statement_beats_a_stale_label(self):
        proof, reason = admit(context([
            comment("This is a real bug, reopening.", login="maintainer",
                    association="MEMBER", number=15)], labels=["wontfix"]))
        self.assertIsNotNone(proof, reason)

    def test_unrelated_labels_do_not_reject(self):
        proof, reason = admit(context(labels=["bug", "External", "Internal"]))
        self.assertIsNotNone(proof, reason)


class PrecisionOnUnseenTrafficTests(unittest.TestCase):
    """Rules added after auditing the first two refusals the live pipeline made on its own.

    Both were imprecise: one keyed on a pointer to another issue, one read a status bullet on
    an aggregate board. A wrong by-design refusal silently deletes qualified influx, which is
    the thing this pipeline exists to produce, so each gets a rule and a case.
    """

    def test_a_pointer_to_another_issue_is_not_a_verdict_here(self):
        body = "Closed/wontfix #627 records the rejected custom launcher model history."
        self.assertIsNone(declared_by_design(context([comment(body, login="Ensrick",
                                                           association="OWNER")])))

    def test_a_declarative_wont_fix_still_counts(self):
        verdict = declared_by_design(context([comment("We won't fix this.", login="Ensrick",
                                                     association="OWNER")]))
        self.assertEqual(verdict["verdict"], "BY_DESIGN")

    def test_an_aggregate_board_is_not_a_bug_report(self):
        ctx = context([comment(DECLARATION)])
        ctx["issue"]["title"] = "Triage Board (auto-updated daily - pin me)"
        self.assertIsNone(declared_by_design(ctx))

    def test_a_board_body_alone_is_enough_to_excuse_it(self):
        ctx = context([comment(DECLARATION, login="limitlessprojects", association="OWNER")])
        ctx["issue"]["body"] = "Auto-updated status board. Do not comment here."
        self.assertIsNone(declared_by_design(ctx))

    def test_a_hyphenated_compound_is_not_the_marker(self):
        body = ("this issue remains an invitation to test real Seller-Free onboarding, "
                "not a bug-fix task or payable bounty.")
        self.assertIsNone(declared_by_design(context([comment(
            body, login="danieldirimini-myzubster", association="COLLABORATOR")])))

    def test_a_spaced_bug_fix_description_is_not_the_marker(self):
        body = ("That's basically it. It's also not high up on my personal priority list, as it is "
                "a entirely new feature (not a bug fix) and I am not using nor intend to use RCS "
                "myself.")
        self.assertIsNone(declared_by_design(context([comment(
            body, login="mar-v-in", association="MEMBER")])))

    def test_the_bare_verdict_still_matches_at_the_end_of_a_sentence(self):
        verdict = declared_by_design(context([comment("This is not a bug.")]))
        self.assertEqual(verdict["verdict"], "BY_DESIGN")

    def test_a_deferral_is_not_a_by_design_verdict(self):
        body = ("DEFERRED BATCH: the owner explicitly wants to finish checking all items before one "
                "coherent correction batch; no code change or new release is authorized yet.")
        self.assertIsNone(declared_by_design(context([comment(
            body, login="ach1992", association="OWNER")])))

    def test_no_code_change_needed_is_still_a_verdict(self):
        verdict = declared_by_design(context([comment(
            "No code change is needed here: the SDK already deduplicates the events.",
            login="maintainer", association="OWNER")]))
        self.assertEqual(verdict["verdict"], "BY_DESIGN")

    def test_a_provenance_clause_is_not_a_verdict_about_the_behaviour(self):
        body = ("6445766848 (rounds/005 provenance column - actually a bus #3 pointer, "
                "cross-thread by design; checker artifact, listed for completeness).")
        self.assertIsNone(declared_by_design(context([comment(
            body, login="MarkDude-design", association="OWNER")])))

    def test_the_quote_always_contains_the_words_that_fired_the_gate(self):
        filler = "status line " * 40
        body = filler + "This works as designed. It is not a bug."
        verdict = declared_by_design(context([comment(body)]))
        self.assertEqual(verdict["verdict"], "BY_DESIGN")
        self.assertIn("works as designed", verdict["quote"])
        self.assertLessEqual(len(verdict["quote"]), 243)


if __name__ == "__main__":
    unittest.main(verbosity=2)
