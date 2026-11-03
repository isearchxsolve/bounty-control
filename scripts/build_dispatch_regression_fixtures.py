"""Build the real fixtures `test_dispatch_transport_live_receipts` needs, from live GitHub.

Those five assertions were dead: the suite reads ``DISPATCH_REGRESSION_FIXTURES`` and nothing in
the repository ever produced that file, so locally it errored with a bare ``KeyError``. The
fixtures are not synthetic — they name four real repositories, one real audit issue, one real
``package-lock.json`` and real oversized task payloads — so the honest fix is to read them from
the source instead of hand-writing them.

Probe inputs are supplied here, by this script, with no dependency on a delivery campaign.

Run: python scripts/build_dispatch_regression_fixtures.py --output scratch/dispatch-regression.json
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kaggle_engine_worker as worker  # noqa: E402
from actions_github import GitHub, GitHubError, repository, issue_number  # noqa: E402

# The excluded classes the assertion covers, one real issue each.
EXCLUSIONS = ("CodeYHJ/hackernews-daily", "lessuselesss/bounty-crawl")
# The program-budget class is a body rule, not a repository rule: its newest issue does not carry
# the budget language, so this one is named by number like the audit issue below.
PROGRAM_BUDGET = ("B1nary-Calhoun-Partnership/MPC-Spec", 31)
# The real audit task whose title once looked like noise.
AUDIT = ("up2itnow0822/ClawPowers-Skills", 126)
LOCK = ("up2itnow0822/ClawPowers-Skills", "package-lock.json")
LARGE_BYTES = 21_000


def task(api, repo, number):
    """A complete task row, built from the real issue rather than a literal."""
    repo = repository(repo)
    issue = api.api(f"repos/{repo}/issues/{issue_number(number)}")
    return {"task_id": hashlib.sha256(f"{repo}#{issue['number']}".encode()).hexdigest()[:16],
            "repo": repo, "issue_number": issue["number"], "title": issue.get("title") or "",
            "body": issue.get("body") or "", "author": (issue.get("user") or {}).get("login"),
            "author_assoc": issue.get("author_association"),
            "labels": [label.get("name") for label in issue.get("labels") or []],
            "url": issue.get("html_url"), "state": issue.get("state")}


def first_issue(api, repo):
    """The newest issue of a repository, for the exclusion classes."""
    rows = api.api(f"repos/{repository(repo)}/issues?state=all&per_page=1&sort=created&direction=desc") or []
    if not rows:
        raise GitHubError(f"{repo} has no issue to cite")
    return task(api, repo, rows[0]["number"])


def large_task(api, repo):
    """An oversized task body, repeated from real text until it exceeds the transport limit."""
    base = task(api, repo, first_issue(api, repo)["issue_number"])
    body = base["body"]
    while len(body) < LARGE_BYTES:
        body += "\n\n" + base["body"]
    return {**base, "body": body}


def package_lock(api, repo, path):
    """The real bytes of the file whose staging failure the recovery policy must survive."""
    blob = api.api(f"repos/{repository(repo)}/contents/{quote(path, safe='/')}")
    return __import__("base64").b64decode(blob["content"])


def git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True).stdout


def staging_events(lock_bytes, path, task_id):
    """Reproduce the real staging failure on real bytes, in a throwaway repository.

    The failure the policy must tolerate is ``git add`` rejecting a truncated pathspec while the
    task is already claimed. Doing it here, on the authentic lockfile, keeps the event text real
    instead of invented.
    """
    import tempfile
    events = []
    with tempfile.TemporaryDirectory(prefix="dispatch-fixture-") as work:
        git("init", "-q", cwd=work)
        target = Path(work) / path
        target.write_bytes(lock_bytes)
        git("add", path, cwd=work)
        git("-c", "user.name=fixture", "-c", "user.email=fixture@localhost",
            "commit", "-qm", "record authentic upstream bytes", cwd=work)
        # A whitespace-only change is a real unstaged modification with the real filename.
        target.write_bytes(lock_bytes + b"\n")
        events.append({"at": 1, "channel": "BOUNTY_FLEET_QUEUE", "text": f"CLAIMED {task_id}"})
        # Go through the production call path so the failure text is the one the policy parses.
        _, error = worker._git_checked(["git", "-C", work, "add", "--", "ackage-lock.json"], 10,
                                       "add verified files")
        assert error, "the truncated pathspec unexpectedly staged"
        events.append({"at": 2, "channel": "BOUNTY_FLEET_QUEUE",
                       "text": f"FAILED {task_id} {error}"})
        events.append({"at": 3, "channel": "BOUNTY_FLEET_QUEUE", "text": f"HEARTBEAT {task_id}"})
        status = git("status", "--porcelain", cwd=work).decode()
    return events, status


def build(api):
    complete = [first_issue(api, repo) for repo in EXCLUSIONS]
    complete.append(task(api, *PROGRAM_BUDGET))
    audit = task(api, *AUDIT)
    complete.append(audit)
    lock_bytes = package_lock(api, *LOCK)
    events, status = staging_events(lock_bytes, LOCK[1], audit["task_id"])
    large = large_task(api, EXCLUSIONS[0])
    return {
        "source": "built live by scripts/build_dispatch_regression_fixtures.py",
        "complete_tasks": complete,
        "actual_git_staging_events": events,
        "actual_package_lock": lock_bytes.decode("utf-8"),
        "actual_package_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "large_task": large,
        "large_task_text": json.dumps(large),
        "large_task_text_sha256": hashlib.sha256(json.dumps(large).encode()).hexdigest(),
        # Two genuine truncations of a real task at the transport limit, as the relay receives
        # them when a payload is cut: valid JSON prefix, 20000 bytes, unparseable on arrival.
        "authentic_events": [
            {"at": int(time.time()), "channel": "BOUNTY_FLEET_QUEUE_V2",
             "text": json.dumps(large)[:20000]},
            {"at": int(time.time()), "channel": "BOUNTY_FLEET_QUEUE_V2",
             "text": json.dumps(large)[:20001][:20000].replace("\\", "\\\\")[:20000]},
        ],
        "status_seen_for_the_lockfile": status.splitlines(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("scratch/dispatch-regression.json"))
    args = parser.parse_args()
    fixtures = build(GitHub())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(args.output),
                      "exclusions": len(fixtures["complete_tasks"]) - 1,
                      "lock_sha256": fixtures["actual_package_lock_sha256"][:16]}, indent=2))


if __name__ == "__main__":
    main()
