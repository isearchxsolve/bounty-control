"""Ask GitHub to start the discovery workflow when its own scheduler has stalled.

Measured need (2026-10-27): ``.github/workflows/bounty-discovery.yml`` declares
``schedule: */15 * * * *``, the workflow's state is ``active`` (not
``disabled_inactivity``), and the file has been on the default branch since 14:48Z -- yet all
nine runs observed that day were ``workflow_dispatch`` (15:13Z-17:54Z). GitHub's cron never
fired once. Discovery therefore ran only when a human typed a command, which is
indistinguishable from a pipeline that is switched off.

This is the sanctioned exception to the "no competing local daemons" rule. It is one paced
evaluation that reads the run list and, only when nothing is running and nothing recent
exists, asks GitHub itself to dispatch the workflow through the public API. It never runs a
phase, never touches a task, and holds whenever any run is queued or in flight, so it cannot
duplicate work; the decision is fail-closed on a probe error.

The discovery workflow is scheduled every 15 minutes. The 20-minute default allows five minutes
for scheduler delay, then restores discovery cadence if no run has appeared.

The decision is a pure function so the edges can be pinned without touching the network.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# The heartbeat must watch the repository it is running in, not a compiled-in name. It is
# scheduled from the default branch of whichever repo hosts it, and a fixed default silently
# pointed the survivor at the retired account: on 2026-10-29 run 40865557648 probed
# niloydassana-maker, found that account's stale run, tried to dispatch there and died with
# "HTTP 403: Must have admin rights", so the self-healing loop was dark by construction.
DEFAULT_REPO = (os.environ.get("BOUNTY_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
                or "isearchxsolve/anonym-family-archive")
DEFAULT_WORKFLOW = "bounty-discovery.yml"
# None means: ask GitHub which branch this repository actually dispatches on. A compiled-in
# branch name is a guess, and a guess is a refusal: measured 2026-11-01 (run 41256276495),
# the ref "master" was dispatched against a repository whose default branch is "main", so
# every dispatch was answered "HTTP 422: No ref found for: master" and the fallback that
# exists to restart a stalled discovery cron was itself dark. Hardcoding "main" makes the
# same assumption in the other spelling; the branch name is a fact GitHub will tell us.
DEFAULT_REF = None

# States in which GitHub already has (or is about to have) a run. Dispatching now would either
# duplicate the pass or sit in a concurrency queue behind it.
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested", "waiting_for_approval"}


class ProbeError(RuntimeError):
    """The run list could not be read, so nothing may be decided."""


def parse_stamp(value):
    """Parse a GitHub timestamp; return ``None`` rather than guessing at a malformed one."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def heartbeat_decision(runs, now, max_age_minutes=20, cooldown_minutes=20, last_fire=None):
    """Decide whether to dispatch the discovery workflow. Returns ``(fire, reason)``.

    Refusals, in order:

    * ``already_running`` -- a run is queued or in flight; a second dispatch duplicates it.
    * ``cooldown`` -- this heartbeat fired recently; GitHub is allowed to catch up.

    Fires only when:

    * ``no_history`` -- the workflow has never run here, so nothing else will start it.
    * ``stale`` -- the newest run is older than ``max_age_minutes``, i.e. the schedule is not
      beating on its own.

    A malformed timestamp is not evidence of freshness: it is dropped, and if no run carries a
    usable timestamp the answer is ``no_history`` (fire) rather than a silent hold forever.
    """
    usable = [run for run in (runs or []) if isinstance(run, dict)]
    for run in usable:
        if str(run.get("status") or "").strip().lower() in ACTIVE_STATUSES:
            return False, "already_running"
    fired_at = parse_stamp(last_fire)
    if fired_at is not None:
        if (now - fired_at).total_seconds() < cooldown_minutes * 60:
            return False, "cooldown"
    stamps = [stamp for stamp in (parse_stamp(run.get("createdAt")) for run in usable) if stamp]
    if not stamps:
        return True, "no_history"
    age_minutes = (now - max(stamps)).total_seconds() / 60.0
    if age_minutes < max_age_minutes:
        return False, "fresh"
    return True, "stale"


def probe(repo, workflow, limit=10):
    """Read the workflow's recent runs through the authenticated ``gh`` client."""
    result = subprocess.run(
        ["gh", "run", "list", "--repo", repo, "--workflow", workflow, "--limit", str(limit),
         "--json", "status,conclusion,createdAt,databaseId,url"],
        capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ProbeError((result.stderr or result.stdout or "gh run list failed").strip()[:600])
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise ProbeError("Unreadable run list: " + str(exc)) from exc


def dispatch(repo, workflow, ref):
    """Ask GitHub to start the workflow. Returns ``(ok, detail)``; never raises."""
    result = subprocess.run(["gh", "workflow", "run", workflow, "--repo", repo, "--ref", ref],
                            capture_output=True, text=True, timeout=120)
    detail = (result.stdout or result.stderr or "").strip()[:600]
    return result.returncode == 0, detail


def resolve_ref(repo):
    """Read the repository's real default branch, or ``None`` if it cannot be read.

    ``gh workflow run`` needs a ref that exists on that repository. Reading it is one
    authenticated GET; guessing it is a 422 that silently disables the fallback (measured
    2026-11-01, run 41256276495, ref "master" against default branch "main"). An unreadable
    answer must stay unreadable rather than become a guess.
    """
    result = subprocess.run(["gh", "api", f"repos/{repo}", "--jq", ".default_branch"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def last_fire(state_path):
    """Timestamp of the most recent receipt that actually fired, or ``None``."""
    path = Path(state_path)
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            receipt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if receipt.get("fired") and receipt.get("at"):
            return receipt["at"]
    return None


def record(state_path, receipt):
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")


def refresh_lock(handle):
    """Renew the held lock lease so a live loop is never mistaken for a dead owner."""
    lease = f"{os.getpid()} {time.time():.6f}".encode("ascii")
    os.ftruncate(handle, 0)
    os.lseek(handle, 0, os.SEEK_SET)
    os.write(handle, lease)
    os.fsync(handle)


def acquire_lock(path, stale_minutes):
    """One evaluator at a time; take over a lock nobody has touched for ``stale_minutes``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            age = stale_minutes * 60
        if age < stale_minutes * 60:
            return None
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            # Windows refuses to unlink an open lock. Treat that as a live owner and fail closed.
            return None
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
    refresh_lock(handle)
    return handle


def evaluate(args, dry_run):
    """One evaluation: probe, decide, fire if warranted, and write the receipt."""
    now = datetime.now(timezone.utc)
    receipt = {"at": now.isoformat().replace("+00:00", "Z"), "dry_run": bool(dry_run),
               "repo": args.repo, "workflow": args.workflow, "ref": args.ref}
    try:
        runs = probe(args.repo, args.workflow)
        fire, reason = heartbeat_decision(runs, now, args.max_age_minutes,
                                          args.cooldown_minutes, last_fire(args.state))
        receipt.update(runs_visible=len(runs), decision=reason,
                       newest_run=(runs[0] if runs else None))
    except ProbeError as exc:
        fire, reason = False, "probe_error"
        receipt.update(runs_visible=0, decision=reason, probe_error=str(exc),
                       newest_run=None)
    receipt["fired"] = False
    if fire:
        # An explicit --ref is honored; otherwise the repository's real default branch is
        # read and recorded. A ref that cannot be read is never guessed.
        ref = args.ref or resolve_ref(args.repo)
        if ref is None:
            receipt["decision"] = "ref_unresolved"
        else:
            receipt["ref"] = ref
            if not dry_run:
                ok, detail = dispatch(args.repo, args.workflow, ref)
                receipt["fired"] = bool(ok)
                receipt["dispatch_detail"] = detail
                if not ok:
                    receipt["decision"] = "dispatch_failed"
    receipt["would_fire"] = bool(fire)
    record(args.state, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    # A failed dispatch used to print "HOLD stale", which reads as a healthy hold on a fresh
    # pipeline. It is neither: the decision was to fire and the dispatch was refused.
    if receipt["fired"]:
        verdict = "FIRED " + args.workflow
    elif receipt["decision"] == "dispatch_failed":
        verdict = "DISPATCH_FAILED " + str(receipt.get("dispatch_detail", ""))[:400]
    elif receipt["decision"] == "ref_unresolved":
        verdict = ("HOLD ref_unresolved: cannot read the default branch of " + args.repo +
                   "; refusing to dispatch a guessed ref")
    else:
        verdict = "HOLD " + reason + (" (dry run)" if dry_run and fire else "")
    print("VERDICT: " + verdict)
    return 0 if (not fire or dry_run or receipt["fired"]) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--max-age-minutes", type=int, default=20)
    parser.add_argument("--cooldown-minutes", type=int, default=20)
    parser.add_argument("--state", default=str(Path("scratch") / "discovery-heartbeat.jsonl"))
    parser.add_argument("--lock", default=str(Path("scratch") / "discovery-heartbeat.lock"))
    parser.add_argument("--lock-stale-minutes", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args(argv)
    if args.max_age_minutes < 1 or args.cooldown_minutes < 0 or args.interval < 30:
        parser.error("intervals must be positive (interval >= 30 seconds)")
    lock = acquire_lock(args.lock, args.lock_stale_minutes)
    if lock is None:
        print("VERDICT: HOLD already_evaluating")
        return 0
    try:
        while True:
            try:
                status = evaluate(args, args.dry_run)
            except Exception as exc:  # noqa: BLE001 - a beat must never take the host down
                print("VERDICT: HOLD receipt_error " + type(exc).__name__ + ": " + str(exc))
                status = 0
            if not args.loop:
                return status
            try:
                refresh_lock(lock)
            except OSError as exc:
                print("VERDICT: HOLD lock_refresh_error " + type(exc).__name__ + ": " + str(exc))
                return 2
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        os.close(lock)
        Path(args.lock).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
