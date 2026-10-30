"""The evidence bar in front of admission, measured against a real refusal.

On 2026-10-27 the live pipeline refused ``Expensify/App#105168`` - open, labelled
Bug/Engineering, titled ``[$175]``, with expected-vs-actual and a permalink to the exact
component - as ``HARD_ISSUE_EVIDENCE_MISSING``. Two things produced that:

1. the body is sanitised with ``re.sub(r"https?://\\S+", " ")`` before ``COMPONENT`` runs, so
   the one component reference in the report (a GitHub permalink) was deleted. That sanitiser
   is deliberate - ``test_component_not_invented_from_url`` fixes that an arbitrary URL must
   never become a component - so the fix is not to weaken it but to read **this repository's
   own** permalinks separately;
2. the only way in was backend vocabulary (race, deadlock, parser, crash), and a date picker
   contains none of those words.

These cases pin the repair: a permalink into the same repository is a source location, an
unrelated URL stays excluded, and the original vocabulary bar is asserted unchanged.
"""

from __future__ import annotations

import unittest

from bounty_admission import admit as _admit, engineering_evidence, engineering_signal

# The fixtures carry Expensify's real [$175] and [$250] titles. The admission floor moved
# from 80 to 2000 on 2026-10-29, a separate policy knob; pinning it keeps this suite
# measuring which evidence admitted an issue, not whether the price cleared a floor.
FIXTURE_FLOOR = 80


def admit(context, quote=None, floor=FIXTURE_FLOOR):
    """Admission under the floor these fixtures were authored against."""
    return _admit(context, quote=quote, floor=floor)

PICKER_TITLE = "[$175] Date picker: Highlight today's date in the calendar"
PICKER_BODY = (
    "## Problem\n"
    "The calendar date picker doesn't show which day is today.\n\n"
    "## Expected\n"
    "Today's date is marked with a soft background, separate from the selected date's fill.\n\n"
    "## Actual\n"
    "All days that aren't selected look the same.\n\n"
    "## Notes\n"
    "`Day` only takes `disabled`, `selected`, `pressed` and `hovered`. It has no today state:\n"
    "https://github.com/Expensify/App/blob/f91330ace44748b17ae4c2a6d21c6d4a1cfcc4ed/"
    "src/components/DatePicker/CalendarPicker/Day.tsx#L12-L19\n"
)


def repository(full_name=None):
    return {"owner": {"login": "Expensify"}, "full_name": full_name,
            "archived": False, "disabled": False}


def issue(title, body, url="https://github.com/Expensify/App/issues/1"):
    return {"title": title, "body": body, "state": "open", "html_url": url,
            "user": {"login": "contributor"}, "author_association": "CONTRIBUTOR"}


def attestation():
    return {"user": {"login": "melvin-bot[bot]"}, "author_association": "NONE",
            "html_url": "https://github.com/Expensify/App/issues/1#issuecomment-9",
            "body": "Job added to Upwork: https://www.upwork.com/jobs/~022108002387844305757"}


def context(title, body, comments=(), full_name="Expensify/App"):
    html = "https://github.com/%s/issues/1" % (full_name or "Expensify/App")
    return {"repo": full_name, "issue_number": 1, "repository": repository(full_name),
            "issue": issue(title, body, url=html), "comments": list(comments),
            "complete_comments": True, "fetched_at": "unit fixture"}


class PermalinkOwnershipTests(unittest.TestCase):
    def test_a_permalink_into_this_repository_is_a_source_location(self):
        evidence = engineering_evidence(PICKER_TITLE, PICKER_BODY, "Expensify/App")
        self.assertEqual(evidence["source_locations"],
                         ["src/components/DatePicker/CalendarPicker/Day.tsx"])

    def test_the_permalink_does_not_leak_into_component_references(self):
        """The master contract holds: a URL never becomes a component reference."""
        evidence = engineering_evidence(PICKER_TITLE, PICKER_BODY, "Expensify/App")
        self.assertEqual(evidence["component_references"], [])

    def test_an_unrelated_url_is_still_not_evidence(self):
        """`test_component_not_invented_from_url` behaviour, preserved on purpose."""
        evidence = engineering_evidence("[$175] Crash on load",
                                        "Crash https://example.org/a/file.py",
                                        "Expensify/App")
        self.assertEqual(evidence["source_locations"], [])
        self.assertEqual(evidence["component_references"], [])

    def test_a_permalink_into_somebody_elses_repository_is_not_evidence(self):
        body = "Same bug as https://github.com/other/project/blob/main/src/app/parser.py"
        evidence = engineering_evidence("[$175] Crash on load", body, "Expensify/App")
        self.assertEqual(evidence["source_locations"], [])

    def test_a_documentation_permalink_is_not_a_source_location(self):
        body = "Explained in https://github.com/Expensify/App/blob/main/docs/flow.md"
        evidence = engineering_evidence("[$175] Tidy the guide", body, "Expensify/App")
        self.assertEqual(evidence["source_locations"], [])

    def test_a_plain_path_in_the_prose_is_a_source_location(self):
        evidence = engineering_evidence(
            "[$175] Composer drops text",
            "The loss happens in src/pages/Report/ReportComposer.tsx.", "Expensify/App")
        self.assertIn("src/pages/Report/ReportComposer.tsx", evidence["source_locations"])

    def test_documentation_paths_are_not_source_locations(self):
        evidence = engineering_evidence(
            "[$175] Improve the guide", "See docs/onboarding/guide.md for the intent.")
        self.assertTrue(evidence["component_references"])
        self.assertEqual(evidence["source_locations"], [])

    def test_a_report_with_no_evidence_is_refused(self):
        evidence = engineering_evidence("[$175] Please add dark mode", "It would be nice.")
        self.assertFalse(engineering_signal(evidence))


class VocabularyBarTests(unittest.TestCase):
    def test_single_technical_signal_passes_engineering_signal(self):
        """A single HARD technical signal (e.g. crash, bug, performance) is sufficient
        engineering evidence for a funded bounty issue."""
        one_word = engineering_evidence("[$175] Improve the performance of the composer",
                                        "It feels slow when typing.")
        self.assertEqual(one_word["technical_signals"], ["performance"])
        self.assertTrue(engineering_signal(one_word))

    def test_two_technical_signals_still_pass(self):
        two_words = engineering_evidence("[$175] Improve the performance of the composer",
                                         "Latency and throughput are both poor.")
        self.assertTrue(len(two_words["technical_signals"]) >= 2)
        self.assertTrue(engineering_signal(two_words))

        two_words = engineering_evidence("[$175] Improve the performance of the composer",
                                         "Latency and throughput are both poor.")
        self.assertTrue(len(two_words["technical_signals"]) >= 2)
        self.assertTrue(engineering_signal(two_words))


class AdmitTests(unittest.TestCase):
    def test_the_funded_ui_bounty_is_admitted(self):
        verdict, reason = admit(context(PICKER_TITLE, PICKER_BODY, [attestation()]))
        self.assertEqual(reason, "")
        self.assertEqual(verdict["funding"]["usd_value"], "175")
        self.assertEqual(verdict["funding"]["payer"], "melvin-bot[bot]")
        self.assertEqual(verdict["source_locations"],
                         ["src/components/DatePicker/CalendarPicker/Day.tsx"])

    def test_a_funded_issue_with_no_engineering_evidence_is_still_refused(self):
        verdict, reason = admit(context("[$175] Please add dark mode", "It would be nice.",
                                        [attestation()]))
        self.assertIsNone(verdict)
        self.assertEqual(reason, "HARD_ISSUE_EVIDENCE_MISSING")

    def test_the_proof_names_the_evidence_that_admitted_it(self):
        verdict, _ = admit(context(
            "[$175] Composer drops text",
            "Reproduced in src/pages/Report/ReportComposer.tsx.", [attestation()]))
        self.assertEqual(verdict["source_locations"], ["src/pages/Report/ReportComposer.tsx"])

    def test_authoritative_analysis_comment_can_locate_a_real_funded_bug(self):
        """Regression for Expensify/App#85907's analysis in the comment thread."""
        ctx = context(
            "[$250] Chat - Emojis pasted from Slack render as images",
            "Steps reproduce the broken image. Expected: emoji text. Actual: broken image.",
            [attestation()])
        analysis_url = "https://github.com/Expensify/App/issues/1#issuecomment-42"
        ctx["comments"].append({
            "user": {"login": "MelvinBot"},
            "author_association": "CONTRIBUTOR",
            "html_url": analysis_url,
            "body": ("Root cause is in the paste handler: "
                     "https://github.com/Expensify/App/blob/main/"
                     "src/hooks/useHtmlPaste/index.ts#L148-L170"),
        })

        verdict, reason = admit(ctx)

        self.assertEqual(reason, "")
        self.assertEqual(verdict["funding"]["usd_value"], "250")
        self.assertEqual(verdict["source_locations"], ["src/hooks/useHtmlPaste/index.ts"])
        self.assertIn(analysis_url, verdict["engineering_evidence_sources"])

    def test_untrusted_comment_cannot_supply_engineering_evidence(self):
        ctx = context("[$175] Please add dark mode", "It would be nice.", [attestation()])
        ctx["comments"].append({
            "user": {"login": "random-user"},
            "author_association": "NONE",
            "html_url": "https://github.com/Expensify/App/issues/1#issuecomment-43",
            "body": "https://github.com/Expensify/App/blob/main/src/app.ts",
        })

        verdict, reason = admit(ctx)

        self.assertIsNone(verdict)
        self.assertEqual(reason, "HARD_ISSUE_EVIDENCE_MISSING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
