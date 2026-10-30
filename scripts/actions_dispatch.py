"""Three global discovery lanes, one admission contract and durable Actions queue."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode
import uuid

from actions_github import GitHub, GitHubError, StateStore, task_id, utcnow
from bounty_admission import admit, competition, NON_WORK, repository_intent, FUNDING_PROGRAMS
from bounty_fx import quote
from discovery_horizon import Horizon
from hardness_score import hardness_score
from urgency_score import urgency_score
from liquidity_score import rank_key as liquidity_rank_key

import search_planner
QUERY_CONFIG = json.loads(Path(__file__).with_name("bounty_queries.json").read_text(encoding="utf-8"))
LANE_PURPOSE = {
    "founder": "Funded founder-stage repos with a paid bounty and a concrete code change.",
    "programs": "Paid bounty programmes (Algora, Polar, Opire and similar) with a reward on the issue.",
    "startup": "Early-stage startup repos that attach a paid bounty to a real code change.",
    "normal": "Ordinary open-source repos with a bounty attached to a reproducible defect or feature.",
}
PRIORITY_DISCOVERY_QUERIES = tuple(QUERY_CONFIG.pop("priority_discovery", ()))
QUERIES = QUERY_CONFIG
SEARCH_QUALIFIERS = (
    "is:issue", "is:open", "is:public", "archived:false",
    "-label:type/experiment", "-label:video-demo",
    "-label:type/not-a-bug", "-label:type/question",
    "-label:not-a-bug", "-label:not-a-defect",
    "-label:invalid", "-label:wontfix",
    "-label:expected-behavior", "-label:by-design",
    "-label:works-as-intended",
    "no:assignee", "-linked:pr",
)
QUERY_POLICY_VERSION = "unassigned-no-closing-pr-no-video-demo-no-not-a-defect-contextual-branches-v5"
QUERY_EXCLUDED_ASSIGNED = "query_excluded_assigned"
QUERY_EXCLUDED_EXPERIMENT = "query_excluded_experiment"
QUERY_EXCLUDED_VIDEO_DEMO = "query_excluded_video_demo"
QUERY_EXCLUDED_NOT_A_DEFECT = "query_excluded_not_a_defect"
SEARCH_QUALIFIER_ATOM = re.compile(r"^-?[A-Za-z][A-Za-z0-9_-]*:")

# Labels a repository's own maintainers attach when the reported behaviour is
# already documented as expected / by design / not a defect. Dispatching an
# engineer to such an issue is a supply-side false positive: the only possible
# delivery outcome is a verified refusal (REJECTED_PREPARATION / blocked) and
# no PR is ever created. These labels gate the search qualifiers below and the
# live query_exclusion_status() check before dispatch.
NOT_A_DEFECT_LABELS = (
    "type/not-a-bug", "type/question",
    "not-a-bug", "not-a-defect", "not a bug", "not a defect",
    "invalid", "wontfix",
    "expected-behavior", "expected behavior",
    "by-design", "by design",
    "works-as-intended", "works as intended",
)


def _search_atoms(expression):
    """Tokenize GitHub search text without splitting quoted phrases or groups."""
    atoms = []
    start = None
    quoted = False
    escaped = False
    depth = 0
    for index, char in enumerate(expression):
        if start is None and not char.isspace():
            start = index
        if char == '"' and not escaped:
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char.isspace() and depth == 0 and start is not None:
                atoms.append(expression[start:index])
                start = None
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    if start is not None:
        atoms.append(expression[start:])
    return atoms


def _is_search_qualifier(atom):
    return bool(SEARCH_QUALIFIER_ATOM.match(atom))


def split_search_or_branches(expression):
    """Expand top-level OR alternatives while preserving shared query context.

    Lane expressions use a common text/qualifier prefix before the first alternative and
    may put common search qualifiers (such as is:issue and is:open) after the last one.
    Distribute that prefix and suffix into every branch. Without this step, splitting
    `label:bounty auth OR permission` silently turns the second query into an unscoped
    search for permission across GitHub.

    GitHub's REST issue-search endpoint changed semantics when a whole expression was
    wrapped in parentheses, so each expanded branch is searched independently instead.
    """
    expression = str(expression or "").strip()
    branches = []
    start = 0
    quoted = False
    escaped = False
    depth = 0
    index = 0
    while index < len(expression):
        char = expression[index]
        if char == '"' and not escaped:
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError("Unbalanced parentheses in GitHub search expression")
            elif (depth == 0 and expression[index:index + 2].upper() == "OR"
                  and (index == 0 or expression[index - 1].isspace())
                  and (index + 2 == len(expression) or expression[index + 2].isspace())):
                branches.append(expression[start:index].strip())
                start = index + 2
                index += 1
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
        index += 1
    if quoted or depth:
        raise ValueError("Unbalanced quote or parentheses in GitHub search expression")
    branches.append(expression[start:].strip())
    if any(not branch for branch in branches):
        raise ValueError("Empty branch in GitHub OR search expression")
    if len(branches) == 1:
        return branches

    first_atoms = _search_atoms(branches[0])
    last_atoms = _search_atoms(branches[-1])
    if not first_atoms or not last_atoms:
        raise ValueError("Missing alternative in GitHub OR search expression")
    if _is_search_qualifier(first_atoms[-1]):
        raise ValueError("Place shared query context before the first OR alternative")

    shared_prefix = first_atoms[:-1]
    suffix_start = len(last_atoms)
    while suffix_start and _is_search_qualifier(last_atoms[suffix_start - 1]):
        suffix_start -= 1
    last_alternative = last_atoms[:suffix_start]
    if not last_alternative:
        raise ValueError("Missing final alternative in GitHub OR search expression")
    shared_suffix = last_atoms[suffix_start:]

    expanded = [" ".join([*shared_prefix, first_atoms[-1], *shared_suffix])]
    for branch in branches[1:-1]:
        atoms = _search_atoms(branch)
        if not atoms:
            raise ValueError("Empty branch in GitHub OR search expression")
        expanded.append(" ".join([*shared_prefix, *atoms, *shared_suffix]))
    expanded.append(" ".join([*shared_prefix, *last_alternative, *shared_suffix]))
    return expanded


def _label_value(atom):
    """Extract the lowercased search-qualifier value after the first ':'.

    Strips surrounding quotes so ``label:"Help Wanted"`` and ``label:External``
    both normalize for matching against contributor-open signals.
    """
    _, _, value = atom.partition(":")
    return value.strip().strip('"').lower()


def _is_contributor_open_expression(expression):
    """True when the expression advertises contributor-open work despite assignees.

    Help Wanted and External labels mark issues the repository wants outside hands
    on, even when a triage bot has auto-assigned them. Approved paid-program
    repositories (FUNDING_PROGRAMS) publish bounties on assigned issues because
    assignment is their triage convention, not a "do not touch" signal.
    """
    atoms = _search_atoms(expression)
    for atom in atoms:
        if atom.lower().startswith("label:"):
            value = _label_value(atom)
            if value == "external" or "help wanted" in value:
                return True
    for atom in atoms:
        if atom.lower().startswith("repo:"):
            repo = atom[len("repo:"):].strip().strip('"').lower()
            if repo in FUNDING_PROGRAMS:
                return True
    return False


def build_issue_search_query(expression, window=None, fresh=0):
    """Compile one GitHub search branch with shared server-side eligibility filters.

    Disjunctions are expanded by ``build_issue_search_queries`` so every branch gets
    these filters before GitHub returns results. GitHub can enforce issue state,
    visibility, archive, assignee and closing-PR relations at search time; predicates
    without GitHub search qualifiers remain in the existing evidence-based admission
    contract.
    """
    expression = str(expression or "").strip()
    if len(split_search_or_branches(expression)) != 1:
        raise ValueError("Compile OR expressions with build_issue_search_queries")
    atoms = _search_atoms(expression)
    contributor_open = _is_contributor_open_expression(expression)
    for qualifier in SEARCH_QUALIFIERS:
        if qualifier == "no:assignee" and contributor_open:
            # Contributor-open work (Help Wanted / External labels, or an approved
            # paid-program repo) is deliberately not filtered to unassigned-only:
            # triage bots auto-assign these issues while still advertising them.
            continue
        if qualifier not in atoms:
            atoms.append(qualifier)
    query = " ".join(atoms)
    if window:
        query += " created:" + Horizon.qualifier(window)
    if fresh:
        query += " updated:>=" + datetime.fromtimestamp(
            time.time() - 7 * 86400, timezone.utc).strftime("%Y-%m-%d")
    return query


def build_issue_search_queries(expression, window=None, fresh=0):
    """Compile one or more queries, applying shared filters to every OR branch."""
    return [build_issue_search_query(branch, window=window, fresh=fresh)
            for branch in split_search_or_branches(expression)]


def has_assignees(item):
    """Read assignment evidence carried by GitHub search results/cache rows."""
    assignees = item.get("assignees")
    if isinstance(assignees, list):
        return bool(assignees)
    return assignees not in (None, "")


def has_label(item, label_name):
    """Read a label name from GitHub search's REST issue representation."""
    labels = item.get("labels")
    if not isinstance(labels, list):
        return False
    return any(
        (label.get("name") if isinstance(label, dict) else label) == label_name
        for label in labels
    )


# F6 reversed 2026-10-29. This threshold used to cut the run to 5400s on a contended
# repository, to bound the preparation race. Expensify/App (141 commits/24h) then
# exhausted every shortened run without producing a receipt -- 93 min (40847696604) and
# 28 min (40852325249) -- because the most contended repository is also the one that takes
# longest to prepare. A mitigation that removes the deliverable cannot bound a race.
# Velocity still orders the queue; it no longer truncates a run.
VELOCITY_CONTENDED_THRESHOLD = 20  # commits on the default branch in the last 24h, reported only
FULL_PREPARATION_BUDGET_SECONDS = 14400


def preparation_budget_seconds(velocity):
    """Return the Cline budget for a candidate.

    Always the full window. ``velocity`` is still accepted because callers pass it and the
    queue ordering uses it, but it never shortens the preparation phase: the preparation
    race is bounded by the baseline ancestry re-check at delivery time, not by starving the
    phase that has to produce the deliverable.
    """
    return FULL_PREPARATION_BUDGET_SECONDS


# Capacity, not preference. Measured 2026-10-29: Expensify/App is 3.3 GB on disk and its own
# `npm run lint` reached ~14 GB RSS on a runner with ~7 GiB of RAM plus 8 GiB of swap, which
# ended two runs at exit 143 with the preparation phase never written. A task we cannot
# prepare is not a task we may claim: the honest answer is to decline it visibly, not to
# dispatch it, exhaust the budget, and file the wreckage. Override with
# BOUNTY_MAX_REPOSITORY_KB when a runner with real memory is available.
CAPACITY_MAX_REPOSITORY_KB = int(os.environ.get("BOUNTY_MAX_REPOSITORY_KB", "750000"))
CAPACITY_UNKNOWN = "capacity_unknown"


def repository_over_capacity(size_kb, limit_kb=None):
    """True when a repository is too large to prepare on this runner.

    ``size_kb`` is GitHub's repository size in kilobytes. ``None`` means unmeasured, and an
    unmeasured repository is never excluded: unknown is not too large, and a probe failure
    must not silently drop a valid target.
    """
    if not isinstance(size_kb, int) or isinstance(size_kb, bool):
        return False
    limit = CAPACITY_MAX_REPOSITORY_KB if limit_kb is None else int(limit_kb)
    return size_kb > limit


def repository_size_kb(api, repo, cache=None):
    """Repository size in kilobytes, cached per cycle. ``None`` when unmeasurable."""
    if cache is not None and repo in cache:
        return cache[repo]
    size = None
    try:
        metadata = api.api("repos/" + repo)
        if isinstance(metadata, dict):
            candidate = metadata.get("size")
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                size = candidate
    except (GitHubError, OSError, ValueError, TypeError):
        size = None
    if cache is not None:
        cache[repo] = size
    return size


def velocity_sort_key(item):
    """Sort ``(identity, candidate)`` pairs quietest-first within a band.

    An unmeasured velocity sorts last and is never treated as zero: comparing ``None`` to an
    ``int`` raised ``TypeError`` and would have aborted a whole dispatch cycle the first time
    one repository's velocity probe failed.
    """
    velocity = item[1].get("velocity_24h")
    if not isinstance(velocity, int) or isinstance(velocity, bool):
        return (1, 0)
    return (0, velocity)


def candidate_priority_key(candidate: dict) -> int:
    """Queue priority: founder(0) programs(1) startup(2) normal(3) other(4).

    Founders lead because the paid-programs lane cannot pay what it promises here: its
    flagship target is ``Expensify/App`` at 3,384,503 KB, which the capacity gate refuses
    outright (measured on run 40898443331 - six of six qualified candidates were that one
    repository and ``dispatched`` was empty). Ranking a lane first whose candidates are
    then discarded starves the queue of everything else. The targeting spec agrees:
    layer 3-4 is the funded founder, layer 1-2 is the programme and the enterprise.
    """
    lanes = set((candidate or {}).get("lanes", ()))
    if "founder" in lanes:
        return 0
    if "programs" in lanes:
        return 1
    if "startup" in lanes:
        return 2
    if "normal" in lanes:
        return 3
    return 4


def liquidity_view(candidate):
    """Map a dispatch candidate onto the fields ``liquidity_score`` reads.

    Only signals this pipeline actually measured are passed through. ``liquidity_score``
    treats an absent field as unmeasured rather than as evidence against the payer, so
    ``company_scale_usd``, ``security_contact`` and ``merges_recent`` are deliberately
    left out: nothing here has read a balance sheet, a SECURITY.md, or a 90-day merge
    window. ``merges_ever``/``prs_total`` are passed because the intent probe measured
    them, and they carry the one penalty that matters -- a repository that takes pull
    requests and merges none has demonstrated it does not pay.
    """
    context = candidate.get("context") or {}
    repository = context.get("repository") or {}
    issue = context.get("issue") or {}
    view = {"repo": context.get("repo"),
            "title": context.get("title") or "",
            "body": context.get("body") or "",
            "flags": [],
            "assignee": issue.get("assignee")}
    owner = repository.get("owner") or {}
    if owner.get("type"):
        view["owner_type"] = owner["type"]
    if issue.get("author_association"):
        view["author_assoc"] = issue["author_association"]
    if isinstance(repository.get("stargazers_count"), int):
        view["stars"] = repository["stargazers_count"]
    pushed = repository.get("pushed_at")
    if pushed:
        try:
            when = datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))
            view["repo_pushed_days"] = max(
                0, int((datetime.now(timezone.utc) - when).total_seconds() // 86400))
        except (TypeError, ValueError):
            pass
    evidence = candidate.get("merge_evidence") or {}
    if isinstance(evidence.get("merged"), int) and isinstance(evidence.get("total"), int):
        view["merges_ever"] = evidence["merged"]
        view["prs_total"] = evidence["total"]
    return view


def hardness_view(candidate):
    """Map a dispatch candidate onto the fields ``hardness_score`` reads.

    The comment count comes from the issue the search returned, and the body is the
    document as fetched for admission, so both are measured rather than assumed. Nothing
    here invents a difficulty label: hardness is the ticket's own vocabulary.
    """
    context = candidate.get("context") or {}
    issue = context.get("issue") or {}
    view = {"title": context.get("title") or issue.get("title") or "",
            "body": context.get("body") or issue.get("body") or "",
            "labels": issue.get("labels") or context.get("labels") or []}
    count = issue.get("comments")
    if isinstance(count, int):
        view["comments_count"] = count
    return view


def urgency_view(candidate):
    """Map a candidate onto the fields :mod:`urgency_score` reads.

    ``age_days`` is supplied from the issue's own ``created_at`` because a dramatic
    complaint written two years ago is not a payer bleeding today, and the scorer must be
    able to discount it. A missing or unparseable timestamp passes ``None``, which the
    scorer treats as unknown - never as fresh.
    """
    context = candidate.get("context") or {}
    issue = context.get("issue") or candidate.get("issue") or {}
    labels = issue.get("labels") or candidate.get("labels") or ()
    age_days = None
    stamp = issue.get("created_at") or candidate.get("created_at")
    if isinstance(stamp, str) and len(stamp) >= 10:
        try:
            created = datetime.strptime(stamp[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_days = max(0, (datetime.now(timezone.utc) - created).days)
        except ValueError:
            age_days = None
    return {
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "labels": labels,
        "age_days": age_days,
    }



EDGE_CAP = 100.0
URGENCY_BONUS = 0.25


def two_edged_score(item):
    """The conjunction Baba named: fundamentally hard AND burning in production.

    Both edges, or it is not our ticket:

    * hard but cold (a volunteer project with a funded ticket open since 2018) - nobody
      answers, because nobody is losing money per hour. Measured: the Google Cast claimant
      has waited since April for a maintainer word.
    * burning but trivial - solved within hours by whoever reads it first, and our moat
      does not protect an easy patch. Measured: bystanders open PRs on funded microG issues
      within 36 hours and land none of them, but on trivial tickets they land.

    The joint term is the minimum of the two normalised edges, so a missing edge cannot be
    compensated by strength in the other. ``URGENCY_BONUS`` then separates the two failures:
    between a hot trivial ticket and a hard dead one, the hot one at least might answer.

    Both scorers cap at ``EDGE_CAP`` so one runaway signal cannot manufacture a match, and a
    calm payer's negative urgency still drags the whole score below zero.
    """
    hard = min(EDGE_CAP, hardness_score(hardness_view(item[1]))[0])
    burning = min(EDGE_CAP, urgency_score(urgency_view(item[1]))[0])
    return min(hard, burning) + URGENCY_BONUS * burning



def candidate_sort_key(item):
    """Band, then the two-edged conjunction, then solvency, then difficulty, then quiet.

    Baba's law, 2026-10-30: a claimant waited since April for a maintainer word on a funded
    microG ticket because the issuing project had no urgency - nobody was losing money per
    hour. Urgency therefore predicts REPLY LATENCY, which is the constraint this funnel
    actually starves on, while solvency predicts whether the payer can pay at all. A payer
    who never answers is worth nothing however rich, so urgency is decided first inside the
    band; solvency is next; difficulty then decides which burning problem we can win.

    The band still dominates: a cold founder issue ranks below a hot one only within its own
    band, never across bands.
    

    The band still dominates: a busy founder issue outranks a quiet normal one. Inside a
    band the payer's ability to pay decides before repository velocity does, because a
    solvent founder with a moderate problem is worth more than an insolvent one with a
    dramatic problem -- the insolvent one cannot pay however loud the issue is. Velocity
    stays as the final tiebreak, so ordering is unchanged for any candidate whose
    liquidity is unmeasured.

    Hardness sits between liquidity and velocity. A payer who cannot pay is worthless
    however terrifying the ticket, so solvency still decides first; but among payers, the
    moat beats silence, because a quiet repository is only a proxy for competition while
    the ticket's own vocabulary is evidence of it.
    """
    return (candidate_priority_key(item[1]),
            -two_edged_score(item),
            -liquidity_rank_key(liquidity_view(item[1]))[0],
            -hardness_score(hardness_view(item[1]))[0],
            velocity_sort_key(item))


def repository_velocity(api, repo, cache=None):
    """Count commits on the default branch in the last 24 hours.

    Cached per cycle to avoid hitting the GitHub search rate limit. Higher = busier repo =
    slower dispatch.

    Returns ``None`` when the velocity could not be measured. It must not return ``0``
    there: ``0`` means "provably quiet", so an API failure would be sorted as the quietest
    repository in its band and attempted first -- the exact opposite of the intent. ``None``
    sorts last and yields the full preparation budget.
    """
    if cache is not None and repo in cache:
        return cache[repo]
    owner, name = repo.split("/", 1)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = None
    # Search returns an exact total in one request. Listing commits caps at one page of 100,
    # which made every busy repository read 100 and rank them all as tied -- useless for
    # exactly the repositories that get dispatched.
    query = urlencode({"q": "repo:" + owner + "/" + name + " committer-date:>" + since,
                       "per_page": 1})
    try:
        result = api.api("search/commits?" + query)
        if isinstance(result, dict) and isinstance(result.get("total_count"), int):
            count = result["total_count"]
        elif isinstance(result, list):
            count = len(result)
    except (GitHubError, OSError, ValueError, TypeError):
        count = None
    if count is None:
        # Fallback: a single page of the commits list, exact only below 100.
        try:
            listed = api.api(f"repos/{owner}/{name}/commits?since={since}&per_page=100")
            if isinstance(listed, list):
                count = len(listed)
        except (GitHubError, OSError, ValueError, TypeError):
            count = None
    if cache is not None:
        cache[repo] = count
    return count


def query_exclusion_status(item):
    """Return a durable queue status for exclusions enforced by GitHub search.

    An assigned issue is still contributor-open when the repository labels it
    Help Wanted: assignment is a triage convention, not a "do not touch" signal.
    """
    if has_assignees(item) and not has_label(item, "Help Wanted"):
        return QUERY_EXCLUDED_ASSIGNED
    if has_label(item, "type/experiment"):
        return QUERY_EXCLUDED_EXPERIMENT
    if has_label(item, "video-demo"):
        return QUERY_EXCLUDED_VIDEO_DEMO
    if has_not_a_defect_label(item):
        return QUERY_EXCLUDED_NOT_A_DEFECT
    return ""


def has_not_a_defect_label(item):
    """True when the live issue carries a maintainer-applied "not a defect" label.

    These labels mean the repository's own maintainers have already classified the
    reported behaviour as expected / by design / invalid / not a bug. Dispatching an
    engineer is a false positive: the only possible delivery outcome is a verified
    refusal and no PR is ever created.
    """
    labels = item.get("labels")
    if not isinstance(labels, list):
        return False
    return any(
        (label.get("name") if isinstance(label, dict) else label) in NOT_A_DEFECT_LABELS
        for label in labels
    )


def refreshed_query_exclusion(context):
    """Reapply server-query exclusions to the live issue before dispatch.

    A search row can become assigned or receive a disqualifying label while it waits in
    the durable queue. Its stale search snapshot must not be enough to start delivery.
    """
    issue = context.get("issue") if isinstance(context, dict) else None
    return query_exclusion_status(issue if isinstance(issue, dict) else {})


def retire_query_excluded_pending(con):
    """Retire cached rows that the current server-side query now excludes.

    The Actions cache can outlive a query-policy deployment. Replaying an old assigned
    issue or an explicitly non-engineering video deliverable would bypass the new GitHub
    query qualifiers, so migrate that cached search evidence when the policy changes.
    """
    retired = Counter()
    for identity, payload in con.execute("SELECT task_id,payload FROM pending").fetchall():
        try:
            item = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        status = query_exclusion_status(item) if isinstance(item, dict) else ""
        if status:
            retired[status] += con.execute(
                "UPDATE pending SET status=? WHERE task_id=?",
                (status, identity)).rowcount
    return dict(retired)


def _query_compiled_window(api, q, fresh=0):
    items = []
    page = 1
    total = None
    while True:
        result = api.api("search/issues?" + urlencode(
            {"q": q, "per_page": min(fresh, 100) if fresh else 100,
             "page": page, "sort": "updated" if fresh else "created", "order": "desc"}))
        if result.get("incomplete_results") or not isinstance(result.get("items"), list):
            raise GitHubError("Search horizon incomplete; cursor retained")
        total = result["total_count"]
        if not fresh and total >= 1000:
            return [], total, True  # Split before spending hydration work on a capped window.
        rows = result["items"]
        items.extend(rows)
        if fresh or not rows or page * 100 >= total:
            return items, total, False
        page += 1


def query_expression_window(api, expression, window=None, fresh=0):
    """Search all OR branches, deduplicate their union, and report saturation."""
    queries = build_issue_search_queries(expression, window=window, fresh=fresh)
    if len(queries) == 1:
        rows, total, saturated = _query_compiled_window(api, queries[0], fresh=fresh)
        return rows, total, saturated, [total]
    merged = {}
    branch_totals = []
    for query in queries:
        rows, total, saturated = _query_compiled_window(api, query, fresh=fresh)
        branch_totals.append(total)
        if saturated:
            return [], sum(branch_totals), True, branch_totals
        for item in rows:
            repository = item.get("repository_url", "")
            number = item.get("number")
            identity = (repository.lower(), number) if repository and number is not None else json.dumps(
                item, sort_keys=True, separators=(",", ":"))
            merged.setdefault(identity, item)
    return list(merged.values()), sum(branch_totals), False, branch_totals


def query_window(api, expression, window=None, fresh=0):
    """Backward-compatible two-value wrapper around branch-aware search."""
    rows, total, _saturated, _branch_totals = query_expression_window(
        api, expression, window=window, fresh=fresh)
    return rows, total


def merge_evidence(api, repo, cache):
    """Measure how many pull requests this repository has merged, once per cycle.

    A bounty is paid on merge, so merge history is the only durable evidence that a
    repository pays outside work. Every issue in the same repository reuses the
    verdict, so the cost tracks the number of repositories that reach candidate
    status rather than the size of the queue.

    This uses GraphQL deliberately. `search/issues` is capped at 30 requests per
    minute for the whole account, and discovery already spends that allowance on its
    own lane queries: the first live run of this gate died at 16:08:56 with
    "API rate limit exceeded" after five lane searches consumed the minute.
    GraphQL draws on the 5,000-point core allowance instead.

    A failed probe records that fact and yields no verdict. It is never a rejection:
    a throttled query says nothing about the repository.
    """
    if repo in cache:
        return cache[repo]
    owner, name = repo.split("/", 1)
    query = ("query($owner:String!,$name:String!){repository(owner:$owner,name:$name){"
             "merged:pullRequests(states:MERGED){totalCount} all:pullRequests{totalCount}}}")
    try:
        result = api.api("graphql", "POST",
                         {"query": query, "variables": {"owner": owner, "name": name}})
        node = (result or {})["data"]["repository"]
        cache[repo] = {"merged": int(node["merged"]["totalCount"]),
                       "total": int(node["all"]["totalCount"])}
    except (GitHubError, OSError, ValueError, KeyError, TypeError) as exc:
        cache[repo] = {"unavailable": str(exc)[:160]}
    return cache[repo]


def context_candidates(api, item, visited=None):
    repo = item["repository_url"].split("/repos/")[-1]
    number = item["number"]
    visited = set(visited or ())
    identity = task_id(repo, number)
    if identity in visited or len(visited) >= 3:
        return
    visited.add(identity)
    context = api.issue_context(repo, number)
    text = context["title"] + "\n" + context["body"]
    if ((NON_WORK.search(context["title"]) and re.search(
            r"original|source|upstream|mirrored|digest|intake", text, re.I))
            or re.search(r"mirrored from|(?:original|source|upstream)\s+issue\s*:|"
                         r"source\s*:\s*https://github\.com/[^\s]+/issues/", text, re.I)):
        for original_repo, original_number in dict.fromkeys(re.findall(
                r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)", text)):
            yield from context_candidates(api, {"repository_url": "https://api.github.com/repos/" + original_repo,
                                                "number": int(original_number)}, visited)
        return
    yield context


def dispatch(api, store, context, proof, lanes, remote_repair=False, preparation_budget=None):
    repo, number = context["repo"], context["issue_number"]
    identity, dispatch_id = task_id(repo, number), uuid.uuid4().hex
    def reserve(old):
        if old:
            status = old.get("status", "")
            retryable = retry_eligible(old) and int(old.get("attempt", 0)) < 3
            if not retryable:
                raise ValueError("Existing durable task state: " + status)
        return {**(old or {}), "task_id": identity, "repo": repo, "issue_number": number,
                "status": "DISPATCHING", "dispatch_id": dispatch_id, "admission": proof,
                "lanes": sorted(set(lanes)), "dispatched_at": utcnow(), "attempt": (old or {}).get("attempt", 0)}
    store.mutate(identity, reserve)
    budget = preparation_budget if isinstance(preparation_budget, int) else FULL_PREPARATION_BUDGET_SECONDS
    payload = {"event_type": "bounty_task_dispatch", "client_payload": {
        "repo": repo, "issue_number": number, "task_id": identity, "lanes": sorted(set(lanes)),
        "mode": "deliver", "preparation_budget_seconds": budget}}
    api.api(f"repos/{store.repo}/dispatches", "POST", payload)
    def acknowledge(old):
        if old and old.get("dispatch_id") == dispatch_id and old["status"] == "DISPATCHING":
            return {**old, "status": "DISPATCHED"}
        if not old:
            raise ValueError("Dispatch state disappeared")
        return old  # A runner can claim before the POST acknowledgement arrives.
    store.mutate(identity, acknowledge)
    return identity


HYDRATION_BATCH = 60
HYDRATION_PER_REPO = 4


def pending_window(rows, limit=HYDRATION_BATCH, per_repo=HYDRATION_PER_REPO, priority_ids=(),
                   excluded_repositories=()):
    """Hydrate current-cycle search hits first, then breadth-first backlog rows.

    GitHub search returns a repository as a unit: one project can publish hundreds
    of matching issues and consume the whole per-cycle hydration budget while every
    unrelated origin waits forever. Selection therefore takes at most ``per_repo``
    backlog sources from each repository first, then fills the rest of the batch from
    leftovers. Fresh query hits already passed the global query contract and lead the
    bounded window, even when a single repository contributes several of them.

    ``excluded_repositories`` drops origins the caller has already measured as
    unpreparable, before their slots are spent rather than after. This is deliberately
    narrower than a per-repository cap on fresh hits: capping the fresh band would push
    backlog rows ahead of current-cycle work whenever fresh hits concentrate in a few
    repositories, which is the starvation ``queue_window`` exists to prevent. An empty
    set (the default) changes nothing, and an unmeasured repository is never in it:
    unknown is not too large.

    ``rows`` are queue tuples whose first three fields are
    ``(task_id, payload, lanes)``, in durable queue order. Extra trailing fields are
    ignored here and read by the caller.
    """
    chosen, counted, rest, seen = [], Counter(), [], set()
    priority = set(priority_ids)
    excluded = {repository.lower() for repository in excluded_repositories}

    def repository_name(row):
        return json.loads(row[1]).get("repository_url", "").split("/repos/")[-1]

    def excluded_row(row):
        return repository_name(row).lower() in excluded

    for row in rows:
        if (row[0] in priority and row[0] not in seen and len(chosen) < limit
                and not excluded_row(row)):
            repository = repository_name(row)
            chosen.append(row)
            counted[repository] += 1
            seen.add(row[0])
    for row in rows:
        if row[0] in seen:
            continue
        repository = repository_name(row)
        if len(chosen) < limit and not excluded_row(row) and counted[repository] < per_repo:
            counted[repository] += 1
            chosen.append(row)
            seen.add(row[0])
        else:
            rest.append(row)
    for row in rest:
        if len(chosen) >= limit:
            break
        if row[0] not in seen and not excluded_row(row):
            chosen.append(row)
            seen.add(row[0])
    return chosen


CAPACITY_PROBE_MAX = 80
CAPACITY_REFRESH_S = 7 * 86400


def capacity_exclusions(api, rows, cache, known=None, limit=CAPACITY_PROBE_MAX):
    """Repositories in this window that this runner cannot prepare.

    The capacity gate already refuses an over-sized repository at dispatch time, which is
    correct but late: by then the cycle has paid for hydration, comment fetches and a full
    admission pass on a task it was never going to dispatch. Measured on run 40898443331,
    six of six qualified candidates were Expensify/App (3,384,503 KB against a 750,000 KB
    ceiling) and ``dispatched`` was empty while every one of them was evaluated in full.

    A repository's size is a property of the repository, not of the cycle, so the verdict is
    taken once and remembered: ``known`` maps repository -> (verdict, probed_at) and only an
    unprobed repository, or one whose verdict is older than ``CAPACITY_REFRESH_S``, costs a
    probe. That keeps the walk bounded without turning every cycle into eighty extra calls.
    ``limit`` bounds the probes in one cycle regardless.

    A repository that cannot be measured is never returned: an unreadable size is not
    evidence of being too large.
    """
    known = known or {}
    stale = time.time() - CAPACITY_REFRESH_S
    probed = 0
    for row in rows:
        repository = repository_of(row[1])
        if not repository or repository in cache:
            continue
        remembered = known.get(repository)
        if remembered and (remembered[1] or 0) >= stale:
            continue
        if probed >= limit:
            break
        repository_size_kb(api, repository, cache)
        probed += 1
    return {repository.lower() for repository, size in cache.items()
            if repository_over_capacity(size)}


INTENT_PRECHECK_MAX = 150
INTENT_REFRESH_S = 7 * 86400
REPO_INTENT_RETIRED = "rejected_repository_intent"
QUEUE_WINDOW = 2000


def repository_of(payload):
    url = (json.loads(payload).get("repository_url") or "") if payload else ""
    return url.split("/repos/")[-1] if "/repos/" in url else ""


def queue_window(con, limit=QUEUE_WINDOW, priority_ids=()):
    """Prioritize current-cycle matches, then read both edges of the backlog.

    ``ORDER BY checked,rowid`` alone made a new candidate unreachable: with 3,131 rows
    waiting and a bounded hydration batch, a candidate discovered this cycle sat behind
    roughly twenty-seven cycles of work at the current batch size, and the six-hour
    re-queue then pushed refreshed rows
    behind the same block. A bounded priority list now keeps fresh query hits in the
    hydration window even when later queries add thousands of rows in the same cycle;
    the remaining capacity still drains both the backlog and newest queue edge.
    """
    rows, seen = [], set()
    select = ("SELECT task_id,payload,lanes,signature,rowid FROM pending "
              "WHERE status='pending' AND task_id=?")
    current_hits = []
    for identity in priority_ids:
        row = con.execute(select, (identity,)).fetchone()
        if row and row[0] not in seen:
            seen.add(row[0])
            current_hits.append(row)
    current_hits.sort(key=lambda row: row[3] or "", reverse=True)
    rows.extend(current_hits[:limit])
    remaining = max(0, limit - len(rows))
    if remaining:
        half = max(1, remaining // 2)
        for query in (
            "SELECT task_id,payload,lanes,signature,rowid FROM pending WHERE status='pending' "
            "ORDER BY checked,rowid LIMIT ?",
            "SELECT task_id,payload,lanes,signature,rowid FROM pending WHERE status='pending' "
            "ORDER BY rowid DESC LIMIT ?",
        ):
            for row in con.execute(query, (half,)):
                if len(rows) >= limit:
                    break
                if row[0] in seen:
                    continue
                seen.add(row[0])
                rows.append(row)
    return rows


def precheck_repository_intent(api, con, rows, cache, limit=INTENT_PRECHECK_MAX):
    """Classify the repositories behind the queue before paying to hydrate them.

    Hydration is the expensive step: it fetches the issue and every comment. On the
    2026-10-27 backlog 885 of 3,311 queued rows sat in repositories that merge nothing,
    and each was re-hydrated on every cycle only to be rejected afterwards. The verdict is
    therefore taken once per repository, remembered in ``repo_intent``, and the rows of a
    rejected repository are retired permanently instead of being re-queued six hours later.

    Only unprobed repositories, or verdicts older than a week, cost a probe, and at most
    ``limit`` repositories are probed per cycle, largest queue share first, so a farm with
    hundreds of rows is classified before an origin that contributed one.
    """
    counts = Counter(repository_of(row[1]) for row in rows)
    counts.pop("", None)
    known = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT repository,verdict,probed_at FROM repo_intent")}
    verdicts = {repo: verdict for repo, (verdict, _) in known.items()}
    stale = time.time() - INTENT_REFRESH_S
    due = [repo for repo, _ in counts.most_common(limit)
           if repo not in known or (known[repo][1] or 0) < stale]
    probed = 0
    for repo in due:
        evidence = merge_evidence(api, repo, cache)
        ok, reason = repository_intent(evidence)
        verdicts[repo] = "OK" if ok else reason
        con.execute("INSERT OR REPLACE INTO repo_intent VALUES(?,?,?,?,?,?)",
                    (repo, verdicts[repo], evidence.get("merged"), evidence.get("total"),
                     json.dumps(evidence)[:400], time.time()))
        probed += 1
    con.commit()
    retired = 0
    for row in rows:
        if verdicts.get(repository_of(row[1])) != "REPOSITORY_DOES_NOT_MERGE":
            continue
        retired += con.execute(
            "UPDATE pending SET status=? WHERE task_id=? AND status='pending'",
            (REPO_INTENT_RETIRED, row[0])).rowcount
    con.commit()
    return verdicts, probed, retired


def preferred_order(rows, verdicts, priority_ids=()):
    """Fresh query hits first, then known-good repositories, with retired farms removed.

    A fresh issue should be hydrated in the cycle that discovered it. Otherwise a large
    backlog of previously checked, known-good repositories can fill the bounded hydration
    window for many cycles and starve current results. Within the fresh band, measured-good
    repositories lead; the historical backlog then keeps the existing good-before-unknown
    order.
    """
    priority_ids = set(priority_ids)
    good, rest = [], []
    for row in rows:
        if verdicts.get(repository_of(row[1])) == "OK":
            good.append(row)
        elif verdicts.get(repository_of(row[1])) != "REPOSITORY_DOES_NOT_MERGE":
            rest.append(row)
    good.sort(key=lambda row: row[3] or "", reverse=True)
    # Keep current-cycle query matches ahead of the historical backlog after repository
    # precheck. Freshness leads; measured-good repositories lead only within that fresh band.
    good_priority = sorted((row for row in good if row[0] in priority_ids),
                           key=lambda row: row[3] or "", reverse=True)
    rest_priority = sorted((row for row in rest if row[0] in priority_ids),
                           key=lambda row: row[3] or "", reverse=True)
    good_rest = [row for row in good if row[0] not in priority_ids]
    rest_other = [row for row in rest if row[0] not in priority_ids]
    return good_priority + rest_priority + good_rest + rest_other


def retry_eligible(state):
    """Only a recorded failure may be dispatched again.

    A verified refusal (``REJECTED_*``) is a terminal engineering outcome: it means the
    engineering phase ran, the contract verified the answer, and the answer was "this is not
    a warranted change". Re-admitting the same issue on the next cycle spends a whole delivery
    run to relearn a verdict already written down.

    Measured 2026-10-27: ``Expensify/App#105153`` was refused as by-design at 17:57 and
    re-dispatched at 18:44 (runs 40555464157 -> 40562829637) purely because the refusal had
    been recorded as ``FAILED_ENGINEER``, which is retryable by design. The same mechanism
    re-queued ``xpex-systems-ai/GXEON-AI#452``.

    ``FAILED_*`` stays retryable: a real fault is worth another attempt, bounded elsewhere.
    ``DISPATCHED`` and ``DISPATCHING`` also stay retryable: a dispatch that was sent to GitHub
    but never produced a PR (e.g., GitHub API transient failure, competition appeared after
    dispatch, or the dispatch was interrupted) should be retried on the next cycle.
    """
    if not state:
        return True
    status = str(state.get("status", ""))
    return status.startswith("FAILED") or status in ("DISPATCHED", "DISPATCHING")


def parse_lanes(value):
    """Split a repo variable such as ``"startup normal"`` into validated lane names.

    ACTIVE_LANES is a repository variable, so a partition is naturally written as more
    than one lane. ``--lane`` used to be an argparse ``choices`` value, which rejected
    the second token outright: the scoped worker died in 41 seconds with
    "unrecognized arguments: normal" before searching anything (run 40855864063).

    Returns every lane for ``all`` or an empty/absent value. Raises ``ValueError`` for a
    name that is not a lane, so a typo fails loudly instead of silently scanning nothing.
    """
    raw = [token for token in re.split(r"[,\s]+", str(value or "").strip()) if token]
    if not raw or "all" in raw:
        return list(QUERIES)
    lanes = []
    for token in raw:
        if token not in QUERIES:
            raise ValueError("unknown lane " + repr(token) + " (expected all, "
                             + ", ".join(QUERIES) + ")")
        if token not in lanes:
            lanes.append(token)
    return lanes


def record_outcome(con, identity, outcome):
    """Latest outcome wins: a refused task that later dispatches is credited as dispatched."""
    con.execute("INSERT OR REPLACE INTO task_outcome VALUES(?,?,?)",
                (identity, outcome, time.time()))


def discover(lanes, max_dispatches=2, live=False, queries_per_lane=2, state_dir=None,
             hydrate_only=False, hydrate_batch=None):
    folder = Path(state_dir or os.environ.get("BOUNTY_STATE_DIR", Path(__file__).resolve().parents[1] / "scratch/actions-discovery"))
    folder.mkdir(parents=True, exist_ok=True)
    api, store = GitHub(), StateStore()
    horizon = Horizon(folder / "horizon.sqlite3")
    con = sqlite3.connect(folder / "discovery.sqlite3", timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS cursors(lane TEXT PRIMARY KEY, position INTEGER)")
    con.execute("CREATE TABLE IF NOT EXISTS candidates(task_id TEXT PRIMARY KEY, payload TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS pending(task_id TEXT PRIMARY KEY, payload TEXT, lanes TEXT, "
                "signature TEXT, checked REAL DEFAULT 0, status TEXT DEFAULT 'pending')")
    con.execute("CREATE TABLE IF NOT EXISTS metadata(name TEXT PRIMARY KEY,value TEXT)")
    # Which search expression surfaced each task. Kept in its own table so the pending schema
    # and every reader of it stay unchanged; it exists so an outcome can be credited back to
    # the query that found the work.
    con.execute("CREATE TABLE IF NOT EXISTS task_expression(task_id TEXT, lane TEXT, "
                "expression TEXT, PRIMARY KEY(task_id, lane, expression))")
    # What each task became, recorded where the pipeline already decides it. Local only: reading
    # the store per task would cost a GitHub API call each, and the rate limit is shared.
    con.execute("CREATE TABLE IF NOT EXISTS task_outcome(task_id TEXT PRIMARY KEY, outcome TEXT, "
                "at REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS repo_intent(repository TEXT PRIMARY KEY, verdict TEXT, "
                "merged INTEGER, total INTEGER, evidence TEXT, probed_at REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS repo_capacity(repository TEXT PRIMARY KEY, size_kb INTEGER, "
                "probed_at REAL)")
    # First-seen timestamp feeds the time-to-first-response metric. CREATE TABLE IF NOT
    # EXISTS cannot add a column to an existing database, so migrate old state dirs
    # explicitly; a missing column is a missing metric, not a reason to lose the queue.
    pending_columns = {row[1] for row in con.execute("PRAGMA table_info(pending)")}
    if "seen_at" not in pending_columns:
        con.execute("ALTER TABLE pending ADD COLUMN seen_at REAL DEFAULT 0")
        con.commit()
        print(json.dumps({"phase": "SCHEMA_MIGRATION", "table": "pending",
                          "added": "seen_at", "backfilled": False}), flush=True)
    batch_size = hydrate_batch if isinstance(hydrate_batch, int) and hydrate_batch > 0 else HYDRATION_BATCH
    policy_material = "\n".join(Path(__file__).with_name(name).read_text(encoding="utf-8-sig")
                                for name in ("bounty_admission.py", "actions_github.py"))
    policy_material += "\nquery-policy=" + QUERY_POLICY_VERSION
    policy_material += "\nquery-qualifiers=" + " ".join(SEARCH_QUALIFIERS)
    policy = hashlib.sha256(policy_material.encode()).hexdigest()
    old_policy = con.execute("SELECT value FROM metadata WHERE name='admission_policy'").fetchone()
    if not old_policy or old_policy[0] != policy:
        # A changed search/admission policy must revisit the cache without letting old
        # search hits bypass a newly pushed-down query filter.
        con.execute("UPDATE pending SET status='pending',checked=0")
        con.execute("DELETE FROM candidates")
        con.execute("INSERT OR REPLACE INTO metadata VALUES('admission_policy',?)", (policy,))
        query_excluded_retired = retire_query_excluded_pending(con)
        con.commit()
        print(json.dumps({"phase": "SEARCH_POLICY_MIGRATION",
                          "version": QUERY_POLICY_VERSION,
                          "qualifiers": list(SEARCH_QUALIFIERS),
                          "query_excluded_cache_rows_retired": query_excluded_retired}), flush=True)
    # A partition means the *queue* is partitioned, not only the queries that fill it.
    # Previously ``lanes`` decided which searches ran, and dispatch then drew from the
    # accumulated pending queue regardless -- so a worker scoped to "startup normal"
    # claimed tasks recorded as ``lanes=['programs']``. Verified live: both accounts
    # claimed the same programs task 2f232cf0..., one of them while configured to
    # exclude that lane entirely.
    active_lanes = set(lanes)
    whole_queues = active_lanes >= set(QUERIES)
    counts = Counter()
    candidates = {}
    intent_cache = {}
    priority_ids = []
    verdicts = {r[0]: r[1] for r in con.execute("SELECT repository,verdict FROM repo_intent")}

    last_search = {}
    nonlocal_context = {"lane": "", "expression": ""}
    def search_and_queue(lane, expression):
        window = horizon.window(expression)
        rows, total, saturated, branch_totals = query_expression_window(api, expression, window)
        recent, fresh_total, _fresh_saturated, fresh_branch_totals = query_expression_window(
            api, expression, fresh=30)
        counts[lane + ".raw"] += len(rows) + len(recent)
        last_search["saturated"] = bool(saturated)
        last_search["returned"] = len(rows) + len(recent)
        queries = build_issue_search_queries(expression, window=window)
        fresh_queries = build_issue_search_queries(expression, fresh=30)
        print(json.dumps({"phase": "SEARCH", "lane": lane, "expression": expression,
                          "query": queries[0] if len(queries) == 1 else queries,
                          "queries": queries,
                          "fresh_query": fresh_queries[0] if len(fresh_queries) == 1 else fresh_queries,
                          "fresh_queries": fresh_queries,
                          "partition": horizon.qualifier(window), "total_count": total,
                          "branch_total_counts": branch_totals,
                          "fresh_total_count": fresh_total,
                          "fresh_branch_total_counts": fresh_branch_totals,
                          "returned": len(rows), "fresh": len(recent),
                          "saturated": saturated}), flush=True)
        # Persist the raw horizon before hydration; bounded work never drops the unprocessed
        # remainder of a search partition.
        # seen_at is written only on a row's first insertion and preserved on refresh, so
        # the time-to-first-response metric measures the wait from the first search hit.
        # The column is guaranteed by the discover() migration even on state dirs created
        # before 2026-10-30; a query returning no column means an unmigrated DB or a
        # direct call, and the metric (not the row) is what degrades gracefully.
        pending_has_seen_at = any(
            row[1] == "seen_at" for row in con.execute("PRAGMA table_info(pending)"))
        for item in [*recent, *rows]:
            repository = item["repository_url"].split("/repos/")[-1]
            identity = task_id(repository, item["number"])
            old = con.execute("SELECT lanes,signature,checked,status,seen_at FROM pending WHERE task_id=?",
                              (identity,)).fetchone()
            lanes_seen = set(json.loads(old[0])) if old else set()
            lanes_seen.add(lane)
            signature = item.get("updated_at", "")
            was_query_excluded = bool(old and str(old[3]).startswith("query_excluded_"))
            pending = (was_query_excluded or not old or old[1] != signature
                       or time.time() - old[2] > 21600)
            status = "pending" if pending else old[3]
            excluded_status = query_exclusion_status(item)
            if excluded_status:
                status = excluded_status
            elif verdicts.get(repository) == "REPOSITORY_DOES_NOT_MERGE":
                status = REPO_INTENT_RETIRED
            first_seen = (old[4] if old and old[4] else time.time()) if old else time.time()
            if nonlocal_context["expression"]:
                con.execute("INSERT OR IGNORE INTO task_expression VALUES(?,?,?)",
                            (identity, nonlocal_context["lane"], nonlocal_context["expression"]))
            if pending_has_seen_at:
                con.execute("INSERT OR REPLACE INTO pending(task_id,payload,lanes,signature,"
                            "checked,status,seen_at) VALUES(?,?,?,?,?,?,?)",
                            (identity, json.dumps(item), json.dumps(sorted(lanes_seen)), signature,
                             old[2] if old else 0, status, first_seen))
            else:
                # Unmigrated direct-call path: keep the durable row, lose only the metric.
                con.execute("INSERT OR REPLACE INTO pending(task_id,payload,lanes,signature,"
                            "checked,status) VALUES(?,?,?,?,?,?)",
                            (identity, json.dumps(item), json.dumps(sorted(lanes_seen)), signature,
                             old[2] if old else 0, status))
        # Give every lane's current-cycle results the same bounded hydration priority.
        # Previously only the dedicated program fast lane populated this list, leaving
        # fresh normal/startup/founder hits behind the accumulated historical backlog.
        for item in recent:
            repository = item["repository_url"].split("/repos/")[-1]
            identity = task_id(repository, item["number"])
            if identity not in priority_ids:
                priority_ids.append(identity)
        con.commit()
        horizon.complete(expression, window, len(rows), 1000, saturated=saturated)

    try:
        # A small, quality-oriented paid-program query runs every cycle so a paying task
        # is never delayed behind the rotating lanes. It is additive: the normal, startup,
        # founder, and rotating program lanes below keep scanning their full horizons, and
        # every lane's fresh hits still enter the bounded hydration priority list inside
        # search_and_queue.
        # Only when the programs lane is actually active: this loop labels every hit it
        # queues as a programs candidate, so an unconditional run put programs-lane rows
        # into a worker that was scoped away from them by construction.
        # A hydration-only lane never spends the search-API budget: discovery's own lane
        # queries already saturate the 30-requests-per-minute search ceiling (measured:
        # 65-second secondary throttle waits), so a second concurrent workflow that ran
        # more searches would only throttle itself. The durable pending queue is the
        # supply; hydration and admission draw on the REST/GraphQL core budget instead.
        if not hydrate_only:
            if "programs" in active_lanes:
                for expression in PRIORITY_DISCOVERY_QUERIES:
                    search_and_queue("programs", expression)
            for lane in lanes:
                # Intelligence layer: the planner chooses the expressions from measured yield
                # and a Nemotron proposal. Any failure falls back to the static round-robin
                # inside plan(), so discovery never stops for lack of intelligence.
                ledger_path = folder / "search_ledger.json"
                ledger = search_planner.load_ledger(ledger_path)
                chosen, audit = search_planner.plan(
                    lane, list(QUERIES[lane]), ledger, slots=queries_per_lane,
                    purpose=LANE_PURPOSE.get(lane, ""),
                    refusal_reasons=[k for k in counts if k.startswith("admission_changed.")
                                     or k.startswith("CURRENT_")],
                    api_key=os.environ.get("NVIDIA_API_KEY", ""))
                print(json.dumps({"phase": "PLANNER", **audit}), flush=True)
                for expression in chosen:
                    nonlocal_context["lane"], nonlocal_context["expression"] = lane, expression
                    search_and_queue(lane, expression)
                    search_planner.record_yield(
                        ledger, lane, expression,
                        returned=last_search.get("returned", 0),
                        saturated=last_search.get("saturated", False))
                search_planner.save_ledger(ledger_path, ledger)
                con.commit()
        if hydrate_only:
            print(json.dumps({"phase": "HYDRATE_ONLY", "queued_total_pending": con.execute(
                "SELECT count(*) FROM pending WHERE status='pending'").fetchone()[0],
                "hydrate_batch": batch_size}), flush=True)
        queued = queue_window(con, priority_ids=priority_ids)
        if not whole_queues:
            queued = [row for row in queued
                      if set(json.loads(row[2])) & active_lanes]
        priority_set = set(priority_ids)
        verdicts, probed_intent, retired = precheck_repository_intent(
            api, con, queued, intent_cache)
        queued = preferred_order(queued, verdicts, priority_ids)
        print(json.dumps({"phase": "REPOSITORY_PRECHECK", "queued": len(queued),
                          "distinct_repositories": len({repository_of(row[1]) for row in queued}),
                          "probed": probed_intent, "retired": retired,
                          "known_good": sum(1 for row in queued
                                            if verdicts.get(repository_of(row[1])) == "OK")}),
              flush=True)
        # Measure capacity before spending hydration, not after. The dispatch gate below
        # stays as the final backstop; this only stops the cycle from paying for a task it
        # has already decided it cannot prepare. Sizes are remembered in repo_capacity so a
        # repository is measured once, not once per cycle.
        known_capacity = {row[0]: (row[1], row[2]) for row in con.execute(
            "SELECT repository,size_kb,probed_at FROM repo_capacity")}
        window_size_cache = {}
        excluded_repositories = capacity_exclusions(api, queued, window_size_cache,
                                                    known=known_capacity)
        for repository, size in window_size_cache.items():
            if size is not None:
                con.execute("INSERT OR REPLACE INTO repo_capacity VALUES(?,?,?)",
                            (repository, size, time.time()))
        con.commit()
        pending_rows = pending_window(queued, limit=batch_size, priority_ids=priority_ids,
                                      excluded_repositories=excluded_repositories)
        print(json.dumps({"phase": "HYDRATION_WINDOW", "queued": len(queued),
                          "selected": len(pending_rows), "hydrate_batch": batch_size,
                          "capacity_excluded_repositories": sorted(excluded_repositories),
                          "current_cycle_hits_queued": sum(row[0] in priority_set for row in queued),
                          "current_cycle_hits_selected": sum(row[0] in priority_set for row in pending_rows),
                          "distinct_repositories": len({json.loads(row[1]).get("repository_url", "")
                                                        for row in pending_rows})}), flush=True)
        # Read the queue row positionally: ``queue_window`` yields
        # (task_id,payload,lanes,signature,rowid) so a freshly discovered source can be
        # recognised at the newest edge, while a window built elsewhere may carry fewer
        # columns. The first three are the durable contract.
        # The time-to-first-response metric: the median minutes a row waited from its
        # first search hit (seen_at) until this cycle gave it its first disposition
        # (checked). A row that was already checked in an earlier cycle is not counted
        # twice.
        first_dispositions = []
        seen_by_id = {row[0]: row[4] for row in con.execute(
            "SELECT task_id,payload,lanes,signature,seen_at,status FROM pending").fetchall()}
        for row in pending_rows:
            source_id, payload, lane_json = row[0], row[1], row[2]
            item, source_lanes = json.loads(payload), json.loads(lane_json)
            try:
                for context in context_candidates(api, item):
                    identity = task_id(context["repo"], context["issue_number"])
                    proof, reason = admit(context, quote=quote)
                    if not proof:
                        counts[reason] += 1
                        offer_band, offer_usd = None, None
                        if reason == "CURRENT_ISSUER_OFFER_MISSING":
                            # Classify the missing-offer band with a floor-zero probe of
                            # the exact same admission contract: if the issue admits at
                            # floor 0 it carries a trusted offer priced below the live
                            # floor (the amount is measurable), and if it still refuses
                            # there is no trusted offer text at all and no floor could
                            # convert it. A second admit() on the in-memory context
                            # costs no API calls.
                            probed, _ = admit(context, quote=quote, floor=Decimal("0"))
                            if probed:
                                offer_band, offer_usd = "OFFER_BELOW_FLOOR", probed["funding"]["usd_value"]
                            else:
                                offer_band = "NO_TRUSTED_OFFER"
                        first_seen = seen_by_id.get(source_id) or 0
                        if first_seen:
                            first_dispositions.append((time.time() - first_seen) / 60.0)
                        print(json.dumps({"phase": "ADMISSION", "repo": context["repo"], "issue_number": context["issue_number"],
                                          "reason": reason, "offer_band": offer_band, "offer_usd": offer_usd,
                                          "reported_comments": context["issue"].get("comments"),
                                          "visible_comments": len(context["comments"])}), flush=True)
                        continue
                    issue_labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in context["issue"].get("labels", [])]
                    is_code, code_reason = is_code_change_request(
                        context["issue"].get("title", ""),
                        context["issue"].get("body", "") or "",
                        issue_labels,
                    )
                    if not is_code:
                        counts[code_reason] += 1
                        first_seen = seen_by_id.get(source_id) or 0
                        if first_seen:
                            first_dispositions.append((time.time() - first_seen) / 60.0)
                        print(json.dumps({"phase": "ADMISSION", "repo": context["repo"], "issue_number": context["issue_number"],
                                          "reason": code_reason}), flush=True)
                        continue
                    merge_ok, merge_reason = repository_intent(
                        merge_evidence(api, context["repo"], intent_cache))
                    if not merge_ok:
                        counts[merge_reason] += 1
                        first_seen = seen_by_id.get(source_id) or 0
                        if first_seen:
                            first_dispositions.append((time.time() - first_seen) / 60.0)
                        print(json.dumps({"phase": "REPOSITORY_INTENT", "repo": context["repo"],
                                          "issue_number": context["issue_number"], "reason": merge_reason,
                                          "evidence": intent_cache.get(context["repo"])}), flush=True)
                        continue
                    competition(api, context["repo"], context["issue_number"])
                    first_seen = seen_by_id.get(source_id) or 0
                    if first_seen:
                        first_dispositions.append((time.time() - first_seen) / 60.0)
                    candidates.setdefault(identity, {"context": context, "proof": proof, "lanes": set(),
                                                      "merge_evidence": intent_cache.get(context["repo"])})["lanes"].update(source_lanes)
                    counts["qualified"] += 1
                con.execute("UPDATE pending SET checked=?,status='checked' WHERE task_id=?", (time.time(), source_id))
            except (GitHubError, OSError, ValueError, KeyError) as exc:
                counts["unknown_or_competing"] += 1
                print(json.dumps({"phase": "ADMISSION_DIAGNOSTIC", "source": source_id, "error": str(exc)}), flush=True)
                # Transport failures stay pending; competition may change next refresh.
                if isinstance(exc, ValueError):
                    con.execute("UPDATE pending SET checked=?,status='checked' WHERE task_id=?", (time.time(), source_id))
            con.commit()
        for identity, candidate in candidates.items():
            serializable = {**candidate, "lanes": sorted(candidate["lanes"])}
            con.execute("INSERT OR REPLACE INTO candidates VALUES(?,?,?)",
                        (identity, json.dumps(serializable), utcnow()))
        con.commit()
        fresh_count = len(candidates)
        for identity, payload in con.execute("SELECT task_id,payload FROM candidates ORDER BY updated_at LIMIT 100"):
            if identity not in candidates:
                saved = json.loads(payload)
                saved["lanes"] = set(saved["lanes"])
                candidates[identity] = saved
        dispatched = []
        capacity_excluded = []
        if live:
            runs = api.api(f"repos/{store.repo}/actions/runs?per_page=100")["workflow_runs"]
            active = sum(r["status"] != "completed" and r.get("path", "").endswith("engine2.yml") for r in runs)
            headroom = max(0, 4 - active)
            # F6: measure velocity per repo; queue by priority band, then quietest first
            # inside the band. The hydration-only lane runs on the REST/GraphQL core
            # budget and never touches the search API, so it cannot probe commit-search
            # velocity: those candidates sort by band then liquidity with velocity
            # unmeasured, which per the sort contract is not treated as zero.
            velocity_cache = {}
            size_cache = {}
            for identity, candidate in candidates.items():
                repo = candidate["context"]["repo"]
                candidate["size_kb"] = repository_size_kb(api, repo, size_cache)
                if not hydrate_only:
                    candidate["velocity_24h"] = repository_velocity(api, repo, velocity_cache)
                # hydrate-only runs never measure velocity (they run on the REST/GraphQL
                # core budget, not the search API), so this must read through .get. Direct
                # indexing raised KeyError('velocity_24h') the moment the drainer finally had
                # candidates to drain - see test_hydrate_only_path.py for the full account.
                candidate["preparation_budget_seconds"] = preparation_budget_seconds(
                    candidate.get("velocity_24h"))
            candidates = dict(sorted(candidates.items(), key=candidate_sort_key))
            for identity, candidate in candidates.items():
                if len(dispatched) >= min(max_dispatches, headroom):
                    break
                if repository_over_capacity(candidate.get("size_kb")):
                    # Visible refusal, not a silent skip: the census has to show that we
                    # declined a task for capacity rather than losing it. The candidate row
                    # is deleted as well: hydration now excludes such a repository before
                    # spending slots, so keeping it would re-evaluate it every cycle and let
                    # a persistent over-sized backlog mask an empty funnel. Measured on run
                    # 40904337220, all 14 saved candidates were the same Expensify/App task.
                    repo = candidate["context"]["repo"]
                    if repo not in capacity_excluded:
                        capacity_excluded.append(repo)
                    counts["CAPACITY_EXCLUDED"] += 1
                    record_outcome(con, identity, "refused")
                    con.execute("DELETE FROM candidates WHERE task_id=?", (identity,))
                    con.commit()
                    print(json.dumps({"phase": "CAPACITY_EXCLUDED", "task_id": identity,
                                      "repo": repo, "size_kb": candidate.get("size_kb"),
                                      "limit_kb": CAPACITY_MAX_REPOSITORY_KB,
                                      "reason": "repository too large to prepare on the "
                                                "runner's memory; needs a bigger runner or "
                                                "a narrower task"}), flush=True)
                    continue
                if not whole_queues and not (set(candidate.get("lanes", ())) & active_lanes):
                    # Durable candidate rows outlive the cycle that found them, so the
                    # lane check is repeated here and not only at the queue edge.
                    counts["out_of_lane_candidate"] += 1
                    continue
                try:
                    state, _ = store.read(identity)
                    if not retry_eligible(state):
                        # A written verdict is retired from the candidate table, not just skipped.
                        # Skipping alone left the row in place, so every cycle re-read the same
                        # tombstone and reported it as qualified supply: run 41029772339 showed
                        # qualified_unique 2 with dispatched [] because both rows were already
                        # REJECTED_PREPARATION. The verdict itself is still preserved in the store.
                        if str(state.get("status", "")).startswith("REJECTED_"):
                            counts["terminal_refusal"] += 1
                            record_outcome(con, identity, "refused")
                            con.execute("DELETE FROM candidates WHERE task_id=?", (identity,))
                            con.commit()
                        else:
                            counts["already_owned"] += 1
                        continue
                    current = api.issue_context(candidate["context"]["repo"], candidate["context"]["issue_number"])
                    query_exclusion = refreshed_query_exclusion(current)
                    if query_exclusion:
                        con.execute("UPDATE pending SET checked=?,status=? WHERE task_id=?",
                                    (time.time(), query_exclusion, identity))
                        con.execute("DELETE FROM candidates WHERE task_id=?", (identity,))
                        con.commit()
                        counts["CURRENT_" + query_exclusion.upper()] += 1
                        record_outcome(con, identity, "refused")
                        continue
                    proof, reason = admit(current, quote=quote)
                    if not proof:
                        con.execute("DELETE FROM candidates WHERE task_id=?", (identity,))
                        con.commit()
                        counts["admission_changed." + reason] += 1
                        record_outcome(con, identity, "refused")
                        continue
                    current_labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in current["issue"].get("labels", [])]
                    is_code, code_reason = is_code_change_request(
                        current["issue"].get("title", ""),
                        current["issue"].get("body", "") or "",
                        current_labels,
                    )
                    if not is_code:
                        con.execute("DELETE FROM candidates WHERE task_id=?", (identity,))
                        con.commit()
                        counts["admission_changed." + code_reason] += 1
                        record_outcome(con, identity, "refused")
                        continue
                    competition(api, current["repo"], current["issue_number"], own_head=(state or {}).get("head_sha"))
                    dispatched.append(dispatch(api, store, current, proof, candidate["lanes"],
                                              preparation_budget=candidate.get("preparation_budget_seconds")))
                    record_outcome(con, identity, "dispatched")
                except (ValueError, GitHubError) as exc:
                    counts["dispatch_deferred"] += 1
                    print(json.dumps({"phase": "DISPATCH_DIAGNOSTIC", "task_id": identity, "error": str(exc)}), flush=True)
        # Credit every expression with what its tasks became. Pure local joins: no API calls.
        # Recomputed from the durable tables each run, so nothing is double-counted.
        ledger = search_planner.load_ledger(folder / "search_ledger.json")
        search_planner.attribute(con, ledger)
        search_planner.save_ledger(folder / "search_ledger.json", ledger)
        if first_dispositions:
            ordered = sorted(first_dispositions)
            median_minutes = ordered[len(ordered) // 2]
        else:
            median_minutes = None
        summary = {"at": utcnow(), "mode": "LIVE" if live else "READ_ONLY", "counts": dict(counts),
                   # F6: the ordering is auditable after the fact, not inferred from logs.
                   "candidate_velocity": {identity: candidate.get("velocity_24h")
                                          for identity, candidate in candidates.items()},
                   "candidate_size_kb": {identity: candidate.get("size_kb")
                                         for identity, candidate in candidates.items()},
                   "capacity_excluded_repositories": capacity_excluded,
                   "qualified_fresh": fresh_count, "qualified_unique": len(candidates), "dispatched": dispatched,
                   "first_response_minutes_median": median_minutes,
                   "first_response_samples": len(first_dispositions),
                   "pending_hydration": con.execute("SELECT count(*) FROM pending WHERE status='pending'").fetchone()[0]}
        with (folder / "receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\n")
        print(json.dumps(summary), flush=True)

        # F11: Refusal census - write census file with refusal counts by reason
        census = {
            "at": summary["at"],
            "mode": summary["mode"],
            "refusals": {k: v for k, v in counts.items() if k.startswith("admission_changed.") or k.startswith("CURRENT_") or k in ("QUERY_EXCLUDED_ASSIGNED", "QUERY_EXCLUDED_EXPERIMENT", "QUERY_EXCLUDED_VIDEO_DEMO", "QUERY_EXCLUDED_NOT_A_DEFECT")},
            "qualified": counts.get("qualified", 0),
            "dispatched": len(dispatched),
        }
        census_path = folder / "census.jsonl"
        with census_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(census) + "\n")
        return summary
    finally:
        con.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", default="all",
                        help="comma/space separated lane names, or all (default: all)")
    parser.add_argument("--live", "--dispatch", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=180)
    parser.add_argument("--max-dispatches", "--max", type=int, default=2)
    parser.add_argument("--queries-per-lane", type=int, default=2)
    parser.add_argument("--hydrate-only", action="store_true",
                        help="skip the search-API lanes and drain the durable pending "
                             "queue on the REST/GraphQL core budget only")
    parser.add_argument("--hydrate-batch", type=int, default=None,
                        help="override HYDRATION_BATCH for this run (hydrate lane)")
    parser.add_argument("--state-dir")
    args = parser.parse_args(argv)
    try:
        lanes = parse_lanes(args.lane)
    except ValueError as exc:
        parser.error(str(exc))
    while True:
        discover(lanes, args.max_dispatches, args.live, args.queries_per_lane, args.state_dir,
                 hydrate_only=args.hydrate_only, hydrate_batch=args.hydrate_batch)
        if not args.daemon or args.once:
            return
        time.sleep(max(30, args.interval))


# ---------------------------------------------------------------------------
# F9 — Class-level admission gate: "does this request a repository code change?"
# ---------------------------------------------------------------------------

_EXTERNAL_TITLE_PATTERNS = (
    r"escrow", r"pago\s+garantizado", r"payment\s+guaranteed",
    r"view\s+link", r"ver\s+enlace", r"off.repo", r"third.?party",
)
_EXTERNAL_BODY_PATTERNS = (
    r"escrow", r"pago\s+garantizado", r"payment\s+guaranteed",
    r"view\s+link", r"ver\s+enlace", r"off.repo", r"icon\s+extraction",
    r"graphic\s+asset", r"art\s+asset", r"bounty\s+bot", r"escrow\s+bot",
)
_EXTERNAL_LABELS = frozenset({"escrow", "escrow-bot", "payment-link"})

_PROCESS_TITLE_PATTERNS = (
    r"triage\s+board", r"availability\s+inquiry", r"bounty\s+availability",
    r"meta\s+checklist", r"meta\s+issue", r"roadmap\s+tracking",
    r"research\s+manifesto", r"pilot\b",
)
_PROCESS_BODY_PATTERNS = (
    r"triage\s+board", r"availability\s+inquiry", r"bounty\s+availability",
    r"meta\s+checklist", r"roadmap\s+tracking", r"research\s+manifesto",
    r"pilot\b", r"bounty\s+harness", r"finish\s+pass",
)
_PROCESS_LABELS = frozenset({"triage", "process", "meta", "roadmap", "pilot"})

# F9 refusal classes. Each gate exists because a measured Cline preparation refusal named the
# class, and each was scored against the 45 hand-labelled needs_code_change items before being
# added: zero false negatives, or it does not ship. Measurement and the gates that were rejected
# are in docs/FUNNEL-REPAIR-PLAN-2026-10-30.md section R2.0.
_AUTO_DIGEST_TITLE = r"^\[[^\]]{0,40}\]\s*\d{4}-\d{2}-\d{2}\b"
_AUTO_DIGEST_LABELS = frozenset({"daily", "digest", "auto-generated", "automated"})
_QUESTION_TITLE = (
    r"^(?:may\s+i\s+know|are\s+there\s+any\s+plans|when\s+(?:will|is|does)|"
    r"how\s+(?:do|can)\s+i|can\s+you\s+tell|is\s+it\s+possible|"
    r"(?:contact|support|general)\s+question)\b"
)
_REPRO_EVIDENCE = (
    r"\b(?:steps\s+to\s+reproduce|expected\s+(?:behaviou?r|result)|"
    r"actual\s+(?:behaviou?r|result)|stack\s*trace|traceback)\b"
)
_UMBRELLA_LABELS = frozenset({"epic", "rfc", "discussion", "feature request", "proposal"})
# A named consumer part is hardware this runner cannot be given: the acceptance for such a
# bounty is a benchmark on that physical card, so no patch prepared here can satisfy it.
_HARDWARE_PRODUCT = (
    r"(?:intel\s+arc|radeon|geforce|ryzen|apple\s+m\d|"
    r"rtx\s*\d{4}|gtx\s*\d{3,4}|arc\s+[abc]\d{3})"
)
_VIDEO_DELIVERABLE = r"\b(?:film|shoot|record|produce)\s+(?:a\s+)?(?:real\s+)?(?:demo|video)\b"

_CODE_TITLE_KEYWORDS = frozenset({
    "bug", "fix", "feature", "implement", "refactor", "security", "cors",
    "auth", "middleware", "endpoint", "parser", "ratelimit", "test",
    "dependency", "patch", "resolve", "fixes", "closes",
})
_CODE_BODY_KEYWORDS = frozenset({
    "bug", "fix", "feature", "implement", "refactor", "security", "cors",
    "auth", "middleware", "endpoint", "parser", "ratelimit", "test",
    "dependency", "patch", "resolve", "closes", "file:", "current code",
    "expected behavior", "actual behavior",
})
_CODE_FILE_EXTENSIONS = frozenset({
    "py", "js", "ts", "go", "rs", "java", "rb", "php", "cs", "swift",
    "kt", "cpp", "c", "h", "hpp", "sol", "hy", "vue", "svelte", "dart",
    "rlib", "wasm",
})
_CODE_PATH_PATTERNS = (
    r"/src/", r"/app/", r"/lib/", r"/pkg/", r"/cmd/", r"/routes/",
    r"/models/", r"/contracts/", r"/middleware/", r"/api/",
)


def _title_matches_any(title: str, patterns: tuple) -> bool:
    import re as _re
    return any(_re.search(p, title) for p in patterns)


def _body_matches_any(body: str, patterns: tuple) -> bool:
    import re as _re
    return any(_re.search(p, body) for p in patterns)


def _label_set(labels: list) -> frozenset:
    return frozenset(str(l).lower() for l in (labels or []))


def _has_code_reference(text: str) -> bool:
    import re as _re
    for ext in _CODE_FILE_EXTENSIONS:
        if _re.search(r"\." + ext + r"\b", text):
            return True
    for pat in _CODE_PATH_PATTERNS:
        if _re.search(pat, text):
            return True
    return False


def is_code_change_request(title: str, body: str, labels: list) -> tuple:
    """Classify whether an issue requests a repository code change.

    Returns (True, "needs_code_change") or (True, "unclear_fail_open") to
    admit the issue to the engineering pipeline.

    Returns (False, "REFUSED_NOT_A_CODE_CHANGE: <reason>") to refuse the
    issue — only when external or process intent is established with high
    confidence.

    Fail-open policy: anything that cannot be confidently classified as
    external or process is admitted.
    """
    title_l = (title or "").lower()
    body_l = (body or "").lower()
    labels_set = _label_set(labels)

    # --- 1. EXTERNAL: refuse with high confidence --------------------------
    external_title = _title_matches_any(title_l, _EXTERNAL_TITLE_PATTERNS)
    external_body = _body_matches_any(body_l, _EXTERNAL_BODY_PATTERNS)
    external_labels = bool(labels_set & _EXTERNAL_LABELS)

    if external_title or external_body or external_labels:
        code_labels = labels_set & {
            "bug", "enhancement", "feature", "security", "good first issue",
            "help wanted", "type/bug", "type/feature",
        }
        if not code_labels:
            reason = "external"
            if external_title:
                reason += ": title matches external patterns"
            elif external_body:
                reason += ": body matches external patterns"
            else:
                reason += ": label matches external patterns"
            return (False, "REFUSED_NOT_A_CODE_CHANGE: " + reason)

    # --- 2. PROCESS: refuse with high confidence ---------------------------
    process_title = _title_matches_any(title_l, _PROCESS_TITLE_PATTERNS)
    process_body = _body_matches_any(body_l, _PROCESS_BODY_PATTERNS)
    process_labels = bool(labels_set & _PROCESS_LABELS)

    if process_title or process_body or process_labels:
        code_keywords = (
            _CODE_TITLE_KEYWORDS & set(title_l.split())
            | _CODE_BODY_KEYWORDS & set(body_l.split())
        )
        if not code_keywords and not _has_code_reference(body_l):
            reason = "process"
            if process_title:
                reason += ": title matches process patterns"
            elif process_body:
                reason += ": body matches process patterns"
            else:
                reason += ": label matches process patterns"
            return (False, "REFUSED_NOT_A_CODE_CHANGE: " + reason)

    # --- 2b. REFUSAL CLASSES (measured 2026-10-30) ------------------------
    # These run after PROCESS so nothing already refused changes behaviour, and before CODE
    # CHANGE because a digest or an advertisement is full of code-ish words that would otherwise
    # admit it. Every branch returns a fixed string: the caller counts the whole reason as a
    # summary key, so interpolating issue text here would explode the counter space.
    if (re.search(_AUTO_DIGEST_TITLE, title_l)
            and labels_set & _AUTO_DIGEST_LABELS
            and not _has_code_reference(body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: auto_digest: dated title plus digest label")

    # An interrogative title with no reproduction evidence anywhere in the body. The repro guard
    # is what keeps a real bug filed as a question admitted.
    if (re.search(_QUESTION_TITLE, title_l)
            and not re.search(_REPRO_EVIDENCE, body_l)
            and not _has_code_reference(body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: question_without_defect: interrogative title, no repro")

    # A maintainer-labelled EPIC/RFC is a multi-issue intention, not a task one runner prepares.
    if labels_set & _UMBRELLA_LABELS and not _has_code_reference(body_l):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: umbrella_request: epic/rfc label, no code reference")

    repro_evidence = bool(re.search(_REPRO_EVIDENCE, body_l))
    if not repro_evidence and (re.search(_HARDWARE_PRODUCT, title_l)
                               or re.search(_HARDWARE_PRODUCT, body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: hardware_product: acceptance needs a physical part")
    # No reproduction guard here, deliberately: the measured case carries "steps to reproduce"
    # only in the repository's issue-template footer, so the guard read boilerplate as evidence.
    # The phrase "film a real demo" is decisive on its own and refuses nothing in the 45-sample.
    if (re.search(_VIDEO_DELIVERABLE, title_l)
            or re.search(_VIDEO_DELIVERABLE, body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: video_deliverable: deliverable is not source code")

    # --- 2c. NON-CODE DELIVERABLE (measured 2026-10-30) -------------------
    # Two live dispatches reached the engineer and were refused there as content and design work:
    # better-feedback/better-commons#3 ("Content bounty: ...") and ProjectWyvern/frontends#1
    # ("Concept design: ..."). Neither matched an external, process or code pattern, so the
    # fail-open tail admitted them and each one spent a claim and a checkout. A deliverable whose
    # title names copy, a mockup or a design artefact, with no code label, no reproduction and no
    # code reference, is refused here. "docs" and "documentation" are deliberately NOT in this
    # list: a documentation fix can be a real code change.
    non_code_title = re.search(
        "(?<![a-z])(?:content bounty|concept design|design (?:a|the|an|set of|mockups?)|"
        "mockups?|wireframes?|logo design|blog posts?|whitepaper|pitch deck|"
        "marketing (?:campaign|copy)|copywriting|tutorial video)(?![a-z])", title_l)
    if (non_code_title
            and not (labels_set & {"bug", "enhancement", "feature", "security", "type/bug",
                                   "type/feature", "good first issue", "help wanted"})
            and not _has_code_reference(body_l)
            and not re.search(_REPRO_EVIDENCE, body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: non_code_deliverable: title names copy, design "
                       "or media, no code label, no reproduction, no code reference")

    # --- 3. CODE CHANGE: admit --------------------------------------------
    # Code labels alone are insufficient - they can be applied to anything.
    # Require at least one code keyword in title/body OR a code file reference.
    has_code_keywords = bool(
        _CODE_TITLE_KEYWORDS & set(title_l.split())
        | _CODE_BODY_KEYWORDS & set(body_l.split())
    )
    has_code_ref = _has_code_reference(body_l)

    if has_code_keywords or has_code_ref:
        return (True, "needs_code_change")

    # --- 4. FAIL-OPEN: admit anything ambiguous ----------------------------
    return (True, "unclear_fail_open")

if __name__ == "__main__":
    main()
