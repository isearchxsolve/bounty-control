"""GitHub transport and durable per-original-issue state; never logs credentials."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import time
from urllib.parse import urlencode


class GitHubError(RuntimeError):
    pass


# The bounty account owns the fork/PR identity. It is read once from the environment so a
# mirror to another account is one variable, not a seventeen-file rename.
# The bounty account owns the fork and PR identity, so it must be the account that is
# actually running the workflow. A compiled-in default pointed the survivor at the
# retired account: the PR branch was pushed as "niloydassana-maker:branch" and the
# fork URL named a repo this token cannot write to (observed 2026-10-29).
BOUNTY_ACCOUNT = (os.environ.get("BOUNTY_ACCOUNT")
                  or (os.environ.get("GITHUB_REPOSITORY") or "").split("/")[0]
                  or "isearchxsolve")
DEFAULT_REPOSITORY = os.environ.get("BOUNTY_REPOSITORY") or BOUNTY_ACCOUNT + "/anonym-family-archive"


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Invalid GitHub repository")
    return value


def issue_number(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError("Invalid issue number")
    return int(value)


def task_id(repo, number):
    return hashlib.sha256(f"{repository(repo).lower()}#{issue_number(number)}".encode()).hexdigest()[:32]


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class GitHub:
    def __init__(self, token=None, deadline=None):
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        self.deadline = deadline

    THROTTLE = re.compile(r"rate limit exceeded|secondary rate limit|abuse detection", re.I)
    THROTTLE_TRIES = 4

    @staticmethod
    def throttle_wait(message):
        """Search allows 30 requests per minute, so its ceiling clears within a minute.

        Honour an explicit retry-after when GitHub sends one; otherwise wait out the
        rolling minute. Bounded, because an unbounded wait hides a real outage.
        """
        match = re.search(r"retry.after[:= ]+(\d+)", message, re.I)
        if match:
            return min(int(match.group(1)), 120)
        # A *core* ceiling is hourly, not the 60-second search window: measured on run
        # 41188694229, four 65-second waits burned the whole headroom and the run died 4 minutes
        # in, before the door had searched at all. Ask GitHub when the window actually resets
        # (the rate_limit endpoint does not consume quota) and wait that long, bounded.
        remaining = GitHub.core_reset_seconds()
        if remaining is not None:
            return max(5, min(remaining + 5, 600))
        return 65

    @staticmethod
    def core_reset_seconds():
        """Seconds until the core window resets, or None when GitHub will not say."""
        try:
            done = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, timeout=30,
                                  env={**os.environ})
            if done.returncode:
                return None
            document = json.loads(done.stdout.decode("utf-8", errors="replace") or "{}")
            reset = (document.get("resources") or {}).get("core", {}).get("reset")
            if not reset:
                return None
            return max(0, int(reset - time.time()))
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            return None

    def api(self, endpoint, method="GET", data=None, paginate=False):
        command = ["gh", "api", endpoint, "--method", method]
        if paginate:
            command += ["--paginate", "--slurp"]
        encoded = None
        if data is not None:
            command += ["--input", "-"]
            encoded = json.dumps(data).encode()
        environment = dict(os.environ)
        if self.token:
            environment["GH_TOKEN"] = self.token
        message = ""
        deadline = min(self.deadline or float("inf"), time.monotonic() + 180)
        for attempt in range(self.THROTTLE_TRIES):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitHubError("GitHub observation deadline exhausted: " + endpoint[:160])
            try:
                result = subprocess.run(command, input=encoded, capture_output=True,
                                        timeout=min(90, remaining), env=environment)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GitHubError("GitHub transport failed: " + str(exc)) from exc
            if not result.returncode:
                return json.loads(result.stdout) if result.stdout.strip() else None
            # gh itself masks authentication; do not include body/environment.
            message = result.stderr.decode("utf-8", errors="replace")[-1500:]
            if not self.THROTTLE.search(message) or attempt + 1 >= self.THROTTLE_TRIES:
                raise GitHubError(message)
            wait = self.rate_limit_wait(endpoint, message, environment)
            if wait >= deadline - time.monotonic():
                raise GitHubError("GitHub throttle exceeds remaining observation budget: " + message)
            # A transient ceiling is not a failure of the lane: wait it out and
            # retry, and say so on the wire so a slow run is never mistaken for a
            # hung one.
            print(json.dumps({"phase": "THROTTLE", "endpoint": endpoint[:160],
                              "attempt": attempt + 1, "wait_s": wait}), flush=True)
            time.sleep(wait)
        raise GitHubError(message)

    @staticmethod
    def rate_limit_wait(endpoint, message, environment):
        explicit = re.search(r"retry.after[:= ]+(\d+)", message, re.I)
        if explicit:
            return max(1, int(explicit.group(1)))
        resource = "search" if endpoint.startswith("search/") else "graphql" if endpoint == "graphql" else "core"
        try:
            done = subprocess.run(["gh", "api", "rate_limit"], capture_output=True,
                                  timeout=10, env=environment)
            if done.returncode == 0:
                observed = json.loads(done.stdout)["resources"][resource]
                if observed["remaining"] == 0:
                    return max(1, int(observed["reset"] - time.time()) + 1)
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            pass
        return 65

    def pages(self, endpoint, **params):
        """Require complete pagination; a failed page never means empty supply."""
        sep = "&" if "?" in endpoint else "?"
        pages = self.api(endpoint + sep + urlencode({**params, "per_page": 100}), paginate=True)
        for rows in pages:
            if not isinstance(rows, list):
                raise GitHubError("Expected paginated GitHub array")
            yield from rows

    def workflow_runs(self, repo, status=None):
        """Complete delivery-workflow run observations, not a mixed 100-run window."""
        rows, page = [], 1
        while True:
            params = {"per_page": 100, "page": page}
            if status:
                params["status"] = status
            result = self.api(f"repos/{repository(repo)}/actions/workflows/engine2.yml/runs?" + urlencode(params))
            batch = result["workflow_runs"]
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1

    def issue_context(self, repo, number):
        repo, number = repository(repo), issue_number(number)
        metadata = self.api(f"repos/{repo}")
        issue = self.api(f"repos/{repo}/issues/{number}")
        if issue.get("pull_request"):
            raise ValueError("Task is a pull request, not an issue")
        comments = list(self.pages(f"repos/{repo}/issues/{number}/comments"))
        complete = len(comments) == issue["comments"]
        count_evidence = {"rest_reported": issue["comments"], "rest_visible": len(comments)}
        if not complete:
            # REST's issue counter can include comments absent from the visible
            # connection. Confirm the visible count and terminal ID independently;
            # never manufacture missing comments or silently call them complete.
            query = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                     "issue(number:$number){comments(last:1){totalCount nodes{databaseId}}}}}")
            try:
                result = self.api("graphql", "POST", {"query": query, "variables": {
                    "owner": repo.split("/")[0], "name": repo.split("/")[1], "number": number}})
                if result.get("errors"):
                    raise GitHubError("Visible comment count could not be independently established")
                connection = result["data"]["repository"]["issue"]["comments"]
                last = connection["nodes"][-1]["databaseId"] if connection["nodes"] else None
                count_evidence.update(graphql_visible=connection["totalCount"], graphql_last_id=last)
                complete = (connection["totalCount"] == len(comments)
                            and last == (comments[-1]["id"] if comments else None))
            except GitHubError as exc:
                count_evidence["diagnostic"] = str(exc)
        default_branch = metadata.get("default_branch", "main")
        return {"repo": repo, "issue_number": number, "title": issue["title"],
                "body": issue.get("body") or "", "issue": issue,
                "repository": metadata, "comments": comments,
                "author_comments": [c.get("body") or "" for c in comments],
                "fetched_at": utcnow(), "complete_comments": complete,
                "comment_count_evidence": count_evidence,
                "base_branch": default_branch}


CLAIM_TTL_SECONDS = 1800  # floor only: the derived lease is always longer than a legal run
CLAIM_LEASE_GRACE_SECONDS = 300  # 5 minutes grace beyond the workflow's own Cline budget
DEFAULT_CLINE_TOTAL_BUDGET_SECONDS = 14400  # engine2.yml CLINE_TOTAL_BUDGET_SECONDS


def cline_total_budget_seconds() -> int:
    """The workflow's own Cline budget, as exported into this process's environment.

    F5 requires the lease to be derived from the run's real budget because a fixed short
    TTL expires while a legitimate run is still working -- and a lease that is shorter than
    a legal run turns the sweeper into the cause of the deadlock it exists to clear. An
    absent or malformed value falls back to the workflow default, never to a short lease.
    """
    try:
        return max(0, int(os.environ.get("CLINE_TOTAL_BUDGET_SECONDS")))
    except (TypeError, ValueError):
        return DEFAULT_CLINE_TOTAL_BUDGET_SECONDS


def lease_seconds() -> int:
    """Never shorter than a legitimate run: the budget plus grace, with a hard floor."""
    return max(CLAIM_TTL_SECONDS, cline_total_budget_seconds() + CLAIM_LEASE_GRACE_SECONDS)


def _lease_expires_at(claimed_at: str) -> str:
    """Compute lease expiry timestamp from claimed_at."""
    from datetime import datetime, timedelta
    claimed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
    return (claimed + timedelta(seconds=lease_seconds())).isoformat()


class StateStore:
    """Contents API SHA compare-and-swap on a dedicated control branch."""
    def __init__(self, api=None, repo=None):
        self.api = api or GitHub()
        self.repo = repository(repo or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY)
        self.branch = "bounty-control"

    def _lease_expired_and_dead(self, old, probes: int = 2) -> bool:
        """Return True if the claim lease has expired AND the owner run is provably dead.

        A lease is expired when lease_expires_at is in the past. A dead owner means
        the Actions run is completed or the API probe fails twice in a row.
        Unknown (probe error) is never treated as dead.
        """
        expires = old.get("lease_expires_at")
        if not expires:
            return False
        try:
            expires_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        if datetime.now(timezone.utc) < expires_dt:
            return False  # Lease not yet expired

        # Lease expired - check if owner is provably dead
        run_id = old.get("owner", "").split(":")[0]
        for _ in range(probes):
            try:
                run = self.api.api(f"repos/{self.repo}/actions/runs/{run_id}")
            except GitHubError:
                continue  # Probe error is not proof of death
            if run.get("status") == "completed":
                return True  # Completed is unambiguous: owner is done
        return False  # Unknown is never treated as dead

    def ensure(self):
        try:
            self.api.api(f"repos/{self.repo}/git/ref/heads/{self.branch}")
        except GitHubError as exc:
            if "404" not in str(exc):
                raise
            info = self.api.api(f"repos/{self.repo}")
            head = self.api.api(f"repos/{self.repo}/git/ref/heads/{info['default_branch']}")
            try:
                self.api.api(f"repos/{self.repo}/git/refs", "POST",
                             {"ref": "refs/heads/" + self.branch, "sha": head["object"]["sha"]})
            except GitHubError as race:
                if "422" not in str(race):
                    raise

    def read(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Invalid canonical task identity")
        try:
            obj = self.api.api(f"repos/{self.repo}/contents/fleet-state/{identity}.json?ref={self.branch}")
        except GitHubError as exc:
            if "404" in str(exc):
                return None, None
            raise
        return json.loads(base64.b64decode(obj["content"])), obj["sha"]

    def write(self, identity, document, expected_sha):
        body = {"message": f"fleet: {identity} {document['status']}",
                "branch": self.branch,
                "content": base64.b64encode(json.dumps(document, indent=2).encode()).decode()}
        if expected_sha:
            body["sha"] = expected_sha
        return self.api.api(f"repos/{self.repo}/contents/fleet-state/{identity}.json", "PUT", body)

    def mutate(self, identity, change):
        self.ensure()
        for attempt in range(5):
            previous, sha = self.read(identity)
            document = change(previous)
            document["updated_at"] = utcnow()
            try:
                self.write(identity, document, sha)
                return document
            except GitHubError as exc:
                if not any(code in str(exc) for code in ("409", "422")) or attempt == 4:
                    raise
                time.sleep(min(attempt + 1, 4))
        raise GitHubError("State compare-and-swap exhausted")

    def claim(self, repo, number, owner, run_url, harness_sha, recovery=False, budget_seconds=None,
              dispatch_id=None):
        identity = task_id(repo, number)
        def reserve(old):
            old = old or {"task_id": identity, "repo": repo, "issue_number": number, "attempt": 0}
            if dispatch_id is not None and old.get("dispatch_id") != dispatch_id:
                raise ValueError("Dispatch generation mismatch")
            if (dispatch_id is not None and old.get("status") not in ("DISPATCHING", "DISPATCHED")
                    and not (old.get("status") == "CLAIMED" and old.get("owner") == owner)
                    and not recovery):
                raise ValueError("Dispatch generation is not claimable")
            if old.get("owner_revoked") == owner:
                raise ValueError("Task ownership revoked")
            if old.get("status") == "DELIVERED":
                raise ValueError("Task already delivered")
            if old.get("status") in ("PUBLISHED_PENDING_CHECKS", "AWAITING_REVIEW"):
                raise ValueError("Owned PR is pending; reconcile it before another engineering run")
            if old.get("owner") == owner and old.get("status") == "CLAIMED":
                # Same owner re-claiming: refresh the lease timestamp.
                claimed_at = old.get("claimed_at")
                if claimed_at:
                    claimed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - claimed).total_seconds()
                    if age > CLAIM_TTL_SECONDS:
                        # Lease expired even for the same owner: fall through to re-claim.
                        pass
                    else:
                        return old
                else:
                    return old
            active = old.get("status") in ("CLAIMED", "ENGINEERING", "VERIFIED", "PUBLISHING")
            takeover = {}
            if active:
                # F5: claim lease expiry — a stale claim with no live run is expired,
                # not a permanent lock. Expiry alone is never enough: the owner must also
                # be provably dead, so a live run is never double-dispatched.
                if self._lease_expired_and_dead(old):
                    # A takeover is a diagnostic event, never a silent reset.
                    takeover = {"takeover_reason": "lease expired and owner run is provably dead",
                                "takeover_at": utcnow()}
                else:
                    raise ValueError("A live Actions run already owns this task")
            attempt = int(old.get("attempt", 0)) + 1
            if attempt > (4 if recovery else 3):
                raise ValueError("Bounded recovery attempts exhausted")
            record = {**old, **takeover, "status": "CLAIMED", "attempt": attempt, "owner": owner,
                      "previous_owner": old.get("owner"), "previous_status": old.get("status"),
                      "run_url": run_url, "harness_sha": harness_sha, "claimed_at": utcnow(),
                      "lease_expires_at": _lease_expires_at(utcnow())}
            if budget_seconds is not None:
                # Recorded on the claim so the ledger can answer "how long was this run
                # given" without reading the dispatch payload (field was absent until
                # 2026-10-29, so every historical record reads None).
                record["preparation_budget_seconds"] = int(budget_seconds)
            return record
        return self.mutate(identity, reserve)

    def owned_update(self, identity, owner, **fields):
        def update(old):
            if not old or old.get("owner") != owner or old.get("owner_revoked") == owner:
                raise ValueError("Task ownership lost")
            return {**old, **fields}
        return self.mutate(identity, update)

    def assert_owner(self, identity, owner):
        record, _ = self.read(identity)
        if (not record or record.get("owner") != owner
                or record.get("owner_revoked") == owner):
            raise ValueError("Task ownership lost")
        return record

    def records(self):
        try:
            tree = self.api.api(f"repos/{self.repo}/git/trees/{self.branch}")
        except GitHubError as exc:
            if "404" in str(exc):
                return
            raise
        subtree = next((entry for entry in tree["tree"] if entry["path"] == "fleet-state" and entry["type"] == "tree"), None)
        if not subtree:
            return
        tree = self.api.api(f"repos/{self.repo}/git/trees/{subtree['sha']}")
        if tree.get("truncated"):
            raise GitHubError("Durable state tree truncated; reconciliation must be partitioned")
        for entry in tree["tree"]:
            if re.fullmatch(r"[a-f0-9]{32}\.json", entry["path"]):
                try:
                    record, _ = self.read(entry["path"][:-5])
                    if record:
                        yield record
                except (GitHubError, ValueError, KeyError, TypeError, OSError) as exc:
                    print(json.dumps({"phase": "STATE_OBSERVATION_ERROR", "task_id": entry["path"][:-5],
                                      "diagnostic": str(exc)}), flush=True)
