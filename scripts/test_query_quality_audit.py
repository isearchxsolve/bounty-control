"""The query audit is the instrument that judges discovery changes, so it gets judged too.

Each test feeds a document with exactly one defect and asserts that the audit names it. A
meter that cannot fail is worse than no meter: it would report CLEAN on the roster that
reached main on 2026-11-06 with duplicate queries and qualifier-less searches.
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import query_quality_audit as audit  # noqa: E402

FOUNDER = {"founder": [
    'commenter:algora-pbc is:issue is:open',
    'label:bounty "$500" is:issue is:open',
    '"bounty" is:issue is:open',
    '"will pay" "crash" is:issue is:open',
]}


def kinds(document, today=None):
    return [f["kind"] for f in audit.audit(document, today)["findings"]]


class CleanRosterTests(unittest.TestCase):
    def test_a_roster_with_no_defect_is_clean(self):
        report = audit.audit(FOUNDER)
        self.assertEqual(report["verdict"], "CLEAN", report["findings"])

    def test_cross_lane_repeats_are_reported_but_never_fail(self):
        document = {"normal": ['commenter:algora-pbc is:issue is:open'],
                    "founder": ['commenter:algora-pbc is:issue is:open']}
        report = audit.audit(document)
        self.assertEqual(report["verdict"], "CLEAN", report["findings"])
        self.assertEqual(report["stats"]["cross_lane_repeats"], {"normal": 1, "founder": 1})


class DefectDetectionTests(unittest.TestCase):
    def test_duplicate_query_inside_one_lane_is_named(self):
        document = {"founder": ['commenter:algora-pbc is:issue is:open',
                                'commenter:algora-pbc is:issue is:open']}
        self.assertIn("DUPLICATE_WITHIN_LANE", kinds(document))

    def test_query_that_matches_pull_requests_is_named(self):
        document = {"founder": ['"bounty" in:title']}
        self.assertIn("NOT_ISSUE_QUALIFIED", kinds(document))

    def test_a_date_anchor_that_has_rotted_is_named_with_its_age(self):
        document = {"founder": ['commenter:algora-pbc is:issue is:open created:>=2026-01-01']}
        found = [f for f in audit.audit(document, audit.date(2026, 11, 6))["findings"]
                 if f["kind"] == "STALE_DATE_ANCHOR"]
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0]["age_days"], audit.MAX_ANCHOR_AGE_DAYS)

    def test_a_fresh_date_anchor_passes(self):
        document = {"founder": ['commenter:algora-pbc is:issue is:open created:>=2026-10-20']}
        self.assertEqual(audit.audit(document, audit.date(2026, 11, 6))["verdict"], "CLEAN")

    def test_a_vein_rendered_before_an_evidence_query_is_named(self):
        document = {"founder": ['"will pay" "crash" is:issue is:open',
                                'commenter:algora-pbc is:issue is:open']}
        self.assertIn("RENDERED_ORDER_BURIES_EVIDENCE", kinds(document))

    def test_a_missing_rendered_lane_is_named(self):
        self.assertIn("RENDERED_LANE_MISSING", kinds({"normal": ['"bounty" is:issue is:open']}))


class LiveRosterTests(unittest.TestCase):
    """The tracked roster must stay clean; a regression here means discovery regressed."""

    def test_the_tracked_roster_has_no_defect(self):
        document = json.loads((Path(__file__).resolve().parent / "bounty_queries.json")
                              .read_text(encoding="utf-8"))
        report = audit.audit(document)
        self.assertEqual(report["verdict"], "CLEAN", report["findings"])

    def test_the_rendered_lane_leads_with_an_attesting_actor(self):
        document = json.loads((Path(__file__).resolve().parent / "bounty_queries.json")
                              .read_text(encoding="utf-8"))
        founder = document["founder"]
        self.assertEqual(audit.tier(founder[0]), 0, founder[0])


class ExitCodeTests(unittest.TestCase):
    def test_a_clean_file_exits_zero(self):
        path = Path(__file__).resolve().parent / "bounty_queries.json"
        result = subprocess.run([sys.executable, str(Path(audit.__file__)), str(path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout[-400:])

    def test_a_missing_file_exits_one(self):
        result = subprocess.run([sys.executable, str(Path(audit.__file__)),
                                 "does-not-exist.json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
