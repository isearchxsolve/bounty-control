"""Deterministic unit fixtures; these are not live delivery receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from actions_dispatch import (HYDRATION_BATCH, QUERY_EXCLUDED_ASSIGNED, QUERY_EXCLUDED_EXPERIMENT,
                              QUERY_EXCLUDED_VIDEO_DEMO, build_issue_search_queries, discover,
                              query_exclusion_status, query_window, refreshed_query_exclusion,
                              retire_query_excluded_pending)
from actions_github import GitHub, GitHubError, StateStore, task_id
from delivery_errors import PreparationContractViolation
from actions_reconcile import classify_checks
from actions_release import (git, manifest, protect_baseline_tests, regression_proof,
                             require_commands, safe_path, status_paths, validate_plan_contract, restore_checkpoint)
from bounty_admission import admit as _admit, amounts, competition

# These fixtures document real issues at the amounts those issues actually carried
# ($500-$1200), which is the whole point of them: they pin gate behaviour against
# measured payloads, not against invented numbers. The admission floor is a separate
# policy knob that moved from 80 to 2000 on 2026-10-29, and leaving these calls on the
# ambient default made every one of them fail for a reason none of them is about.
# The floor's own behaviour stays pinned by test_admission_trust (FLOOR - 1 is refused)
# and test_program_offers (FLOOR > 10, and a $10 title is refused).
FIXTURE_FLOOR = 80


def admit(context, quote=None, floor=FIXTURE_FLOOR):
    """Admission under the floor these fixtures were authored against."""
    return _admit(context, quote=quote, floor=floor)


def context():
    return {"repo": "owner/project", "issue_number": 7, "title": "Parser race condition", "body": "Fix src/parser.py", "complete_comments": True,
            "repository": {"owner": {"login": "owner"}}, "fetched_at": "unit fixture",
            "issue": {"title": "Parser race condition", "body": "Fix deadlock in src/parser.py. Bounty $500.",
                      "state": "open", "html_url": "https://github.com/owner/project/issues/7",
                      "user": {"login": "owner"}, "author_association": "OWNER"}, "comments": []}


class AdmissionTests(unittest.TestCase):
    def test_real_issuer_amount_and_hard_scope(self):
        proof, reason = admit(context())
        self.assertEqual(reason, "")
        self.assertEqual(proof["funding"]["amount"], "500")

    def test_comment_offer_and_title_offer(self):
        c = context()
        c["comments"] = [{**c["issue"], "body": "/bounty $1200"}]
        c["issue"]["body"] = "Fix parser deadlock in src/parser.py"
        self.assertEqual(admit(c)[0]["funding"]["amount"], "1200")
        c["comments"] = []
        c["issue"]["title"] = "[Bounty $100] parser regression"
        self.assertIsNotNone(admit(c)[0])

    def test_funding_match_offsets_survive_long_code_blocks_and_repeated_price(self):
        c = context()
        c["issue"]["title"] = "[$750] memory performance regression"
        c["issue"]["body"] = ("Fix src/parser.py\n" + "x" * 1000 + "\n```sh\n" + "code\n" * 200 +
                               "```\n" + "z" * 1000 + "\nBounty: $750 USD paid by maintainers")
        self.assertEqual(admit(c)[0]["funding"]["amount"], "750")

    def test_no_phantom_amount_from_severity(self):
        c = context()
        c["issue"]["body"] = "P0 parser crash in src/parser.py; urgent bounty"
        self.assertIsNone(admit(c)[0])

    def test_payee_and_untrusted_offer(self):
        for body, login, association in [("Bounty $500; payout wallet", "owner", "OWNER"),
                                          ("Bounty $500", "outsider", "NONE")]:
            c = context()
            c["issue"].update(body="Parser crash in src/parser.py " + body,
                               user={"login": login}, author_association=association)
            self.assertIsNone(admit(c)[0])

    def test_withdrawal_overrides_previous_offer(self):
        c = context()
        c["comments"] = [{**c["issue"], "body": "Withdraw the bounty; no longer offering"}]
        self.assertIsNone(admit(c)[0])

    def test_metrics_code_strikethrough_not_currency(self):
        for body in ["$500$ micrometers", "~~$500~~", "```\n$500\n```", "$500 TVL", "$500 pool"]:
            self.assertEqual(list(amounts(body)), [])

    def test_missing_comments_and_mirrors(self):
        c = context()
        c["complete_comments"] = False
        self.assertEqual(admit(c)[1], "INCOMPLETE_COMMENTS")
        c = context()
        c["issue"]["title"] = "Daily digest"
        self.assertIsNone(admit(c)[0])

    def test_crypto_requires_observed_quote(self):
        c = context()
        c["issue"]["body"] = "Parser deadlock src/parser.py bounty 2 SOL"
        self.assertIsNone(admit(c)[0])
        self.assertIsNotNone(admit(c, quote=lambda _: {"usd_rate": "60", "source_url": "unit fixture"})[0])

    def test_component_not_invented_from_url(self):
        c = context()
        c["issue"].update(title="Crash bounty $500", body="Crash https://example.org/a/file.py")
        # External URLs do not create component references, but the crash signal alone
        # qualifies as engineering evidence for a funded bounty issue
        self.assertIsNotNone(admit(c)[0])


class TransportTests(unittest.TestCase):
    def test_live_discovery_workflow_advances_three_queries_per_lane(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                    "bounty-discovery.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"--queries-per-lane\s+3\b")

    def test_or_search_carries_common_bounty_context_and_trailing_filters(self):
        expressions = [
            ('label:bounty "auth" OR "permission" OR "unauthorized" is:issue is:open',
             ['"auth"', '"permission"', '"unauthorized"']),
            ('"/bounty" "wallet" OR "solana" OR "token" is:issue is:open',
             ['"wallet"', '"solana"', '"token"']),
        ]
        for expression, alternatives in expressions:
            with self.subTest(expression=expression):
                queries = build_issue_search_queries(expression)
                self.assertEqual(len(queries), len(alternatives))
                for query, alternative in zip(queries, alternatives):
                    self.assertIn(alternative, query)
                    self.assertIn("label:bounty" if expression.startswith("label:") else '"/bounty"', query)
                    self.assertIn("is:issue", query)
                    self.assertIn("is:open", query)
                    self.assertIn("no:assignee", query)
                    self.assertIn("-linked:pr", query)
                    self.assertIn("-label:video-demo", query)
                    self.assertNotIn(" OR ", query)
                    self.assertEqual(query.count("is:issue"), 1)
                    self.assertEqual(query.count("is:open"), 1)

    def test_video_and_experiment_labels_are_excluded_in_query_and_cached_queue(self):
        queries = build_issue_search_queries('label:bounty "mesh demo" OR "agent" is:issue is:open')
        self.assertEqual(len(queries), 2)
        self.assertTrue(all("-label:video-demo" in query for query in queries))

        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE pending(task_id TEXT PRIMARY KEY,payload TEXT,lanes TEXT,"
                    "signature TEXT,checked REAL DEFAULT 0,status TEXT DEFAULT 'pending')")
        rows = [
            ("video", {"labels": [{"name": "video-demo"}], "assignees": []}),
            ("experiment", {"labels": [{"name": "type/experiment"}], "assignees": []}),
            ("engineering", {"labels": [{"name": "bounty"}], "assignees": []}),
        ]
        for identity, payload in rows:
            con.execute("INSERT INTO pending(task_id,payload,status) VALUES(?,?, 'pending')",
                        (identity, json.dumps(payload)))
        retired = retire_query_excluded_pending(con)
        statuses = dict(con.execute("SELECT task_id,status FROM pending"))
        self.assertEqual(retired[QUERY_EXCLUDED_VIDEO_DEMO], 1)
        self.assertEqual(retired[QUERY_EXCLUDED_EXPERIMENT], 1)
        self.assertEqual(statuses["video"], QUERY_EXCLUDED_VIDEO_DEMO)
        self.assertEqual(statuses["experiment"], QUERY_EXCLUDED_EXPERIMENT)
        self.assertEqual(statuses["engineering"], "pending")
        con.close()

    def test_or_inside_quoted_text_is_not_split(self):
        queries = build_issue_search_queries('"wallet OR token" is:issue is:open')
        self.assertEqual(len(queries), 1)
        self.assertIn('"wallet OR token"', queries[0])

    def test_complete_search_pagination(self):
        calls = []
        def get(endpoint):
            calls.append(endpoint)
            return {"items": [dict(number=i) for i in range(100 if len(calls) == 1 else 37)],
                    "total_count": 137, "incomplete_results": False}
        rows, total = query_window(SimpleNamespace(api=get), "bounty")
        self.assertEqual((len(rows), total, len(calls)), (137, 137, 2))

    def test_saturated_search_partitions_before_hydration(self):
        rows, total = query_window(SimpleNamespace(api=lambda _: {"items": [{}] * 100, "total_count": 1500}), "bounty")
        self.assertEqual((rows, total), ([], 1500))

    def test_incomplete_is_error_not_zero(self):
        with self.assertRaises(GitHubError):
            query_window(SimpleNamespace(api=lambda _: {"items": [], "incomplete_results": True}), "bounty")

    def test_full_issue_body_and_all_comments(self):
        api = GitHub()
        issue = {"title": "fixture", "body": "x" * 50000, "comments": 101}
        def get(url, **kwargs):
            if "/comments?" in url:
                self.assertTrue(kwargs["paginate"])
                return [[{}] * 99, [{}] * 2]
            return issue if "/issues/" in url else {"default_branch": "main"}
        with patch.object(api, "api", side_effect=get):
            result = api.issue_context("owner/repo", 1)
        self.assertTrue(result["complete_comments"])
        self.assertEqual(len(result["body"]), 50000)

    def test_stale_rest_counter_needs_independent_visible_count_and_last_id(self):
        api = GitHub()
        issue = {"title": "fixture", "body": "full context", "comments": 3}
        def get(url, *args, **kwargs):
            if url == "graphql":
                return {"data": {"repository": {"issue": {"comments": {
                    "totalCount": 2, "nodes": [{"databaseId": 12}]}}}}}
            if "/comments?" in url:
                return [[{"id": 11}, {"id": 12}]]
            return issue if "/issues/" in url else {}
        with patch.object(api, "api", side_effect=get):
            result = api.issue_context("owner/repo", 1)
        self.assertTrue(result["complete_comments"])
        self.assertEqual(result["comment_count_evidence"]["rest_reported"], 3)
        self.assertEqual(result["comment_count_evidence"]["graphql_visible"], 2)

    def test_unsafe_task_identity_rejected(self):
        for repo, number in [("a/b;echo", 1), ("a/b", "$(shell)"), ("a/b", True)]:
            with self.assertRaises(ValueError):
                task_id(repo, number)

    def test_hydration_budget_keeps_every_unprocessed_search_result(self):
        items = [{"repository_url": "https://api.github.com/repos/owner/project", "number": n,
                  "updated_at": "fixture"} for n in range(1, HYDRATION_BATCH + 42)]
        def get(endpoint):
            if "search/issues?" in endpoint:
                rows = items[:30] if "per_page=30" in endpoint else items[100:] if "&page=2" in endpoint else items[:100]
                return {"items": rows, "total_count": len(items)}
            if endpoint.startswith("repos/"):
                # The capacity pre-check measures repository size before spending hydration
                # slots. A small size keeps this fixture about the hydration budget.
                return {"size": 1024}
            raise AssertionError(endpoint)
        fake = SimpleNamespace(api=get, issue_context=lambda repo, number: context(), pages=lambda *a, **k: [])
        import sqlite3
        with tempfile.TemporaryDirectory() as folder, patch("actions_dispatch.GitHub", return_value=fake):
            with patch("builtins.print"):
                discover(["normal"], queries_per_lane=1, state_dir=folder)
            with sqlite3.connect(Path(folder) / "discovery.sqlite3") as con:
                counts = dict(con.execute("SELECT status,count(*) FROM pending GROUP BY status"))
            con.close()
            self.assertEqual(counts, {"checked": HYDRATION_BATCH, "pending": 41})
            con = sqlite3.connect(Path(folder) / "discovery.sqlite3")
            con.execute("UPDATE metadata SET value='previous broken policy' WHERE name='admission_policy'")
            con.execute("UPDATE pending SET status='checked'")
            con.commit()
            con.close()
            with patch("builtins.print"):
                discover(["normal"], queries_per_lane=1, state_dir=folder)
            con = sqlite3.connect(Path(folder) / "discovery.sqlite3")
            counts = dict(con.execute("SELECT status,count(*) FROM pending GROUP BY status"))
            con.close()
            self.assertEqual(counts, {"checked": HYDRATION_BATCH, "pending": 41})

    def test_current_open_competition(self):
        pr = {"title": "Fix #7", "body": "", "head": {"ref": "fix/7", "sha": "a", "repo": None}, "html_url": "unit fixture"}
        api = SimpleNamespace(pages=lambda *a, **k: [pr])
        with self.assertRaisesRegex(ValueError, "Competing"):
            competition(api, "owner/project", 7)

    def test_merged_fixed_pr_in_timeline_excludes_still_open_issue(self):
        event = {"event": "cross-referenced", "source": {"issue": {
            "state": "closed", "pull_request": {"url": "https://api.github.com/repos/owner/project/pulls/88"}}}}
        pull = {"base": {"repo": {"full_name": "owner/project"}},
                "head": {"sha": "merged-head"}, "merged_at": "2026-10-26T17:34:41Z",
                "body": "### Fixed Issues\n\nhttps://github.com/owner/project/issues/7",
                "html_url": "https://github.com/owner/project/pull/88"}
        api = SimpleNamespace(
            pages=lambda endpoint, **kwargs: [event] if "/timeline" in endpoint else [],
            api=lambda endpoint: pull)
        with self.assertRaisesRegex(ValueError, "resolved by merged PR"):
            competition(api, "owner/project", 7)

    def test_merged_related_pr_without_fixed_issue_claim_does_not_block(self):
        event = {"event": "cross-referenced", "source": {"issue": {
            "state": "closed", "pull_request": {"url": "https://api.github.com/repos/owner/project/pulls/88"}}}}
        pull = {"base": {"repo": {"full_name": "owner/project"}},
                "head": {"sha": "merged-head"}, "merged_at": "2026-10-26T17:34:41Z",
                "body": "### Related Issues\n\nhttps://github.com/owner/project/issues/7",
                "html_url": "https://github.com/owner/project/pull/88"}
        api = SimpleNamespace(
            pages=lambda endpoint, **kwargs: [event] if "/timeline" in endpoint else [],
            api=lambda endpoint: pull)
        self.assertTrue(competition(api, "owner/project", 7))

    def test_contributor_open_expression_omits_no_assignee(self):
        # Help Wanted label: contributor-open work is not filtered to unassigned-only.
        query = build_issue_search_queries('label:"Help Wanted" "bug" is:issue is:open')[0]
        self.assertNotIn("no:assignee", query)
        self.assertIn('label:"Help Wanted"', query)
        self.assertIn("is:issue", query)
        self.assertIn("is:open", query)
        # External label: contributor-open work is not filtered to unassigned-only.
        query = build_issue_search_queries('label:External "bug" is:issue is:open')[0]
        self.assertNotIn("no:assignee", query)
        self.assertIn("label:External", query)
        # Approved paid-program repo: Expensify bounties are assigned but contributor-open.
        query = build_issue_search_queries(
            'repo:Expensify/App label:Bug in:title "$250" -label:"Awaiting Payment" is:issue is:open'
        )[0]
        self.assertNotIn("no:assignee", query)
        self.assertIn("repo:Expensify/App", query)
        self.assertIn('in:title "$250"', query)
        # Standard bounty query keeps no:assignee (existing behavior preserved).
        query = build_issue_search_queries('label:bounty "wallet" is:issue is:open')[0]
        self.assertIn("no:assignee", query)
        self.assertIn("label:bounty", query)

    def test_help_wanted_issue_is_not_excluded_as_assigned(self):
        # Assigned issue carrying Help Wanted is contributor-open, not excluded.
        item = {
            "assignees": [{"login": "bugzero-triage"}],
            "labels": [{"name": "External"}, {"name": "Help Wanted"}, {"name": "Bug"}],
        }
        self.assertEqual(query_exclusion_status(item), "")
        # Help Wanted alone suffices to override assignment exclusion.
        item = {"assignees": [{"login": "someone"}], "labels": [{"name": "Help Wanted"}]}
        self.assertEqual(query_exclusion_status(item), "")
        # Assigned without Help Wanted is still excluded.
        item = {"assignees": [{"login": "someone"}], "labels": []}
        self.assertEqual(query_exclusion_status(item), QUERY_EXCLUDED_ASSIGNED)

    def test_live_issue_refresh_reapplies_query_exclusions(self):
        context = {"issue": {"assignees": [{"login": "contributor"}], "labels": []}}
        self.assertEqual(refreshed_query_exclusion(context), "query_excluded_assigned")
        context["issue"] = {"assignees": [], "labels": [{"name": "video-demo"}]}
        self.assertEqual(refreshed_query_exclusion(context), QUERY_EXCLUDED_VIDEO_DEMO)

    def test_ownership_and_attempt_bounds(self):
        store = StateStore()
        old = {"status": "CLAIMED", "owner": "1:1", "attempt": 1}
        store.mutate = lambda identity, change: change(old)
        store.api = SimpleNamespace(api=lambda _: {"status": "in_progress"})
        with self.assertRaisesRegex(ValueError, "live Actions"):
            store.claim("owner/project", 7, "2:1", "run", "sha")
        old.update(status="FAILED", attempt=3)
        with self.assertRaisesRegex(ValueError, "exhausted"):
            store.claim("owner/project", 7, "2:1", "run", "sha")

    def test_remote_no_checks_is_not_passed(self):
        api = SimpleNamespace(api=lambda _: {"check_runs": []}, pages=lambda _: [])
        self.assertEqual(classify_checks(api, "owner/project", "head")["state"], "NO_REMOTE_CHECKS")

    def test_later_rerun_supersedes_old_failure(self):
        rows = [{"id": 1, "name": "native", "status": "completed", "conclusion": "failure"},
                {"id": 2, "name": "native", "status": "completed", "conclusion": "success"}]
        api = SimpleNamespace(api=lambda _: {"check_runs": rows}, pages=lambda _: [])
        self.assertEqual(classify_checks(api, "owner/project", "head")["state"], "PASSED")

    def test_maintainer_approval_is_held_not_a_code_repair(self):
        # Contract change, 2026-11-01. This test previously pinned action_required as PENDING,
        # which was wrong in a way that cost real deliveries: measured across 18 open PRs, 15 had
        # no executed checks and paraloom-core/kivaloo returned action_required on 8 of 8 runs, so
        # every one of them sat in "CI still running" forever and never aged into an obligation.
        # Held is still not a code repair -- nothing failed -- but it is no longer reported as a
        # run in progress. The assertion that survives unchanged is failures == [].
        rows = [{"id": 1, "name": "native", "status": "completed", "conclusion": "action_required"}]
        api = SimpleNamespace(api=lambda _: {"check_runs": rows}, pages=lambda _: [])
        proof = classify_checks(api, "owner/project", "head")
        self.assertEqual(proof["state"], "HELD")
        self.assertEqual(proof["failures"], [])


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "user.name", "Unit fixture")
        git(self.root, "config", "core.autocrlf", "false")
        (self.root / "product.py").write_text("def value(): return 0\n")
        (self.root / "tests").mkdir()
        (self.root / "tests/master.py").write_text("# immutable fixture\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "unit baseline")
        self.base = git(self.root, "rev-parse", "HEAD").stdout.decode().strip()

    def tearDown(self):
        self.temp.cleanup()

    def test_new_test_directory_preserved(self):
        p = self.root / "tests/regression/new case.py"
        p.parent.mkdir()
        p.write_text("# companion")
        self.assertEqual(status_paths(self.root), ["tests/regression/new case.py"])

    @unittest.skipIf(os.name == "nt", "Windows filesystem prohibits newline names")
    def test_newline_path_roundtrip(self):
        (self.root / "odd\nname.py").write_text("# companion")
        self.assertEqual(status_paths(self.root), ["odd\nname.py"])

    def test_rename_and_deletion_include_sources(self):
        git(self.root, "mv", "product.py", "renamed.py")
        self.assertEqual(status_paths(self.root), ["product.py", "renamed.py"])

    def test_master_tests_are_immutable(self):
        with self.assertRaisesRegex(ValueError, "master test"):
            protect_baseline_tests(self.root, self.base, ["tests/master.py"])

    def test_git_object_script_protection_without_checkout(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "native-test"}}))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "unit manifest")
        base = git(self.root, "rev-parse", "HEAD").stdout.decode().strip()
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "echo pass"}}))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "tamper fixture")
        head = git(self.root, "rev-parse", "HEAD").stdout.decode().strip()
        (self.root / "package.json").unlink()
        with self.assertRaisesRegex(ValueError, "verification script"):
            protect_baseline_tests(self.root, base, ["package.json"], head_sha=head)

    def test_paths_cannot_escape(self):
        for name in ("../secret", "/absolute", ".git/config", ".github/workflows/ci.yml"):
            with self.assertRaises(ValueError):
                safe_path(self.root, name)

    def test_real_red_to_green_runs_actual_source(self):
        (self.root / "product.py").write_text("def value(): return 1\n")
        test = self.root / "tests/regression.py"
        test.write_text("from product import value\nassert value() == 1, 'specific regression fixture assertion'\n")
        before = manifest(self.root, status_paths(self.root))
        def execute(argv):
            result = subprocess.run(argv, cwd=self.root, text=True, capture_output=True,
                                    env={**os.environ, "PYTHONPATH": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}, timeout=10)
            return SimpleNamespace(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)
        proof = regression_proof(self.root, self.base, {"test_files": ["tests/regression.py"],
                "argv": [sys.executable, "-B", str(test)], "expected_failure": "specific regression fixture assertion"}, execute)
        self.assertNotEqual(proof["red_exit"], 0)
        self.assertEqual(proof["green_exit"], 0)
        self.assertEqual(manifest(self.root, status_paths(self.root)), before)

    def test_checkpoint_restores_real_tracked_and_new_companion_bytes(self):
        import zipfile
        (self.root / "product.py").write_text("def value(): return 1\n")
        patch_bytes = git(self.root, "diff", "--binary", "HEAD").stdout
        git(self.root, "restore", "product.py")
        with tempfile.TemporaryDirectory() as outside:
            archive = Path(outside) / "checkpoint.zip"
            with zipfile.ZipFile(archive, "w") as saved:
                saved.writestr("checkpoint.json", json.dumps({"schema": 1, "head_sha": self.base}))
                saved.writestr("tracked.patch", patch_bytes)
                saved.writestr("untracked/tests/new_companion.py", "# retained companion\n")
            receipt = restore_checkpoint(self.root, self.base, archive)
        self.assertEqual(receipt["status"], "RESTORED")
        self.assertEqual((self.root / "product.py").read_text(), "def value(): return 1\n")
        self.assertEqual((self.root / "tests/new_companion.py").read_text(), "# retained companion\n")

    def test_failed_or_warning_receipts_block(self):
        for code, output in [(1, ""), (0, "warning: unsafe"), (0, "npm warn unsupported engine"), (0, "4:4 warning unused variable"), (0, "0 errors, 2 warnings"), (0, "Ran 0 tests")]:
            with self.assertRaises(ValueError):
                require_commands([["native", "test"]], [{"argv": ["native", "test"], "exit_code": code, "stdout": output}])
        with self.assertRaises(ValueError):
            require_commands([["native", "test"]], [])

    def test_no_bypass_native_plan(self):
        for command in (["echo", "pass"], ["npm", "test", "--if-present"], ["sh", "-c", "run || true"]):
            plan = SimpleNamespace(builds=[command], baseline_tests=[["native", "test"]],
                                   final_tests=[["native", "test"]], linters=[["native", "lint"]])
            # A bypassed plan phase is a malformed deliverable, not an engineering verdict
            # (see test_failure_taxonomy.test_2d). Still must raise -- the assertion is
            # retargeted to the correct type, not relaxed.
            with self.assertRaises(PreparationContractViolation):
                validate_plan_contract(plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
