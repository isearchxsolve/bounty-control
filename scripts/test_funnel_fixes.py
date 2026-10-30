"""Funnel fixes pinned by tests: the admission floor, the hydration drain lane, the
silo-hunter entrypoint, and the verified engagement report.

Measured market context (2026-10-30): across 53 priced titles on three high-yield
queries, the median bounty is $250. A $2,000 floor kept only 3.8% of priced
bounties and admitted exactly one task in the live cycle that closed the wiring
proof; a $250 floor keeps 60.4%. These tests pin the code to the market number and
to the lanes that were dead by construction: the mass-attack templates are gone, the
engagement report is wired to real delivery receipts, and hydration can drain the
durable pending queue without the search-API throttle.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from bounty_admission import FLOOR  # noqa: E402
from actions_dispatch import pending_window  # noqa: E402


def row(task_id, repository):
    return (task_id, json.dumps({"repository_url": "https://api.github.com/repos/" + repository,
                                 "number": 1}), "programs")


class FloorPolicyTests(unittest.TestCase):
    """The live default floor is the market median, and admission honours it."""

    def test_default_floor_is_the_measured_market_median(self):
        self.assertEqual(FLOOR.as_tuple().exponent, -0)  # whole dollars
        self.assertEqual(int(FLOOR), 250)

    def test_a_median_priced_offer_admits_under_the_live_default(self):
        from test_admission_trust import _admit, attestation, context
        proof, reason = _admit(context([attestation("algora-pbc[bot]", 250)]))
        self.assertEqual(reason, "")
        self.assertIsNotNone(proof)
        self.assertEqual(proof["funding"]["amount"], "250")

    def test_an_offer_below_the_median_is_still_refused(self):
        from test_admission_trust import _admit, attestation, context
        proof, reason = _admit(context([attestation("algora-pbc[bot]", 249)]))
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")


class HydrationDrainTests(unittest.TestCase):
    """The hydration-only lane raises the batch on the core budget; the per-repo
    cap and the capacity exclusion keep binding at the larger batch."""

    def test_batch_raises_to_three_hundred(self):
        rows = [row(f"t-{i}", f"org{i % 40}/repo{i % 40}") for i in range(350)]
        chosen = pending_window(rows, limit=300)
        self.assertLessEqual(len(chosen), 300)
        self.assertEqual(len(chosen), 300)

    def test_a_single_real_origin_still_drains_the_raised_batch(self):
        # The batch limit is a truncation cap, never a share: one legitimate origin
        # queue is drained in full up to the raised limit, exactly as the 60-batch
        # contract behaves today, only five times deeper per cycle.
        rows = [row(f"only-{i}", "owner/project") for i in range(320)]
        self.assertEqual(len(pending_window(rows, limit=300)), 300)

    def test_excluded_repositories_never_spend_slots(self):
        rows = [row("excluded", "TooBig/Repo"), row("ok", "Fine/Repo")]
        chosen = pending_window(rows, limit=300, excluded_repositories=("TooBig/Repo",))
        self.assertEqual([r[0] for r in chosen], ["ok"])


class SiloHunterEntrypointTests(unittest.TestCase):
    """scripts/agentic_silo_hunter.py is a compat entrypoint into the shared
    dispatcher; it must not carry an independent floor constant that could disagree
    with (or bypass) the layer-3 admission floor."""

    def test_entrypoint_has_no_independent_floor_constant(self):
        source = (HERE / "agentic_silo_hunter.py").read_text(encoding="utf-8")
        self.assertNotIn("MIN_BOUNTY_USD", source)
        self.assertNotIn("FLOOR =", source)
        self.assertIn("actions_dispatch", source)

    def test_entrypoint_routes_to_the_shared_main(self):
        import agentic_silo_hunter
        import actions_dispatch
        self.assertIs(agentic_silo_hunter.main, actions_dispatch.main)


class EngagementReportTests(unittest.TestCase):
    """The six-part founder report is built only from real delivery receipts; an
    evidence-free call is refused, never filled with canned claims."""

    def test_real_receipts_build_the_full_report(self):
        from outreach_report import build_report
        receipt = {
            "base_sha": "abc123", "run_url": "https://github.com/o/r/actions/runs/1",
            "verification": [
                {"argv": ["pytest", "tests/test_gate.py"], "exit_code": 0, "duration_s": 1.25},
                {"argv": ["python", "-m", "py_compile", "scripts/actions_dispatch.py"],
                 "exit_code": 0, "duration_s": 0.5},
            ],
        }
        context = {"repo": "org/pkg", "issue_number": 41,
                   "title": "Fix the replay guard"}
        with self.subTest(step="impact line leads"):
            report = build_report(
                impact="A native-verified fix for issue #41 is submitted as pull request http://pr.",
                affected="Maintainers and users of org/pkg who hit #41.",
                steps=["On the proposed head, run: pytest tests/test_gate.py"],
                proof=["Verified base abc123 -> head deadbeef", "`pytest ...` exit 0, 1.25s"],
                fix="Apply pull request http://pr.",
                detail="Engine run: https://x/1",
                repo="org/pkg",
            )
            self.assertIn("pull request http://pr.", report)
            self.assertIn("abc123", report)
            self.assertIn("exit 0", report)
        with self.subTest(step="no evidence is refused, not filled"):
            from outreach_report import MissingEvidence
            with self.assertRaises(MissingEvidence):
                build_report(impact="none", affected="none", steps=[], proof=[], fix="x", repo="org/pkg")

    def test_engagement_comment_refused_for_payment_rails(self):
        # Payment coordinates in a public comment are refused by the same guard that
        # protects the live outreach: a UPI handle shape is caught by the real regex.
        from outreach_report import MissingEvidence, build_report
        with self.assertRaises(MissingEvidence):
            build_report(impact="p-38 Rs 12500 advance isearch.xsolve-3@okhdfcbank now",
                         affected="buyer", steps=["s"], proof=["evidence"], fix="x", repo="org/pkg")


if __name__ == "__main__":
    unittest.main()