"""Observe actual Actions/PR status and queue bounded repairs of owned work."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from actions_github import BOUNTY_ACCOUNT, GitHub, GitHubError, StateStore, utcnow

ACTIVE_STATUSES = ("CLAIMED", "ENGINEERING", "VERIFIED", "PUBLISHING")
# Statuses where a PR exists and is still ours to observe. This is the set the reconcile loop
# reads GitHub for, so a status missing here is a status that never gets looked at again.
#
# Measured 2026-11-01, on this file's own previous commit: adding CHECKS_HELD_FOR_APPROVAL and
# CHANGES_REQUESTED without adding them here made both terminal by omission. A PR whose CI was
# held, or that a reviewer asked to change, was written once and then never observed -- so it
# could not progress, and could not even be seen to be stuck. The dead ends this repair set out
# to close were reopened by the repair itself. Every status this loop can write back must be in
# this tuple, and test_pipeline_repairs asserts that.
PR_OBSERVATION_STATUSES = ("PUBLISHED_PENDING_CHECKS", "AWAITING_REVIEW", "FAILED_REMOTE_CHECKS",
                           "CHECKS_HELD_FOR_APPROVAL", "CHANGES_REQUESTED")
# engine2.yml runs the engineering job with timeout-minutes: 330. This must match that
# number: at 300*60 the sweeper cancelled runs GitHub still considered legal, so the
# recovery sweep could kill a job five hours in that had twenty-five more minutes.
DEFAULT_JOB_TIMEOUT_SECONDS = 330 * 60
SWEEP_GRACE_SECONDS = 300


def _release(store, record, status, diagnostic, **fields):
    """Move a task out of an active status, refusing to overwrite a concurrent change."""
    identity = record["task_id"]
    expected = record.get("updated_at")

    def update(old):
        if not old or old.get("updated_at") != expected:
            raise ValueError("Concurrent state change; sweep deferred")
        return {**old, **fields, "status": status, "diagnostic": diagnostic,
                "owner_revoked": record.get("owner"),
                "observed_at": utcnow()}

    state = store.mutate(identity, update)
    return {"task_id": identity, "previous": record.get("status"), "status": state["status"],
            "swept": bool(fields.get("swept")), "at": utcnow()}


def sweep_stale_runs(api, store, job_timeout_seconds=None, cancel_wait_seconds=5, records=None):
    """F5: release tasks whose owning run has outlived its own job window.

    A record is swept only on proof, never on absence of life:

    * the owner must parse as a real run id -- a missing or malformed owner is written
      ``FAILED_MISSING_TERMINAL_RECEIPT`` with a diagnostic instead of guessed at;
    * the run must still be ``in_progress`` (a completed run belongs to the existing
      reconciliation branch) and must have outlived ``job_timeout + grace``;
    * the run is cancelled through the API and the cancellation is awaited, then the task
      is written ``FAILED_RUNNER_SHUTDOWN`` with ``swept: true``.

    ``attempt`` is deliberately untouched: the selector is never widened to accept
    ``CLAIMED``, so a sweep makes a task retryable through the ordinary bounded budget and
    a flapping run cannot loop forever.
    """
    timeout = DEFAULT_JOB_TIMEOUT_SECONDS if job_timeout_seconds is None else int(job_timeout_seconds)
    limit = timeout + SWEEP_GRACE_SECONDS
    receipts = []
    for record in (store.records() if records is None else records) or ():
        try:
            if record.get("status") not in ACTIVE_STATUSES:
                continue
            run_id = str(record.get("owner") or "").split(":")[0]
            if not run_id.isdigit():
                receipts.append(_release(
                    store, record, "FAILED_MISSING_TERMINAL_RECEIPT",
                    "Claim owner is missing or malformed; refusing to guess a run", swept=False))
                continue
            try:
                run = api.api(f"repos/{store.repo}/actions/runs/{run_id}")
            except GitHubError:
                continue  # unknown is never proof of death
            if run.get("status") == "completed":
                continue  # the existing completed-run branch owns this case
            started = record.get("claimed_at") or run.get("run_started_at")
            if not started:
                started = record.get("claimed_at")
            if not started:
                continue  # no clock to measure: refuse to guess an age
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(str(started).replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                continue
            if age <= limit:
                continue
            try:
                api.api(f"repos/{store.repo}/actions/runs/{run_id}/cancel", "POST", {})
            except GitHubError:
                print(json.dumps({"phase": "CANCELLATION_UNCONFIRMED", "task_id": record["task_id"]}), flush=True)
                continue
            confirmed_dead = False
            try:
                confirmed_dead = api.api(f"repos/{store.repo}/actions/runs/{run_id}").get("status") == "completed"
            except GitHubError:
                pass
            deadline = time.time() + max(0.0, float(cancel_wait_seconds))
            while not confirmed_dead and time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
                try:
                    if api.api(f"repos/{store.repo}/actions/runs/{run_id}").get("status") == "completed":
                        confirmed_dead = True
                        break
                except GitHubError:
                    break
            if not confirmed_dead:
                print(json.dumps({"phase": "CANCELLATION_UNCONFIRMED", "task_id": record["task_id"]}), flush=True)
                continue
            receipts.append(_release(
                store, record, "FAILED_RUNNER_SHUTDOWN",
                f"Run {run_id} outlived the {timeout}s job timeout (age {int(age)}s); cancelled and released",
                swept=True, swept_run=run_id, job_timeout_seconds=timeout,
                takeover_reason="stale run exceeded job timeout and grace"))
        except (GitHubError, ValueError, KeyError, TypeError, OSError) as exc:
            receipt = {"task_id": record.get("task_id"), "phase": "RECONCILE_DEFERRED",
                       "diagnostic": str(exc), "at": utcnow()}
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
    return receipts


def classify_checks(api, repo, head):
    checks = []
    # check-runs is an envelope, unlike the legacy statuses array.
    page = 1
    while True:
        result = api.api(f"repos/{repo}/commits/{head}/check-runs?per_page=100&page={page}")
        rows = result["check_runs"]
        checks.extend(rows)
        if len(rows) < 100:
            break
        page += 1
    statuses = list(api.pages(f"repos/{repo}/commits/{head}/statuses"))
    latest = {}
    for row in checks:
        key = (row["name"], (row.get("app") or {}).get("id"))
        if key not in latest or row["id"] > latest[key]["id"]:
            latest[key] = row
    failures = [r for r in latest.values() if r["status"] == "completed"
                and r.get("conclusion") in ("failure", "timed_out", "cancelled", "startup_failure")]
    latest_status = {}
    for row in statuses:  # newest first
        latest_status.setdefault(row["context"], row)
    failures += [r for r in latest_status.values() if r["state"] in ("error", "failure")]
    # Measured 2026-11-01 across 18 open PRs: 15 had no executed checks at all, and
    # paraloom-labs/paraloom-core plus Tarsnap/kivaloo returned action_required on 8 of 8 runs.
    # A workflow held for maintainer approval has not run and will not run until a human clicks
    # approve. Folding it into ``pending`` reported "CI still running" for a PR that was in fact
    # waiting on a person, so the record never aged and no follow-up obligation was ever raised.
    # Held is a distinct observation: the workflow never executed, and that is a fact about the
    # world, not a stage of a run in progress.
    held = [r for r in latest.values() if r.get("conclusion") == "action_required"]
    pending = any(r["status"] != "completed" for r in latest.values()) or any(
        r["state"] == "pending" for r in latest_status.values())
    return {"head_sha": head, "checks": list(latest.values()), "statuses": list(latest_status.values()),
            "failures": failures, "held": held,
            "state": "FAILED" if failures else "HELD" if held else "PENDING" if pending else
            "PASSED" if latest or latest_status else "NO_REMOTE_CHECKS"}


def review_verdict(api, repo, number):
    """Read what a human actually decided about a published PR.

    Measured 2026-11-01: bl4ckb4ll/blackball#182 carried CHANGES_REQUESTED from a collaborator
    and fyne-io/fyne#6637 carried a reviewer report of a failing native check, and neither was
    visible to any pipeline record. The only lane that reads reviews is pr_conversion_watch.py,
    which is deliberately read-only and reports to a file nobody acts on. A review is the one
    signal that says what to do next, so it is observed here as durable state.

    Interpretation stays with the model and the engineer; this reads the verdict GitHub
    recorded and nothing more.
    """
    # pages() yields lazily, so it is a generator: indexing or re-reading it fails. Measured
    # 2026-11-01 (run 41265535120): the published PR sriahead/aheed-online-store#1382 was
    # answered with RECONCILE_DEFERRED "'generator' object is not subscriptable" -- the exact
    # line below -- so the one live PR was never observed and never left
    # PUBLISHED_PENDING_CHECKS. Materialize the page once, and read it as a list.
    reviews = list(api.pages(f"repos/{repo}/pulls/{number}/reviews"))
    states = [str((r or {}).get("state") or "").upper() for r in reviews]
    states = [s for s in states if s]
    if "CHANGES_REQUESTED" in states:
        verdict = "CHANGES_REQUESTED"
    elif "APPROVED" in states:
        verdict = "APPROVED"
    elif states:
        verdict = "COMMENTED"
    else:
        verdict = "NONE"
    latest = reviews[-1] if reviews else {}
    return {"verdict": verdict, "review_count": len(states),
            "latest_reviewer": ((latest or {}).get("user") or {}).get("login"),
            "latest_review_at": (latest or {}).get("submitted_at")}


# Statuses whose failure the pipeline owns and must re-dispatch itself, plus the general rule:
# the ledger's own ``retryable`` verdict. Measured 2026-11-01 (10:24Z, run 41290957550): five
# retryable tasks sat frozen while the delivery engine idled -- lux#99 twice and GramRaksha-AI#2
# on TokenHarbor 429s, dozer#1659 on the same, gyroflow#742 on a dirty baseline, gqrx#1336 on a
# staged whitespace line -- because this decision named only the two post-publication states.
# Every earlier retry of a failed engineering run had come from the door re-admitting the issue;
# when that round returned NO_ROWS (both agent rounds killed at the round budget before writing
# a row) the de-facto retry path died and the queue froze silently. A retry obligation must be
# durable in the ledger, not contingent on a fresh issue appearing.
REPAIRABLE_STATUSES = ("FAILED_REMOTE_CHECKS", "CHANGES_REQUESTED",
                       "FAILED_ENGINEER", "FAILED_DELIVERABLE_MISSING")
REPAIR_ATTEMPT_CAP = 3


def repair_obligation(record):
    """True when this record's failure is the pipeline's to retry, inside its attempt budget."""
    if not isinstance(record, dict):
        return False
    status = str(record.get("status") or "")
    if not (status in REPAIRABLE_STATUSES or record.get("retryable")):
        return False
    try:
        return int(record.get("attempt", 0) or 0) < REPAIR_ATTEMPT_CAP
    except (TypeError, ValueError):
        return False


def retryable_backlog(records) -> int:
    """Count the ledger's own retry queue: retryable failures still inside the attempt budget.

    This is the pipeline's sensory reading of itself. Without it, "the delivery engine is idle
    with five retryable tasks" is an inference a human makes from a run list; with it, every
    reconcile prints the number, so a starved engine with pending work is a measured fact
    rather than a silence nobody notices.
    """
    return sum(1 for record in (records or ()) if repair_obligation(record))


def retry_claim(api, record):
    """Re-post a claim command that failed to submit.

    Measured 2026-11-01: a claim that failed to post was recorded as
    ``claim_retry_required=True`` and then never retried by anything. The obligation was durable
    and unactionable, which is the same as not recording it. A merge without a claim is unpaid
    work, so this is the last link in the chain and it has to close.

    Only a recorded submission failure is retried. An unconfirmed submission is left alone: the
    platform may already have read it, and a second identical command is noise on someone's PR.
    """
    if not record.get("claim_retry_required"):
        return None
    claim = record.get("claim_command")
    number = record.get("pr_number")
    if not claim or not number:
        return {"claim_retry": "NOT_ATTEMPTED",
                "diagnostic": "Claim retry required but command or PR number is missing"}
    try:
        api.api(f"repos/{record['repo']}/issues/{number}/comments", "POST", {"body": claim})
    except (GitHubError, OSError, ValueError) as exc:
        return {"claim_retry": "FAILED", "diagnostic": str(exc)[:300]}
    print(json.dumps({"phase": "CLAIM_RETRIED", "repo": record["repo"], "pr": number}),
          flush=True)
    return {"claim_retry": "SUBMITTED_UNCONFIRMED", "claim_status": "SUBMITTED_UNCONFIRMED",
            "claim_retry_required": False}


def reconcile(repair=False, api=None, store=None):
    api, store = api or GitHub(), store or StateStore()
    # F5: the sweeper runs before the existing branches, so a run that outlived its own job
    # window is released rather than left pinned in CLAIMED forever.
    records = list(store.records() or ())
    receipts = list(sweep_stale_runs(api, store, records=records))
    swept_ids = {r["task_id"] for r in receipts if r.get("swept")}
    observed = {r.get("task_id"): dict(r) for r in records}
    for record in records:
        try:
            if record.get("task_id") in swept_ids:
                continue
            status = record["status"]
            fields = {}
            if status in ("DISPATCHING", "DISPATCHED"):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(record["dispatched_at"])).total_seconds()
                if age > 1800:
                    runs = api.workflow_runs(store.repo)
                    generation = record.get("dispatch_id")
                    matching = [r for r in runs if generation and generation in r.get("display_title", "")]
                    if not matching:
                        fields = {"status": "FAILED_DISPATCH", "diagnostic": "Dispatch acknowledgement timeout: no Actions run observed"}
                    elif all(r.get("status") == "completed" for r in matching):
                        fields = {"status": "FAILED_DISPATCH", "diagnostic":
                                  "Dispatch run completed without acquiring ownership", "owner_revoked": record.get("owner")}
            elif status in ("CLAIMED", "ENGINEERING", "VERIFIED", "PUBLISHING"):
                run = api.api(f"repos/{store.repo}/actions/runs/{record['owner'].split(':')[0]}")
                if run["status"] == "completed":
                    fields = {"status": "FAILED_MISSING_TERMINAL_RECEIPT", "diagnostic":
                              f"Actions run completed ({run['conclusion']}) without terminal callback; artifacts retained",
                              "run_url": run["html_url"]}
            # Reconcile a server-acknowledged PR after a transport/callback failure.
            if (status.startswith("FAILED") or status == "PUBLISHING") and record.get("proposed_head"):
                matches = [p for p in api.pages(f"repos/{record['repo']}/pulls", state="open")
                           if p["head"]["sha"] == record["proposed_head"]
                           and p["head"]["repo"] and p["head"]["repo"]["owner"]["login"] == BOUNTY_ACCOUNT]
                if len(matches) == 1:
                    fields = {"status": "PUBLISHED_PENDING_CHECKS", "head_sha": record["proposed_head"],
                              "pr_number": matches[0]["number"], "pr_url": matches[0]["html_url"],
                              "branch": matches[0]["head"]["ref"], "publication_recovered": True}
            if status in PR_OBSERVATION_STATUSES:
                pr = api.api(f"repos/{record['repo']}/pulls/{record['pr_number']}")
                if pr["head"]["sha"] != record["head_sha"]:
                    fields = {"status": "BLOCKED_HEAD_CHANGED", "diagnostic": "Owned PR head differs from verified receipt"}
                elif pr.get("merged"):
                    fields = {"status": "DELIVERED", "merged_at": pr["merged_at"], "pr_url": pr["html_url"],
                              "payment_status": record.get("payment_status", "UNVERIFIED"),
                              "claim_status": record.get("claim_status", "UNVERIFIED")}
                elif pr["state"] == "closed":
                    fields = {"status": "CLOSED_UNMERGED", "pr_url": pr["html_url"]}
                else:
                    proof = classify_checks(api, record["repo"], record["head_sha"])
                    review = review_verdict(api, record["repo"], record["pr_number"])
                    fields = {"status": "FAILED_REMOTE_CHECKS" if proof["failures"] else
                              "CHECKS_HELD_FOR_APPROVAL" if proof["state"] == "HELD" else
                              "PUBLISHED_PENDING_CHECKS" if proof["state"] == "PENDING" else "AWAITING_REVIEW",
                              "remote_verification": proof, "remote_review": review}
                    if proof["failures"]:
                        fields["failures"] = [*record.get("failures", []), proof]
                    if review["verdict"] == "CHANGES_REQUESTED":
                        # A reviewer asked for a change. That is ours to fix, and it is a durable
                        # obligation rather than a note in a report file.
                        fields["status"] = "CHANGES_REQUESTED"
                        fields["review_obligation"] = "address_review"
                    # A claim that failed to post is unpaid work waiting to happen. Close the last
                    # link here, where the PR is already being observed.
                    retried = retry_claim(api, record)
                    if retried:
                        fields.update(retried)
            if not fields:
                # A retryable failure has nothing to observe: its obligation is the retry
                # itself. This branch is why the engine can sit idle while retryable work
                # waits -- the observation path used to own the only retry gate, so a
                # failed engineering run never reached it.
                if not (repair and repair_obligation(record)):
                    continue
                state = record
                identity = record["task_id"]
                receipt = {"task_id": identity, "previous": status, "status": status,
                           "at": utcnow()}
                self_dispatch = True
            else:
                identity = record["task_id"]
                def update(old):
                    if not old or old.get("updated_at") != record.get("updated_at"):
                        raise ValueError("Concurrent state change; reconciliation deferred")
                    return {**old, **fields, "observed_at": utcnow()}
                state = store.mutate(identity, update)
                observed[identity] = state
                receipt = {"task_id": identity, "previous": status,
                           "status": state.get("status"), "at": utcnow()}
                self_dispatch = False
            if repair and (self_dispatch or repair_obligation(state)):
                from actions_dispatch import dispatch
                from bounty_admission import competition
                from pipeline_evidence import require_evidence
                try:
                    context = api.issue_context(state["repo"], state["issue_number"])
                    proof, verdict = require_evidence(state, context)
                    competition(api, state["repo"], state["issue_number"],
                                own_head=state.get("head_sha"))
                    dispatch(api, store, context, proof, state.get("lanes", []), remote_repair=True,
                             sovereign_admission=True, competition=verdict)
                    receipt["repair"] = "DISPATCHED"
                except ValueError as exc:
                    receipt["repair_blocked"] = str(exc)

            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
        except (GitHubError, ValueError, KeyError, TypeError, OSError) as exc:
            receipt = {"task_id": record.get("task_id"), "phase": "RECONCILE_DEFERRED",
                       "diagnostic": str(exc), "at": utcnow()}
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
    for receipt in receipts:
        if receipt.get("status") and receipt.get("task_id") in observed:
            observed[receipt["task_id"]]["status"] = receipt["status"]
    followups = [{"task_id": r.get("task_id"), "pr_url": r.get("pr_url"),
                  "claim_status": r.get("claim_status", "UNVERIFIED"),
                  "claim_retry_required": r.get("claim_retry_required", False),
                  "payment_status": r.get("payment_status", "UNVERIFIED")}
                 for r in observed.values() if r.get("pr_url")]
    report = {"at": utcnow(), "receipts": receipts, "followup_obligations": followups,
              "recorded_prs": len(followups),
              "recorded_merges": sum(r.get("status") == "DELIVERED" for r in observed.values()),
              "observation_errors": sum(r.get("phase") == "RECONCILE_DEFERRED" for r in receipts),
              # The pipeline reading its own queue: how many retryable failures are waiting,
              # and how many of them this pass discharged. An idle delivery engine with a
              # non-zero backlog is a starvation event, and now it says so.
              "retryable_backlog": retryable_backlog(records),
              "repair_obligations_discharged": sum(r.get("repair") == "DISPATCHED" for r in receipts),
              "repair_obligations_blocked": sum(1 for r in receipts if r.get("repair_blocked"))}
    if os.environ.get("BOUNTY_STATE_DIR"):
        folder = Path(os.environ["BOUNTY_STATE_DIR"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "reconciliation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"phase": "RECONCILIATION_SUMMARY", **report}), flush=True)
    return receipts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    reconcile(parser.parse_args().repair)
