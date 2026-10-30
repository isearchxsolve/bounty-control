"""Fixtures for the discovery queue: windowing, repository pre-check and ordering.

The 2026-10-27 backlog made a fresh candidate unreachable. ``ORDER BY checked,rowid``
reads oldest-first, so with 3,131 rows waiting a candidate could sit behind roughly
twenty-seven cycles of a 120-row hydration batch; the six-hour re-queue then pushed
refreshed rows behind the same block. ``queue_window`` reads both edges instead.

Two other repairs are pinned here. A repository that carries many pull requests and has
merged none is a farm: 885 of 3,311 queued rows sat in such repositories and each was
re-hydrated every cycle only to be rejected afterwards, so the verdict is now taken once
per repository and its rows are retired permanently. And a repository with measured merge
history deserves the batch ahead of an unknown one, while absence of evidence stays
permissive -- a new project must never be refused on silence.
"""
import json
import sqlite3
import time
import unittest

from actions_dispatch import (
    HYDRATION_BATCH,
    INTENT_REFRESH_S,
    QUEUE_WINDOW,
    REPO_INTENT_RETIRED,
    build_issue_search_queries,
    pending_window,
    preferred_order,
    precheck_repository_intent,
    queue_window,
    repository_of,
)


class FakeAPI:
    """Answers only the GraphQL merge probe that ``merge_evidence`` issues."""

    def __init__(self, table):
        self.table = table
        self.probes = []

    def api(self, endpoint, method="GET", data=None, paginate=False):
        assert endpoint == "graphql", endpoint
        name = "%s/%s" % (data["variables"]["owner"], data["variables"]["name"])
        self.probes.append(name)
        merged, total = self.table[name]
        return {"data": {"repository": {"merged": {"totalCount": merged},
                                        "all": {"totalCount": total}}}}


def payload(repo, number, updated="2026-10-27T00:00:00Z"):
    return json.dumps({"repository_url": "https://api.github.com/repos/%s" % repo,
                       "number": number, "updated_at": updated})


def database():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
                "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending')")
    con.execute("CREATE TABLE repo_intent(repository TEXT PRIMARY KEY, verdict TEXT, "
                "merged INTEGER, total INTEGER, evidence TEXT, probed_at REAL)")
    return con


def add(con, repo, number, status="pending", checked=0.0, updated="2026-10-27T00:00:00Z"):
    task = "%s#%d" % (repo, number)
    con.execute("INSERT INTO pending VALUES(?,?,?,?,?,?)",
                (task, payload(repo, number, updated), json.dumps(["normal"]),
                 updated, checked, status))
    return task


class RepositoryOfTests(unittest.TestCase):
    def test_repository_is_read_from_the_payload(self):
        self.assertEqual(repository_of(payload("Expensify/App", 1)), "Expensify/App")

    def test_a_payload_without_a_repository_url_yields_empty(self):
        self.assertEqual(repository_of(json.dumps({"number": 1})), "")
        self.assertEqual(repository_of(""), "")


class QueueWindowTests(unittest.TestCase):
    def test_a_fresh_candidate_is_reachable_behind_a_large_backlog(self):
        con = database()
        for number in range(QUEUE_WINDOW * 2):
            add(con, "farm/backlog", number)
        fresh = add(con, "fresh/repo", 1, updated="2026-10-27T12:00:00Z")
        con.commit()

        # The behaviour that starved the queue, reproduced exactly.
        oldest_only = {row[0] for row in con.execute(
            "SELECT task_id,payload,lanes,signature,rowid FROM pending WHERE status='pending' "
            "ORDER BY checked,rowid LIMIT ?", (QUEUE_WINDOW,))}
        self.assertNotIn(fresh, oldest_only)

        windowed = {row[0] for row in queue_window(con)}
        self.assertIn(fresh, windowed)

    def test_the_window_never_returns_a_row_twice(self):
        con = database()
        for number in range(10):
            add(con, "small/repo", number)
        con.commit()
        rows = queue_window(con)
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row[0] for row in rows}), 10)

    def test_only_pending_rows_enter_the_window(self):
        con = database()
        add(con, "a/repo", 1, status="checked")
        add(con, "a/repo", 2, status=REPO_INTENT_RETIRED)
        live = add(con, "a/repo", 3)
        con.commit()
        self.assertEqual([row[0] for row in queue_window(con)], [live])

    def test_fresh_search_hit_survives_rows_added_by_later_queries(self):
        con = database()
        for number in range(QUEUE_WINDOW + 100):
            add(con, "backlog/repo", number)
        fresh = add(con, "paid-program/repo", 1, updated="2026-10-27T12:00:00Z")
        # Simulate later global query results pushing the original hit outside both
        # ordinary queue edges before the cycle reaches hydration.
        for number in range(QUEUE_WINDOW + 1000, QUEUE_WINDOW + 1000 + QUEUE_WINDOW):
            add(con, "later-query/repo", number)
        con.commit()

        ordinary = {row[0] for row in queue_window(con)}
        self.assertNotIn(fresh, ordinary)

        prioritized = queue_window(con, priority_ids=[fresh])
        self.assertEqual(prioritized[0][0], fresh)
        self.assertIn(fresh, {row[0] for row in pending_window(prioritized)})

    def test_priority_across_lanes_uses_newest_issue_first(self):
        con = database()
        older = add(con, "normal/repo", 1, updated="2026-10-27T01:00:00Z")
        newer = add(con, "startup/repo", 1, updated="2026-10-28T00:00:00Z")
        con.commit()

        rows = queue_window(con, limit=1, priority_ids=[older, newer])

        self.assertEqual([row[0] for row in rows], [newer])

    def test_measured_111_fresh_hits_lead_the_window_and_leftovers_stay_reachable(self):
        """The 2026-10-28 measured cycle queued 111 fresh hits; the declared batch is 60.

        The starvation defect this file pins is a fresh hit waiting behind the whole
        historical backlog, not behind one cycle. When a cycle queues more fresh hits
        than the API-throttled batch can hydrate, the window spends its entire budget
        on fresh hits first, and the leftovers keep their lead over the backlog so the
        next window drains them before it inspects a single stale row.
        """
        fresh_rows = []
        for number in range(111):
            repo = "fresh-%02d/project" % (number % 7)
            fresh_rows.append(("fresh#%d" % number, payload(repo, number),
                               json.dumps(["normal"]), "2026-10-28T01:12:00Z", number))
        backlog_rows = [("backlog#%d" % number,
                         payload("old-%02d/project" % (number % 100), number),
                         json.dumps(["normal"]), "2026-10-20T00:00:00Z", 1000 + number)
                        for number in range(400)]

        selected = pending_window(fresh_rows + backlog_rows,
                                  priority_ids={row[0] for row in fresh_rows})

        self.assertEqual(HYDRATION_BATCH, 60)
        self.assertEqual(len(selected), HYDRATION_BATCH)
        selected_ids = {row[0] for row in selected}
        fresh_ids = {row[0] for row in fresh_rows}
        self.assertTrue(selected_ids.issubset(fresh_ids))
        self.assertEqual(len(selected_ids & fresh_ids), HYDRATION_BATCH)

        # The 51 unhydrated fresh hits are not buried behind the backlog: the next
        # window hydrates every leftover before it touches a backlog row.
        leftover = [row for row in fresh_rows if row[0] not in selected_ids]
        self.assertEqual(len(leftover), 111 - HYDRATION_BATCH)
        next_selected = pending_window(leftover + backlog_rows,
                                       priority_ids={row[0] for row in leftover})
        self.assertEqual([row[0] for row in next_selected[:len(leftover)]],
                         [row[0] for row in leftover])
        self.assertEqual(len(next_selected), HYDRATION_BATCH)


class PriorityPreferredOrderTests(unittest.TestCase):
    def test_current_cycle_good_repository_hit_stays_ahead_of_newer_backlog(self):
        con = database()
        priority = add(con, "known/repo", 1, updated="2026-10-26T00:00:00Z")
        newer = add(con, "known/repo", 2, updated="2026-10-27T12:00:00Z")
        rows = list(con.execute(
            "SELECT task_id,payload,lanes,signature,rowid FROM pending ORDER BY rowid"))

        ordered = preferred_order(rows, {"known/repo": "OK"}, {priority})
        self.assertEqual([row[0] for row in ordered], [priority, newer])

    def test_fresh_unknown_hit_precedes_stale_known_good_backlog(self):
        con = database()
        stale = add(con, "known/repo", 1, updated="2026-10-01T00:00:00Z")
        fresh = add(con, "new/repo", 1, updated="2026-10-28T00:00:00Z")
        rows = list(con.execute(
            "SELECT task_id,payload,lanes,signature,rowid FROM pending ORDER BY rowid"))

        ordered = preferred_order(rows, {"known/repo": "OK"}, {fresh})

        self.assertEqual([row[0] for row in ordered], [fresh, stale])
        self.assertEqual([row[0] for row in pending_window(ordered)], [fresh, stale])


class PriorityQueryConfigTests(unittest.TestCase):
    def test_paid_program_fast_lane_runs_every_cycle_and_stays_additive(self):
        from actions_dispatch import PRIORITY_DISCOVERY_QUERIES, QUERIES

        self.assertEqual(len(PRIORITY_DISCOVERY_QUERIES), 1)
        query = PRIORITY_DISCOVERY_QUERIES[0]
        self.assertEqual(query, 'repo:Expensify/App label:External label:Bug in:title '
                                 '"$250" -label:"Awaiting Payment" is:issue is:open')
        self.assertIn('repo:', query)
        compiled = build_issue_search_queries(query)[0]
        for qualifier in ['is:issue', 'is:open', 'is:public', 'archived:false',
                          '-linked:pr']:
            self.assertIn(qualifier, compiled)
        # The paid-program query is contributor-open (label:External + approved
        # paid program), so it is deliberately NOT filtered to unassigned-only.
        self.assertNotIn('no:assignee', compiled)
        # Additive: the global lanes keep scanning their own horizons, and the generic
        # title query rotates in the normal lane instead of re-flooding the durable
        # queue on every cycle.
        self.assertIn('bounty in:title', QUERIES['normal'])
        self.assertNotIn('bounty in:title', PRIORITY_DISCOVERY_QUERIES)
        self.assertTrue(any(program.startswith('label:"Status: Available"')
                            for program in QUERIES['programs']))


class PrecheckTests(unittest.TestCase):
    def build(self):
        con = database()
        for number in (1, 2, 3):
            add(con, "farm/repo", number)
        for number in (1, 2):
            add(con, "good/repo", number)
        add(con, "new/repo", 1)
        con.commit()
        api = FakeAPI({"farm/repo": (0, 4458), "good/repo": (333, 863), "new/repo": (0, 3)})
        return con, api

    def test_a_farm_is_measured_once_and_its_rows_are_retired(self):
        con, api = self.build()
        verdicts, probed, retired = precheck_repository_intent(api, con, queue_window(con), {})
        self.assertEqual(probed, 3)
        self.assertEqual(retired, 3)
        self.assertEqual(verdicts["farm/repo"], "REPOSITORY_DOES_NOT_MERGE")
        self.assertEqual(verdicts["good/repo"], "OK")
        remaining = {repository_of(row[1]) for row in queue_window(con)}
        self.assertNotIn("farm/repo", remaining)
        self.assertIn("good/repo", remaining)

    def test_a_repository_without_enough_evidence_is_not_refused(self):
        con, api = self.build()
        verdicts, _, _ = precheck_repository_intent(api, con, queue_window(con), {})
        self.assertEqual(verdicts["new/repo"], "OK")

    def test_the_verdict_survives_in_the_intent_table(self):
        con, api = self.build()
        precheck_repository_intent(api, con, queue_window(con), {})
        stored = {row[0]: (row[1], row[2], row[3]) for row in con.execute(
            "SELECT repository,verdict,merged,total FROM repo_intent")}
        self.assertEqual(stored["farm/repo"], ("REPOSITORY_DOES_NOT_MERGE", 0, 4458))
        self.assertEqual(stored["good/repo"], ("OK", 333, 863))

    def test_a_known_verdict_is_not_probed_again_within_the_week(self):
        con, api = self.build()
        precheck_repository_intent(api, con, queue_window(con), {})
        before = len(api.probes)
        _, probed, _ = precheck_repository_intent(api, con, queue_window(con), {})
        self.assertEqual(probed, 0)
        self.assertEqual(len(api.probes), before)

    def test_a_stale_verdict_is_probed_again(self):
        # Only healthy repositories here: a retired farm leaves the queue, so folding both
        # into one fixture would measure the retirement instead of the refresh.
        con = database()
        add(con, "good/repo", 1)
        add(con, "good/repo", 2)
        add(con, "new/repo", 1)
        con.commit()
        api = FakeAPI({"good/repo": (333, 863), "new/repo": (0, 3)})
        precheck_repository_intent(api, con, queue_window(con), {})
        self.assertEqual(len(api.probes), 2)
        con.execute("UPDATE repo_intent SET probed_at=?", (time.time() - INTENT_REFRESH_S - 60,))
        con.commit()
        _, probed, _ = precheck_repository_intent(api, con, queue_window(con), {})
        self.assertEqual(probed, 2)

    def test_the_probe_budget_is_bounded_and_spends_on_the_largest_share(self):
        con, api = self.build()
        _, probed, _ = precheck_repository_intent(api, con, queue_window(con), {}, limit=1)
        self.assertEqual(probed, 1)
        self.assertEqual(api.probes, ["farm/repo"])

    def test_a_dead_probe_is_never_a_rejection(self):
        class Broken:
            def api(self, *args, **kwargs):
                raise OSError("connection reset")

        con, _ = self.build()
        verdicts, probed, retired = precheck_repository_intent(Broken(), con, queue_window(con), {})
        self.assertEqual(probed, 3)
        self.assertEqual(retired, 0)
        self.assertEqual(verdicts["farm/repo"], "OK")


class PreferredOrderTests(unittest.TestCase):
    def rows(self):
        con = database()
        add(con, "farm/repo", 1)
        add(con, "unknown/repo", 1, updated="2026-10-26T00:00:00Z")
        add(con, "good/repo", 1, updated="2026-10-01T00:00:00Z")
        add(con, "good/repo", 2, updated="2026-10-27T00:00:00Z")
        con.commit()
        return queue_window(con)

    def test_known_good_repositories_lead(self):
        ordered = preferred_order(self.rows(), {"good/repo": "OK"})
        self.assertEqual({repository_of(row[1]) for row in ordered[:2]}, {"good/repo"})

    def test_the_freshest_candidate_leads_inside_a_band(self):
        ordered = preferred_order(self.rows(), {"good/repo": "OK"})
        self.assertEqual(ordered[0][3], "2026-10-27T00:00:00Z")

    def test_a_retired_repository_never_reaches_the_batch(self):
        ordered = preferred_order(self.rows(), {"farm/repo": "REPOSITORY_DOES_NOT_MERGE"})
        self.assertNotIn("farm/repo", {repository_of(row[1]) for row in ordered})

    def test_an_unprobed_repository_stays_in_the_queue(self):
        ordered = preferred_order(self.rows(), {})
        self.assertIn("unknown/repo", {repository_of(row[1]) for row in ordered})

    def test_nothing_is_lost_between_the_bands(self):
        rows = self.rows()
        verdicts = {"good/repo": "OK", "farm/repo": "REPOSITORY_DOES_NOT_MERGE"}
        ordered = preferred_order(rows, verdicts)
        self.assertEqual(len(ordered), len(rows) - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
