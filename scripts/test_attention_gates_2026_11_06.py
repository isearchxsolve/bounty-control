"""Gates from the 2026-11-06 studies, pinned without the network.

Two sources, both landed 2026-11-06:

- docs/MARKET-STUDY-2026-11-06.md: escrow-only admission (NO_PLATFORM_ESCROW), 30-day
  push vitality (REPO_ACTIVE_DAYS=30) and the competition swarm (COMPETITION_SWARM=3).
- docs/FAST-MAINTAINER-ATTENTION-GATE-PROPOSAL-2026-11-06.md: ATT-08 (split CI states),
  ATT-09 (actor-evidenced attention clocks, submitted_at for reviews), ATT-12 (reversible
  ATTENTION_DEFERRED instead of terminal abandonment - fyne#6505 merged at day 48.6 and
  fyne#6103 at day 257.3, so age is never a "never merges" fact) and ATT-P15 (coverage
  receipt so a 20-row watch of 86 PRs shows its unobserved remainder).
"""
from datetime import datetime, timedelta, timezone
import pathlib
from types import SimpleNamespace
from unittest import mock
import unittest

import bounty_admission as admission
from bounty_admission import competition, repository_intent
from actions_github import task_id
from pipeline_evidence import (bind_proof, legacy_source_revision, require_evidence,
                               source_revision)
import pr_conversion_watch as watch

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
HERE = pathlib.Path(__file__).parent
GREEN = {"total": 13, "passing": 13, "failing": 0, "pending": 0, "approval_required": 0}


def ts(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def real_ts(days_ago):
    """repository_intent() reads the wall clock, so push fixtures must too."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------- market-study gates

class PushVitalityTests(unittest.TestCase):
    """REPO_ACTIVE_DAYS=30: ghost repos (no push in 30d+) are the top field-study killer."""

    def test_push_31_days_old_is_rejected(self):
        ok, reason = repository_intent({"merged": 5, "total": 100, "pushed_at": real_ts(31)})
        self.assertFalse(ok)
        self.assertEqual(reason, "REPOSITORY_MERGES_STALE")

    def test_push_29_days_old_is_allowed(self):
        ok, reason = repository_intent({"merged": 5, "total": 100, "pushed_at": real_ts(29)})
        self.assertTrue(ok, reason)

    def test_push_exactly_30_days_old_is_allowed(self):
        ok, reason = repository_intent({"merged": 5, "total": 100, "pushed_at": real_ts(29.5)})
        self.assertTrue(ok, reason)

    def test_missing_push_timestamp_never_rejects(self):
        ok, reason = repository_intent({"merged": 5, "total": 100})
        self.assertTrue(ok, reason)


def attestation(login, amount, association="NONE"):
    return {"user": {"login": login}, "author_association": association,
            "html_url": "https://github.com/o/r/issues/1#issuecomment-1",
            "body": "## $%s bounty\n1. Comment /attempt #1\n2. Open a PR with /claim #1\n" % amount}


def context(comments, association="CONTRIBUTOR", lane=None):
    ctx = {
        "repo": "o/r", "issue_number": 1,
        "repository": {"owner": {"login": "o"}, "archived": False, "disabled": False},
        "issue": {"title": "Fix the signature check in src/bridge.sol verifySignature()",
                  "body": "The guard in src/bridge.sol is incomplete.",
                  "state": "open", "html_url": "https://github.com/o/r/issues/1",
                  "user": {"login": "reporter"}, "author_association": association},
        "comments": comments, "complete_comments": True, "fetched_at": "unit fixture",
    }
    if lane:
        ctx["lane"] = lane
    return ctx


class EscrowOnlyTests(unittest.TestCase):
    """BOUNTY_ESCROW_ONLY=1: only a platform-bot attestation is escrow. Strict, no exemptions."""

    def admit(self, ctx):
        return admission.admit(ctx, quote=None, floor=80)

    def test_platform_bot_attestation_is_escrow_and_admits(self):
        with mock.patch.object(admission, "escrow_only_enabled", return_value=True):
            proof, reason = self.admit(context([attestation("algora-pbc[bot]", 900)]))
        self.assertEqual(reason, "")
        self.assertIsNotNone(proof)
        self.assertTrue(proof["funding"]["escrow"])

    def test_bountyhub_bot_attestation_is_escrow(self):
        with mock.patch.object(admission, "escrow_only_enabled", return_value=True):
            proof, reason = self.admit(context([attestation("bountyhub-bot", 300)]))
        self.assertEqual(reason, "")
        self.assertTrue(proof["funding"]["escrow"])

    def test_human_owner_verbal_offer_is_refused_under_escrow_only(self):
        with mock.patch.object(admission, "escrow_only_enabled", return_value=True):
            proof, reason = self.admit(context([attestation("maintainer", 900, "OWNER")],
                                               association="OWNER"))
        self.assertIsNone(proof)
        self.assertEqual(reason, "NO_PLATFORM_ESCROW")

    def test_unpriced_founder_request_is_also_not_escrow(self):
        # Strict gate: a FOUNDER currency offer carries no escrow flag, so it refuses too.
        with mock.patch.object(admission, "escrow_only_enabled", return_value=True):
            proof, reason = self.admit(context([], association="OWNER", lane="founder"))
        self.assertIsNone(proof)
        self.assertEqual(reason, "NO_PLATFORM_ESCROW")

    def test_without_the_flag_human_authority_still_admits(self):
        # Backward compatibility: fixtures and older callers keep the funding-authority logic.
        with mock.patch.object(admission, "escrow_only_enabled", return_value=False):
            proof, reason = self.admit(context([attestation("maintainer", 900, "OWNER")],
                                               association="OWNER"))
        self.assertEqual(reason, "")
        self.assertIsNotNone(proof)
        self.assertFalse(proof["funding"]["escrow"])


def drive_by(number, login):
    return {"number": number, "user": {"login": login}, "title": "fix #1272",
            "body": "", "head": {"ref": "feat/x", "sha": str(number) * 8, "repo": None},
            "html_url": "https://github.com/microg/GmsCore/pull/%d" % number}


def swarm_api(pulls):
    return SimpleNamespace(
        pages=lambda endpoint, **kwargs: iter(pulls) if endpoint.endswith("/pulls")
        else iter([]) if endpoint.endswith("/timeline") else iter([]),
        api=lambda endpoint: ({"total_count": 0} if "search/issues" in endpoint
                              else {"check_runs": []}))


class CompetitionSwarmTests(unittest.TestCase):
    """COMPETITION_SWARM=3: 3+ open PRs referencing one ticket is a lottery even if nominal."""

    def test_three_nominal_open_prs_trigger_the_swarm_refusal(self):
        api = swarm_api([drive_by(3941, "agent-a"), drive_by(3942, "agent-b"),
                         drive_by(3943, "agent-c")])
        with self.assertRaisesRegex(ValueError, "Competition swarm: 3"):
            competition(api, "microg/GmsCore", 1272)

    def test_two_nominal_open_prs_do_not_trigger_the_swarm(self):
        api = swarm_api([drive_by(3941, "agent-a"), drive_by(3942, "agent-b")])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"])
        self.assertEqual(len(verdict["nominal"]), 2)

    def test_one_real_competitor_still_blocks_before_the_swarm_counts(self):
        api = swarm_api([drive_by(3941, "proven-here")])
        api.api = lambda endpoint: ({"total_count": 4} if "search/issues" in endpoint
                                    else {"check_runs": []})
        with self.assertRaisesRegex(ValueError, "Competing open PR"):
            competition(api, "microg/GmsCore", 1272)


def own_pr(number, login="isearchxsolve"):
    pr = drive_by(number, login)
    pr["head"]["repo"] = {"owner": {"login": login}}
    return pr


class OwnPullRequestIsNotCompetition(unittest.TestCase):
    """Measured 2026-11-06 (run 42216544639): the door called competition() without
    own_head, so our own open PR was counted as an open reference and as a swarm member.
    A ticket we already hold was therefore unapproachable - even for a repair dispatch.
    Our own PR is a claim; it is never competition against ourselves."""

    def test_our_own_pr_alone_never_refuses(self):
        api = swarm_api([own_pr(3970)])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"])
        self.assertEqual(len(verdict["nominal"]), 0)

    def test_our_own_prs_do_not_accumulate_toward_the_swarm(self):
        api = swarm_api([own_pr(3970), own_pr(3969), own_pr(3967), drive_by(3968, "agent-b")])
        verdict = competition(api, "microg/GmsCore", 1272)
        self.assertFalse(verdict["blocking"], "one stranger is not a swarm of three")
        self.assertEqual(len(verdict["nominal"]), 1)

    def test_strangers_still_trigger_the_swarm(self):
        api = swarm_api([own_pr(3970), drive_by(3941, "a"), drive_by(3942, "b"),
                         drive_by(3943, "c")])
        with self.assertRaisesRegex(ValueError, "Competition swarm: 3"):
            competition(api, "microg/GmsCore", 1272)

    def test_own_head_is_still_honoured_without_a_repo_owner(self):
        pr = drive_by(3941, "isearchxsolve")
        pr["head"]["repo"] = None
        api = swarm_api([pr])
        verdict = competition(api, "microg/GmsCore", 1272, own_head=pr["head"]["sha"])
        self.assertEqual(len(verdict["nominal"]), 0)

    def test_the_door_reaches_the_same_verdict_as_the_dispatcher(self):
        # The door must not carry its own copy of the rule (it did: no own_head).
        source = (HERE / "cline_entry_door.py").read_text(encoding="utf-8")
        body = source.split("def competition_refusal(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("competition(client, repo, number)", body)


# ------------------------------------------------------- attention probes (ATT-08/09/12)

class ActorClassificationTests(unittest.TestCase):
    """ATT-P01/P02: bots and [bot] logins never create human attention receipts."""

    def test_bot_account_type_is_excluded(self):
        self.assertTrue(watch.actor_is_bot({"login": "some-app", "type": "Bot"}))

    def test_bot_suffix_is_excluded_even_on_a_user_account(self):
        self.assertTrue(watch.actor_is_bot({"login": "algora-pbc[bot]", "type": "User"}))

    def test_plain_human_is_not_a_bot(self):
        self.assertFalse(watch.actor_is_bot({"login": "ub3dqy", "type": "User"}))

    def test_missing_user_is_not_crashed(self):
        self.assertFalse(watch.actor_is_bot(None))
        self.assertFalse(watch.actor_is_bot({}))


class ApplicableReviewTests(unittest.TestCase):
    """ATT-P09: latest review per actor on the current head; dismissed and stale-head
    reviews are history, not verdicts."""

    def review(self, actor, state, head, at):
        return {"user": {"login": actor}, "state": state, "commit_id": head,
                "submitted_at": at, "html_url": "https://x/" + actor + state}

    def test_old_head_changes_requested_does_not_dominate_new_head_approval(self):
        reviews = [self.review("alice", "CHANGES_REQUESTED", "old-head", "2026-10-01T00:00:00Z"),
                   self.review("alice", "APPROVED", "new-head", "2026-10-05T00:00:00Z")]
        self.assertEqual(watch.current_review_decision(reviews, "new-head"), "approved")
        self.assertEqual(len(watch.applicable_reviews(reviews, "new-head")), 1)

    def test_dismissed_review_is_history(self):
        reviews = [self.review("alice", "CHANGES_REQUESTED", "new-head", "2026-10-01T00:00:00Z"),
                   self.review("alice", "DISMISSED", "new-head", "2026-10-06T00:00:00Z")]
        self.assertEqual(watch.current_review_decision(reviews, "new-head"), "none")

    def test_any_current_changes_requested_wins_over_approval(self):
        reviews = [self.review("alice", "APPROVED", "new-head", "2026-10-05T00:00:00Z"),
                   self.review("bob", "CHANGES_REQUESTED", "new-head", "2026-10-06T00:00:00Z")]
        self.assertEqual(watch.current_review_decision(reviews, "new-head"), "changes_requested")

    def test_latest_review_per_actor_is_used(self):
        reviews = [self.review("alice", "CHANGES_REQUESTED", "new-head", "2026-10-01T00:00:00Z"),
                   self.review("alice", "APPROVED", "new-head", "2026-10-07T00:00:00Z")]
        self.assertEqual(watch.current_review_decision(reviews, "new-head"), "approved")


def facts(**overrides):
    base = {"repo": "fyne-io/fyne", "number": 6637, "state": "open", "draft": False,
            "merged_at": None, "created_at": ts(2), "updated_at": ts(2),
            "review_count": 0, "review_decision": "none", "checks": dict(GREEN)}
    base.update(overrides)
    return base


class AttentionDeferredTests(unittest.TestCase):
    """ATT-12 / ATT-P12: 14+ days without a maintainer event parks REVERSIBLY."""

    def test_no_maintainer_action_for_15_days_is_deferred_not_abandoned(self):
        result = watch.classify(facts(created_at=ts(15), updated_at=ts(15)), NOW)
        self.assertEqual(result["state"], "ATTENTION_DEFERRED")
        self.assertEqual(result["action"], "park_reversible")
        self.assertIn("reactivates", result["reason"])

    def test_updated_at_is_never_the_waiting_clock_anchor(self):
        # ATT-P03: our own comment refreshed updated_at today; the PR is still 20 days
        # without a maintainer, so it must still defer (a updated_at anchor would hide it).
        result = watch.classify(facts(created_at=ts(20), updated_at=ts(0)), NOW)
        self.assertEqual(result["state"], "ATTENTION_DEFERRED")

    def test_a_recent_maintainer_event_reactivates_immediately(self):
        # Reversibility is structural: clocks are recomputed from events every run.
        result = watch.classify(facts(created_at=ts(20), updated_at=ts(0),
                                      last_maintainer_activity=ts(1)), NOW)
        self.assertNotEqual(result["state"], "ATTENTION_DEFERRED")
        self.assertEqual(result["state"], "WAITING_FRESH")

    def test_ready_for_review_is_the_anchor_for_drafts(self):
        # ATT-P06: created 40d ago as draft, ready 2d ago -> 2 days of waiting, not 40.
        result = watch.classify(facts(created_at=ts(40), updated_at=ts(2),
                                      ready_for_review_at=ts(2)), NOW)
        self.assertEqual(result["state"], "NEEDS_NUDGE")

    def test_deferral_does_not_fire_when_a_review_exists(self):
        result = watch.classify(facts(created_at=ts(30), updated_at=ts(30),
                                      review_count=1, review_decision="none"), NOW)
        self.assertEqual(result["state"], "STALE_WITH_COMMENTS")


class CheckStateSplitTests(unittest.TestCase):
    """ATT-08 / ATT-P08: approval-required is the maintainer's action, not red CI."""

    def test_approval_required_is_its_own_state(self):
        checks = {"total": 2, "passing": 1, "failing": 0, "pending": 0, "approval_required": 1}
        result = watch.classify(facts(checks=checks), NOW)
        self.assertEqual(result["state"], "APPROVAL_REQUIRED")
        self.assertEqual(result["action"], "request_approval")

    def test_real_failures_still_block_as_ours(self):
        checks = {"total": 2, "passing": 0, "failing": 1, "pending": 1, "approval_required": 0}
        result = watch.classify(facts(checks=checks), NOW)
        self.assertEqual(result["state"], "BLOCKED_CI")

    def test_unreadable_checks_are_unknown_never_green(self):
        result = watch.classify(facts(checks={"total": 0, "failing": 0, "pending": 0,
                                              "passing": 0, "approval_required": 0},
                                      checks_error="gh api failed: 403"), NOW)
        self.assertEqual(result["state"], "CI_UNKNOWN")
        self.assertEqual(result["action"], "recheck_checks")


class CoverageTests(unittest.TestCase):
    """ATT-P15: 86 authored PRs with a 20-row selection must show as truncated."""

    def test_truncated_receipt(self):
        receipt = watch.coverage_receipt(86, 20)
        self.assertTrue(receipt["truncated"])
        self.assertEqual(receipt["discovered_total"], 86)
        self.assertEqual(receipt["observed"], 20)

    def test_complete_receipt(self):
        self.assertFalse(watch.coverage_receipt(20, 20)["truncated"])
        self.assertFalse(watch.coverage_receipt(None, 0)["truncated"])

    def test_summary_counts_deferred_and_maintainer_action(self):
        rows = [
            {"facts": facts(number=1, created_at=ts(20), updated_at=ts(20)),
             "verdict": None},
            {"facts": facts(number=2, updated_at=ts(0), last_maintainer_activity=ts(1)),
             "verdict": None},
        ]
        for row in rows:
            row["verdict"] = watch.classify(row["facts"], NOW)
        summary = watch.summarise(rows)
        self.assertEqual(summary["attention_deferred"], 1)
        self.assertEqual(summary["with_maintainer_action"], 1)
        # park_reversible is a deliberate non-action, not an actionable nudge.
        self.assertEqual(summary["actionable"], 0)


class EvidenceFreshnessTests(unittest.TestCase):
    """Measured 2026-11-06: ``source_revision`` hashed the whole issue object and every
    comment, so a passing comment by an unrelated agent invalidated every deferred
    admission. The hydration lane then logged 42 rows as "Admission source changed; agent
    reconsideration required" on every run and the backlog could not drain - only a fresh
    agent pass could move them. The revision now covers the decision-bearing issue fields
    and the quoted attestation alone."""

    URL = "https://github.com/o/r/issues/1#issuecomment-7"
    ISSUE_URL = "https://github.com/o/r/issues/1"

    def attestation(self, body="## $300 bounty\n1. Comment `/attempt #1`\n2. Open a PR with `/claim #1`"):
        return {"html_url": self.URL, "body": body, "created_at": "2026-11-04T10:00:00Z",
                "updated_at": "2026-11-04T10:00:00Z",
                "user": {"login": "bountyhub-bot", "type": "Bot"}}

    def stranger(self, n=2):
        return {"html_url": self.ISSUE_URL + "#issuecomment-9%d" % n,
                "body": "I am taking this one", "created_at": "2026-11-06T09:0%d:00Z" % n,
                "updated_at": "2026-11-06T09:0%d:00Z" % n,
                "user": {"login": "agent-%d" % n, "type": "User"}}

    def context(self, comments=None, body=None, state="open"):
        return {
            "repo": "o/r", "issue_number": 1,
            "issue": {"html_url": self.ISSUE_URL, "title": "Implementation of Nearby Share",
                      "body": body if body is not None else "Implement the service.",
                      "state": state, "updated_at": "2026-11-06T00:00:00Z", "comments": 2,
                      "user": {"login": "owner"}, "author_association": "OWNER"},
            "comments": [self.attestation()] if comments is None else comments,
            "complete_comments": True,
            "repository": {"archived": False, "disabled": False},
        }

    def funding(self):
        return {"amount": "300", "currency": "USD", "usd_value": "300", "raw": "$300",
                "source_url": self.URL, "payer": "bountyhub-bot", "escrow": True}

    def bound(self, context=None):
        ctx = context or self.context()
        admission = bind_proof({"funding": self.funding()}, ctx)
        source = {"sovereign_admission": True, "admission": admission,
                  "competition": {"blocking": False}}
        return ctx, admission, source

    def test_a_stranger_comment_no_longer_invalidates_the_admission(self):
        _, admission, source = self.bound()
        later = self.context(comments=[self.attestation(), self.stranger()])
        later["issue"]["updated_at"] = "2026-11-06T11:11:00Z"
        later["issue"]["comments"] = 3
        require_evidence(source, later)  # must not raise
        self.assertEqual(source_revision(later, admission), admission["source_revision"])

    def test_a_bot_comment_no_longer_invalidates_the_admission(self):
        _, admission, source = self.bound()
        later = self.context(comments=[self.attestation(), self.stranger(3)])
        require_evidence(source, later)

    def test_editing_the_quoted_attestation_still_invalidates(self):
        _, _, source = self.bound()
        raised = self.context(comments=[self.attestation("## $900 bounty\n/claim #1")])
        with self.assertRaisesRegex(ValueError, "source changed"):
            require_evidence(source, raised)

    def test_deleting_the_quoted_attestation_still_invalidates(self):
        _, _, source = self.bound()
        with self.assertRaisesRegex(ValueError, "source changed"):
            require_evidence(source, self.context(comments=[self.stranger()]))

    def test_editing_the_issue_body_still_invalidates(self):
        _, _, source = self.bound()
        widened = self.context(body="Implement the service and the whole Nearby stack.")
        with self.assertRaisesRegex(ValueError, "source changed"):
            require_evidence(source, widened)

    def test_closing_the_issue_keeps_its_own_message(self):
        _, _, source = self.bound()
        with self.assertRaisesRegex(ValueError, "no longer open"):
            require_evidence(source, self.context(state="closed"))

    def test_a_row_bound_under_the_old_formula_drains_when_nothing_moved(self):
        # The 192-row backlog was bound before this contract. Old bytes reproduce the old
        # digest exactly, which is evidence that nothing moved - so it may proceed.
        ctx = self.context()
        legacy = {"funding": self.funding(), "task_id": task_id("o/r", 1),
                  "source_revision": legacy_source_revision(ctx)}
        source = {"sovereign_admission": True, "admission": legacy,
                  "competition": {"blocking": False}}
        require_evidence(source, ctx)  # must not raise

        moved = self.context(comments=[self.attestation(), self.stranger()])
        with self.assertRaisesRegex(ValueError, "source changed"):
            require_evidence(source, moved)

    def test_a_proof_without_funding_keeps_the_strict_contract(self):
        ctx = self.context()
        admission = bind_proof({"funding": None}, ctx)
        source = {"sovereign_admission": True, "admission": admission,
                  "competition": {"blocking": False}}
        later = self.context(comments=[self.attestation(), self.stranger()])
        with self.assertRaisesRegex(ValueError, "source changed"):
            require_evidence(source, later)


if __name__ == "__main__":
    unittest.main()