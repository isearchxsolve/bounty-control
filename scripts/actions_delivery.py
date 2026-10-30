"""Actions adapter for the repaired Cline lifecycle; publication is a separate job."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from types import SimpleNamespace

from actions_github import (BOUNTY_ACCOUNT, GitHub, GitHubError, StateStore, issue_number,
                            repository, task_id, utcnow)
from actions_release import (git, manifest, product_paths, protect_baseline_tests,
                             regression_proof, require_commands, safe_path, status_paths,
                             validate_plan_contract, write_json, restore_checkpoint)
from bounty_admission import admit, competition, TRUSTED_BOTS
from bounty_fx import quote
# The typed failures live in a dependency-free module because the worker has to raise the
# same classes and must never import this adapter back (it is imported lazily here).
from delivery_errors import (PREPARATION_ACTIONS, ClineBudgetExhausted, ClineDeliverableInvalid,
                             ClineDeliverableMissing, InfrastructureFault, PreparationRace,
                             RunnerShutdown, validate_preparation)


def write_json_atomic(path, document):
    """Write JSON to a temp path in the same directory, then os.replace so a reader
    never observes a partial document."""
    tmp = path.with_name(path.name + ".tmp")
    write_json(tmp, document)
    os.replace(tmp, path)


def submodule_without_url(text):
    """Return the first ``[submodule ...]`` section that declares no ``url``, or None.

    A ``.gitmodules`` whose entry has no url is the recorded defect: git then fails with
    ``fatal: No url found for submodule path during repo in .gitmodules`` and a repository
    unrelated to the issue becomes silently un-deliverable.
    """
    section, sections, order = None, {}, []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[submodule"):
            section = line
            if section not in sections:
                sections[section] = ""
                order.append(section)
            continue
        if section and "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == "url":
                sections[section] = value.strip()
    for name in order:
        if not sections[name]:
            return name
    return None


def malformed_submodules(root):
    """The broken section name when ``.gitmodules`` exists and is malformed, else None."""
    path = Path(root) / ".gitmodules"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return submodule_without_url(text)


def download_patch(root, task, patch_dir, base, repo=""):
    """F10: fetch and apply the owned PR patch with submodule machinery out of the way.

    The recorded failure is ``fatal: No url found for submodule path during repo in
    .gitmodules``, which blocked delivery at a stage unrelated to the issue. Three
    guarantees, matching the blueprint:

    * every git invocation here runs with ``submodule.recurse=false`` because the patch
      concerns the top-level tree and downloading it must never initialise submodules;
    * a malformed ``.gitmodules`` is named ``InfrastructureFault("submodule")`` with the
      repository, so the class is visible instead of buried in a raw ``fatal:`` line;
    * therefore the failure can never be recorded as ``FAILED_ENGINEER``.

    Returns the patch path that was applied.
    """
    broken = malformed_submodules(root)
    if broken:
        raise InfrastructureFault("submodule", (repo + ": " if repo else "") +
                                  ".gitmodules is malformed: " + broken + " declares no url")
    number = int(task["owned_pr_number"])
    applied = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false",
                              "-C", str(root), "fetch", "upstream", "refs/pull/" + str(number) + "/head"],
                             capture_output=True, timeout=180)
    if applied.returncode:
        stderr = applied.stderr.decode("utf-8", errors="replace")
        if "submodule" in stderr.lower():
            raise InfrastructureFault("submodule", (repo + ": " if repo else "") + stderr.strip()[:500])
        raise RuntimeError(stderr)
    prior_head = git(root, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if prior_head != task["owned_head"]:
        raise ValueError("Owned PR changed since claim; reconcile before repair")
    ancestor = git(root, "merge-base", base, prior_head).stdout.decode().strip()
    patch = git(root, "diff", "--binary", ancestor, prior_head).stdout
    patch_file = Path(patch_dir) / "owned-pr.patch"
    patch_file.write_bytes(patch)
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false",
                             "-C", str(root), "apply", "--3way", str(patch_file)],
                            capture_output=True, timeout=180)
    if result.returncode:
        stderr = result.stderr.decode("utf-8", errors="replace")
        if "submodule" in stderr.lower():
            raise InfrastructureFault("submodule", (repo + ": " if repo else "") + stderr.strip()[:500])
        raise RuntimeError(stderr)
    return patch_file


def preflight(checks):
    """Pre-flight checks before Cline runs.

    Each check is a (subsystem, ok, detail) tuple. If any check fails,
    raises InfrastructureFault so the failure is classified as
    infrastructure, not engineering.
    """
    for subsystem, ok, detail in checks:
        if not ok:
            raise InfrastructureFault(subsystem, detail)


def check_disk_space(path, min_free_gb=5):
    """Check free disk space above a floor; returns (subsystem, ok, detail)."""
    import shutil
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        return "disk", free_gb >= min_free_gb, f"{free_gb:.1f} GB free (need {min_free_gb} GB)"
    except OSError:
        return "disk", False, "cannot read disk usage"


def check_free_memory(min_free_mb=512):
    """Check free memory above a floor."""
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        for line in meminfo.split("\n"):
            if line.startswith("MemAvailable:"):
                free_kb = int(line.split()[1])
                free_mb = free_kb / 1024
                return "memory", free_mb >= min_free_mb, f"{free_mb:.0f} MB free (need {min_free_mb} MB)"
    except (OSError, ValueError):
        pass
    return "memory", False, "cannot read memory info"


def check_executable(cmd, args=("--version",)):
    """Check an executable exists and is executable."""
    import shutil
    path = shutil.which(cmd)
    if path is None:
        return "executable", False, f"{cmd} not found on PATH"
    try:
        import subprocess
        result = subprocess.run([cmd] + list(args), capture_output=True, timeout=10)
        return "executable", result.returncode == 0, f"{cmd} version check returned {result.returncode}"
    except (OSError, subprocess.TimeoutExpired):
        return "executable", False, f"{cmd} not executable"


def check_git_version(min_version="2.20"):
    """Check git version is sufficient."""
    import subprocess
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return "git", False, "git version check failed"
        version_str = result.stdout.strip().split()[-1]
        version_parts = [int(x) for x in version_str.split(".")[:3]]
        min_parts = [int(x) for x in min_version.split(".")[:3]]
        if version_parts < min_parts:
            return "git", False, f"git {version_str} < {min_version}"
        return "git", True, f"git {version_str}"
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "git", False, "git version check failed"


def prepared_touched_files(prepared):
    """Derive the set of files the prepared plan will touch, from the contract-validated
    regression plan plus any source paths the plan names."""
    touched = set()
    plan = prepared.get("plan")
    if plan is not None:
        component = plan.component if hasattr(plan, "component") else None
        if component:
            touched.add(component)
        for attr in ("source_paths", "files", "touched"):
            paths = getattr(plan, attr, None) or prepared.get(attr, [])
            for p in paths:
                if isinstance(p, str):
                    touched.add(p)
    rp = prepared.get("regression_plan") or {}
    if isinstance(rp, dict):
        comp = rp.get("component")
        if comp:
            touched.add(comp)
    return touched


def baseline_overlap(comparison, touched):
    """Decide the prepared baseline's relationship to its declared branch.

    Pure decision: no network, no git. ``comparison`` is the GitHub compare payload and
    ``touched`` is the set of files the contract-validated plan will change.

    Returns ``(status, live_sha, overlap, unknown)``. A payload that carries no ``files``
    list cannot prove the patch is disjoint, so ``unknown`` is True and the caller refuses
    closed: a missing key is never evidence that upstream changed nothing (F1 test 7).
    """
    status = comparison.get("status")
    commits = comparison.get("commits") or []
    live_sha = commits[-1].get("sha") if commits else None
    if "files" not in comparison:
        return status, live_sha, set(), True
    moved = {entry["filename"] for entry in (comparison.get("files") or [])
             if isinstance(entry, dict) and entry.get("filename")}
    return status, live_sha, touched & moved, False


BASELINE_ADMITTED = ("identical", "ahead")


def require_baseline_relationship(status):
    """Refuse a prepared base that is not on the declared branch's line of history.

    The rule is ancestry-or-equality, which is exactly what the compare payload measures
    when it is asked about ``base_sha...base_branch``:

    * ``identical`` -- the base is the branch head. Admitted.
    * ``ahead``     -- the branch moved on; the base is still an ancestor. Admitted, and the
      per-file disjointness check decides whether the patch is safe (F1).
    * ``diverged``  -- the base is on some other line of history. The librepods artefact
      (``base_sha`` = ``android/rewrite`` HEAD declared as ``main``) is this case, and this
      is the refusal that must never be weakened.
    * ``behind``    -- the base is a *descendant* of the branch head, so it is not reachable
      from it either: commits that the branch does not have are baked in. Reachable only
      after a rewind or a force-push, and re-preparing is the only safe answer.

    Anything else -- including an unrecognised status -- is refused closed: an unproven
    relationship is never treated as a safe one.
    """
    if status in BASELINE_ADMITTED:
        return status
    if status == "diverged":
        raise ValueError("Prepared baseline is not the current upstream default")
    raise ValueError(
        "Prepared baseline is not on the declared base branch's history "
        f"(relationship {status!r})")


def resolve_base_branch(api, repo, prepared):
    """Resolve the declared base branch against the server's own branch list (F2).

    ``base_branch`` defaults to ``default_branch`` so every existing artefact stays valid.
    A branch the server does not have is a refusal -- no invention is possible. Only a
    genuine 404 becomes a refusal; a throttled or transient GitHub failure stays a failure
    so a slow API is never recorded as a bad declaration.
    """
    declared = prepared.get("base_branch") or prepared["default_branch"]
    try:
        branch = api.api(f"repos/{repo}/branches/{declared}")
    except GitHubError as exc:
        message = str(exc)
        if "HTTP 404" in message or "Not Found" in message or "Not found" in message:
            raise ValueError(
                f"Declared base branch {declared!r} does not exist in {repo}") from exc
        raise
    head = (branch or {}).get("commit") or {}
    if not head.get("sha"):
        raise ValueError(f"Branch {declared!r} returned no head commit")
    return declared, head["sha"]


def baseline_relationship(api, repo, prepared, receipt_path=None):
    """Resolve the declared base branch, measure the relationship, record it, then decide.

    This is the whole gate in one place so it can be exercised without a runner: the branch
    declaration is resolved against the server's own branch list (F2), the compare payload
    is measured (F1), the receipt is written before any verdict so a refusal explains itself,
    and only then does the decision raise.

    Returns the receipt document. Raises ``ValueError`` for a false or unknown declaration
    and ``PreparationRace`` when the baseline is genuinely stale under a correct patch.
    """
    base = prepared["base_sha"]
    base_branch, branch_head = resolve_base_branch(api, repo, prepared)
    prepared["base_branch"] = base_branch
    comparison = api.api(f"repos/{repo}/compare/{base}...{base_branch}")
    status, live_sha, overlap, unknown = baseline_overlap(
        comparison, prepared_touched_files(prepared))
    record = {
        "base": base, "base_branch": base_branch, "branch_head": branch_head,
        "live_sha": live_sha or base, "status": status,
        "ahead_by": comparison.get("ahead_by", 0),
        "overlap": sorted(overlap), "overlap_unknown": unknown,
    }
    # The relationship is recorded before it is judged: a refusal has to explain itself from
    # the artefact, and a raised exception would otherwise discard the only measurement.
    if receipt_path is not None:
        write_json_atomic(Path(receipt_path), record)
    require_baseline_relationship(status)
    if unknown:
        raise PreparationRace(base, record["live_sha"], set(), unknown=True,
                              ahead_by=record["ahead_by"])
    if overlap:
        raise PreparationRace(base, record["live_sha"], sorted(overlap),
                              ahead_by=record["ahead_by"])
    return record


def artifacts():
    root = Path(os.environ.get("FLEET_ARTIFACT_DIR", "fleet-artifacts")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def owner():
    return os.environ["GITHUB_RUN_ID"] + ":" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")


def output(**values):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            for key, value in values.items():
                if not re.fullmatch(r"[A-Za-z0-9_./:-]+", str(value)):
                    raise ValueError("Unsafe Actions output value")
                handle.write(f"{key}={value}\n")


def summary(result):
    """Echo a terminal outcome into the job summary.

    A refusal recorded only in an uploaded artifact reads, on the run page, exactly like a
    pipeline that quietly did nothing. Measured need: the 2026-10-27 delivery run ended with
    no PR and no visible reason until the step log was opened.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    status = str(result.get("status") or "")
    if not status:
        return
    detail = str(result.get("declared_reason") or result.get("reason") or result.get("error") or "")
    lines = ["### " + status, "",
             "- task: `" + str(result.get("task_id") or "unknown") + "`"]
    if result.get("repo"):
        lines.append("- issue: `" + str(result["repo"]) + "#" + str(result.get("issue_number", "")) + "`")
    if detail:
        lines.append("- reason: " + " ".join(detail.split())[:600])
    if result.get("pr_url"):
        lines.append("- pull request: " + str(result["pr_url"]))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def reject_preparation(blocked, task, repo, number):
    """Record a verified preparation refusal as terminal and stop the chain here.

    The refusal is not a fault: Cline inspected the repository and returned
    ``action=blocked`` with its actual diagnosis, and the contract verified that answer
    before this host saw it. Retrying would buy the same verdict again, so the run ends with
    the verdict written down, its evidence attached, and the publish job unarmed.
    """
    report = getattr(blocked, "report", None) or {}
    result = {"status": "REJECTED_PREPARATION", "at": utcnow(),
              "task_id": task.get("task_id"), "repo": repo, "issue_number": number,
              "reason": str(blocked), "declared_reason": report.get("reason", ""),
              "evidence": {"action": report.get("action"), "worktree": report.get("worktree", ""),
                           "base_sha": report.get("base_sha", ""),
                           "default_branch": report.get("default_branch", ""),
                           "sources": report.get("sources", []),
                           "run_url": task.get("run_url", ""),
                           "admission": (task.get("admission") or {}).get("funding")}}
    write_json(artifacts() / "engineering-result.json", result)
    output(verdict="rejected_preparation")
    summary(result)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def claim(event_file):
    event = read_json(event_file)
    payload = event.get("client_payload") or event.get("inputs") or {}
    mode = payload.get("mode", "deliver")
    if mode == "canary":
        output(mode="canary", task_id="canary")
        write_json(artifacts() / "claim.json", {"mode": "canary", "owner": owner()})
        return
    if mode != "deliver":
        raise ValueError("Unknown task mode")
    repo = repository(payload.get("repo") or payload.get("target_repo"))
    number = issue_number(payload.get("issue_number"))
    identity = task_id(repo, number)
    api, store = GitHub(), StateStore()
    old, _ = store.read(identity)
    context = api.issue_context(repo, number)
    proof, reason = admit(context, quote=quote)
    if not proof:
        raise ValueError("Admission blocked: " + reason)
    competition(api, repo, number, own_head=(old or {}).get("head_sha"))
    recovery = (os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
                and str(payload.get("force_recovery", "")).lower() == "true")
    try:
        budget_seconds = int(payload.get("preparation_budget_seconds"))
    except (TypeError, ValueError):
        budget_seconds = None
    state = store.claim(repo, number, owner(),
                        f"https://github.com/{store.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
                        os.environ["GITHUB_SHA"], recovery, budget_seconds=budget_seconds)
    context.update(task_id=identity, admission=proof, prior_failures=state.get("failures", []),
                   owned_pr=state.get("pr_url"), owned_head=state.get("head_sha"),
                   owned_pr_number=state.get("pr_number"))
    write_json(artifacts() / "claim.json", {"mode": "deliver", "context": context, "state": state})
    output(mode="deliver", task_id=identity)


def runtime():
    os.environ.setdefault("FLEET_SANDBOX_DIR", str(Path(tempfile.gettempdir()) / "bounty-workspaces"))
    os.environ.setdefault("FLEET_ARTIFACT_DIR", str(artifacts()))
    os.environ.setdefault("CLINE_DATA_DIR", str(Path(tempfile.gettempdir()) / "bounty-cline"))
    os.environ["ACTIONS_PUBLISHER_MANAGED"] = "1"
    import kaggle_engine_worker as worker
    ok, diagnostic = worker.configure_cline_for_engine()
    if not ok:
        raise RuntimeError(diagnostic)
    # Remove credentials from ordinary child environments. This is not a
    # hostile-code sandbox; write credentials live in the separate publisher job.
    for name in list(os.environ):
        if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|GH_PAT", name, re.I):
            os.environ.pop(name, None)
    status = worker.cline_proxy_router_status()
    if status["states"].get("READY", 0) < 1:
        raise RuntimeError("Gateway has no ready provider key")
    ok, diagnostic = worker.verify_cline_provider_wire()
    if not ok:
        raise RuntimeError(diagnostic)
    write_json(artifacts() / "model-wire.json", {"at": utcnow(), "diagnostic": diagnostic,
                                               "gateway": worker.cline_proxy_router_status()})
    return worker


def engineer():
    document = read_json(artifacts() / "claim.json")
    api = GitHub()  # retain read token only in the host transport object
    worker = runtime()
    if document["mode"] == "canary":
        write_json(artifacts() / "engineering-result.json", {"status": "CANARY_PASSED", "at": utcnow(),
                                               "harness_sha": os.environ["GITHUB_SHA"]})
        return
    # F6: a velocity-contended dispatch carries a shorter preparation window in its payload.
    # An absent or unusable value leaves the four-hour budget untouched, because an unmeasured
    # velocity must never shorten a legitimate run.
    cline_budget = int(os.environ.get("CLINE_TOTAL_BUDGET_SECONDS", "14400"))
    try:
        preferred = int(os.environ.get("PREPARATION_BUDGET_SECONDS", "") or 0)
    except (TypeError, ValueError):
        preferred = 0
    if 0 < preferred < cline_budget:
        cline_budget = preferred
    worker.set_cline_execution_budget(cline_budget)
    print(json.dumps({"phase": "CLINE_BUDGET", "total_seconds": cline_budget}), flush=True)
    task, state = document["context"], document["state"]
    repo, number = task["repo"], task["issue_number"]
    lease = SimpleNamespace(run_id=state["owner"], attempt=state["attempt"], lost=threading.Event(),
                            phase="CLINE_INTAKE", command_pid=0)
    try:
        prepared = worker.run_cline_claim_intake(task, lease)
    except worker.PreparationBlocked as blocked:
        # Terminal for this dispatch: the refusal reason was already verified, so the chain
        # stops here instead of being reported as a broken engineering phase.
        reject_preparation(blocked, task, repo, number)
        return
    root, base = prepared["worktree"], prepared["base_sha"]
    try:
        # F1+F2: one gate. The declared branch is resolved server-side, the prepared base
        # must still sit on that branch's history, no file the plan touches may have moved,
        # and the relationship is recorded before any verdict is reached.
        baseline_record = baseline_relationship(
            api, repo, prepared, artifacts() / "baseline-relationship.json")
        # F2: the resolved declaration travels with the release receipt, so publication
        # checks currency against the branch the patch was actually built on instead of
        # silently falling back to the default branch.
        base_branch = baseline_record["base_branch"]
        if git(root, "remote", "get-url", "upstream").stdout.decode().strip().removesuffix(".git") != (
                "https://github.com/" + repo):
            raise ValueError("Unexpected upstream remote")
        plan = prepared["plan"]
        validate_plan_contract(plan, prepared.get("report_path"))
        component = prepared.get("regression_plan", {}).get("component")
        if not component or not safe_path(root, component).is_file():
            raise ValueError("Cline must identify the actual existing defect component")
        baseline_ok, diagnostic, baseline = worker.verify_baseline(root, plan)
        if not baseline_ok:
            repaired, plan, repair_error = worker.cline_supervise_delivery_phase(
                root, repo, number, "baseline", diagnostic, plan)
            if not repaired:
                raise RuntimeError("BLOCKED_BASELINE: " + repair_error)
            validate_plan_contract(plan, prepared.get("report_path"))
            baseline_ok, diagnostic, baseline = worker.verify_baseline(root, plan)
        if not baseline_ok:
            raise RuntimeError("BLOCKED_BASELINE: " + diagnostic)
        if status_paths(root):
            raise ValueError("Provisioning mutated the untouched source baseline")
        if state.get("previous_owner") and not task.get("owned_pr"):
            prior_run = state["previous_owner"].split(":")[0]
            if not prior_run.isdecimal():
                raise ValueError("Invalid previous run identity")
            recovery_dir = artifacts() / "previous-run"
            environment = dict(os.environ)
            if api.token:
                environment["GH_TOKEN"] = api.token
            downloaded = subprocess.run(["gh", "run", "download", prior_run,
                "--repo", os.environ["GITHUB_REPOSITORY"], "--name", "task-engineering-" + prior_run,
                "--dir", str(recovery_dir)], env=environment, capture_output=True, timeout=180)
            if downloaded.returncode:
                write_json(artifacts() / "recovery.json", {"status": "NO_PRIOR_ARTIFACT_AVAILABLE", "run": prior_run})
            else:
                checkpoints = []
                import zipfile
                for archive in recovery_dir.glob("cline-recovery/*.zip"):
                    with zipfile.ZipFile(archive) as saved:
                        if "checkpoint.json" in saved.namelist():
                            info = json.loads(saved.read("checkpoint.json"))
                            checkpoints.append((info["at"], archive))
                if checkpoints:
                    archive = max(checkpoints)[1]
                    try:
                        recovery = restore_checkpoint(root, base, archive)
                    except ValueError as exc:
                        recovery = {"status": "REQUIRES_CLINE_RECONCILIATION", "archive": str(archive),
                                    "diagnostic": str(exc)}
                    write_json(artifacts() / "recovery.json", recovery)
        # Resume the real owned patch after checking the untouched current base.
        # Source is fetched as Git objects; no credentials are given to Cline.
        if task.get("owned_pr_number"):
            # F10: submodule machinery stays out of the patch path (see download_patch).
            download_patch(root, task, artifacts(), base, repo)
        regression_file = artifacts() / "regression.json"
        body = task["body"] + (
            "\n\nDelivery contract: write " + str(regression_file) + " as JSON with "
            "test_files (new companion test paths), argv (the exact native regression command), "
            "expected_failure (a specific defect assertion, minimum 12 characters). "
            "The host runs these tests with actual upstream product source restored, then with your fix. "
            "Do not modify any existing master test or verification configuration. "
            "Do not commit, push, create a fork or publish. Preserve complete issue context at "
            + prepared["context_path"] + "."
        )
        if (artifacts() / "recovery.json").exists():
            body += "\nRead retained previous-run edits and recovery evidence at " + str(artifacts() / "recovery.json")
        if task.get("owned_pr"):
            body += "\nRepair this same owned PR: " + task["owned_pr"] + "\n" + json.dumps(task["prior_failures"])
        arch = prepared["architecture"]
        arch["full_delivery_context"] = prepared["context_path"]
        cases = worker.model_scenarios(task["title"], body, arch)
        feedback = json.dumps(task.get("prior_failures", []))

        # F3's write-early skeleton belongs to the worker, at Cline's real report path
        # (folder/<identity>.preparation.json). A copy written here would land at a
        # different path, after Cline had already run, and could never be replaced by it.
        # The worker therefore reports the path it used, and the release loop below re-reads
        # that file after every turn. Assuming a path here raised NameError on the first run
        # that reached this line (2026-10-29, run 40876500657).
        report_path = Path(prepared["report_path"])
        # F7: Pre-flight checks before Cline runs.
        preflight([
            check_disk_space(".", min_free_gb=5),
            check_free_memory(min_free_mb=512),
            check_executable("git", ("--version",)),
            check_git_version("2.20"),
        ])
        for release_turn in range(1, 4):
            ok, run, diagnostic = worker.run_engineering_iteration_loop(
                root, repo, number, task["title"], body, arch, plan, cases, base,
                max_iterations=1, initial_feedback=feedback)
            if not ok:
                feedback = diagnostic
                worker.preserve_cline_edits(root)
                if worker.cline_turn_timeout_seconds() <= 0:
                    # A resource outcome, not a verdict on the code: the run's own clock
                    # ended. Typed so the ledger can say so instead of FAILED_ENGINEER.
                    raise ClineBudgetExhausted(cline_budget)
                continue
            # F3: Cline reported success but produced no verification receipt at all.
            # This is not an engineering failure: Cline ran and exited, but the
            # artefact contract was not satisfied.
            if not report_path.exists():
                raise ClineDeliverableMissing(report_path, elapsed=None, exit_code=0)
            # F3: Validate the report before any downstream phase reads it.
            report = read_json(report_path)
            validate_preparation(report, report_path)
            try:
                if git(root, "rev-parse", "HEAD").stdout.decode().strip() != base:
                    raise ValueError("Cline changed Git HEAD before release verification")
                paths = status_paths(root)
                protect_baseline_tests(root, base, paths)
                if not product_paths(paths):
                    raise ValueError("No issue-linked product change; no-op/docs/lockfile-only release blocked")
                regression = regression_proof(
                    root, base, read_json(regression_file),
                    lambda argv: worker.run_command_safe(argv, cwd=root, timeout=3600))
                before = manifest(root, status_paths(root))
                final_commands = plan.builds + worker.verification_test_commands(plan) + plan.linters + plan.format_checks
                final = [worker.run_command_safe(argv, cwd=root, timeout=3600) for argv in final_commands]
                results = [asdict(row) for row in final]
                evidence_file = artifacts() / f"release-verification-{release_turn}.json"
                write_json(evidence_file, results)
                require_commands(final_commands, results)
                if manifest(root, status_paths(root)) != before:
                    raise ValueError("Native verification changed the proposed source tree")
                break
            except (ValueError, RuntimeError, OSError) as exc:
                feedback = ("Independent release verification failed: " + str(exc) +
                            "\nRead complete native receipts at " + str(artifacts()) +
                            ". Repair the actual failure, preserving completed edits and master tests.")
                worker.preserve_cline_edits(root)
        else:
            raise RuntimeError("Bounded Cline delivery repair exhausted: " + feedback)
        git(root, "diff", "--check")
        git(root, "config", "user.name", BOUNTY_ACCOUNT)
        git(root, "config", "user.email", "isearch.xsolve@gmail.com")
        git(root, "add", "--", *paths)
        git(root, "-c", "commit.gpgsign=false", "commit", "-m", f"fix: #{number} - {task['title']}")
        head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
        if git(root, "rev-list", "--count", base + ".." + head).stdout.strip() != b"1":
            raise ValueError("Expected exactly one verified task commit")
        git(root, "bundle", "create", str(artifacts() / "release.bundle"), "HEAD", "^" + base)
        receipt = {"schema": 1, "status": "VERIFIED", "task_id": task["task_id"],
                   "repo": repo, "issue_number": number, "owner": state["owner"],
                   "harness_sha": os.environ["GITHUB_SHA"], "base_sha": base, "head_sha": head,
                   "tree_sha": git(root, "rev-parse", "HEAD^{tree}").stdout.decode().strip(),
                   "default_branch": prepared["default_branch"],
                   "base_branch": base_branch, "files": before,
                   "plan": asdict(plan), "sources": prepared["sources"], "regression": regression,
                   "baseline": [asdict(r) for r in baseline], "verification": results,
                   "admission": task["admission"], "run_url": state["run_url"], "at": utcnow()}
        write_json(artifacts() / "release.json", receipt)
        write_json(artifacts() / "engineering-result.json", {"status": "VERIFIED", "head_sha": head,
                                               "task_id": task["task_id"], "at": utcnow()})
        # The publish job is gated on this verdict alone: a refusal must never arm it.
        output(verdict="verified")
    finally:
        if Path(root, ".git").exists():
            worker.preserve_cline_edits(root)


def validate_bundle(receipt, bundle, root):
    """Runs no target code and requires the actual committed object/diff proof."""
    if receipt.get("status") != "VERIFIED" or receipt.get("harness_sha") != os.environ["GITHUB_SHA"]:
        raise ValueError("Release/harness provenance mismatch")
    repo, number = repository(receipt["repo"]), issue_number(receipt["issue_number"])
    if task_id(repo, number) != receipt["task_id"]:
        raise ValueError("Release task identity mismatch")
    # F10: Disable submodule recursion to avoid .gitmodules failures blocking delivery.
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false",
                    "clone", "--no-checkout",
                    "https://github.com/" + repo + ".git", str(root)], check=True, timeout=180)
    git(root, "fetch", str(bundle), "HEAD")
    head, base = receipt["head_sha"], receipt["base_sha"]
    if git(root, "rev-parse", "FETCH_HEAD").stdout.decode().strip() != head:
        raise ValueError("Bundle HEAD mismatch")
    if git(root, "rev-list", "--count", base + ".." + head).stdout.strip() != b"1":
        raise ValueError("Release is not one task commit")
    if git(root, "show", "-s", "--format=%P", head).stdout.decode().split() != [base]:
        raise ValueError("Release must have exactly the verified upstream parent")
    if git(root, "rev-parse", head + "^{tree}").stdout.decode().strip() != receipt["tree_sha"]:
        raise ValueError("Release tree mismatch")
    paths = [os.fsdecode(p) for p in git(root, "diff", "--name-only", "-z", base, head).stdout.split(b"\0") if p]
    if set(paths) != set(receipt["files"]) or not product_paths(paths):
        raise ValueError("Changed-file release proof mismatch")
    protect_baseline_tests(root, base, paths, head_sha=head)
    for name in paths:
        safe_path(root, name)
        blob = git(root, "show", head + ":" + name, check=False)
        proof = receipt["files"][name]
        if proof.get("deleted"):
            if blob.returncode == 0:
                raise ValueError("Deletion proof mismatch")
        elif blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != proof["sha256"]:
            raise ValueError("File content proof mismatch")
        mode = git(root, "ls-tree", head, "--", name).stdout.split(b" ", 1)[0]
        if mode in (b"120000", b"160000"):
            raise ValueError("Symlink/submodule release requires separate review")
    for source in receipt["sources"]:
        if hashlib.sha256(git(root, "show", base + ":" + source["path"]).stdout).hexdigest() != source["sha256"]:
            raise ValueError("Native-plan source citation mismatch")
    plan = SimpleNamespace(**receipt["plan"])
    validate_plan_contract(plan, bundle)
    require_commands(plan.baseline_tests, receipt["baseline"])
    commands = plan.builds + plan.baseline_tests + plan.targeted_tests + plan.final_tests + plan.linters + plan.format_checks
    require_commands(commands, receipt["verification"])
    if receipt["regression"]["red_exit"] == 0 or receipt["regression"]["green_exit"] != 0:
        raise ValueError("Red-to-green regression proof missing")
    git(root, "diff", "--check", base, head)
    return repo, number, head


def is_self_owned(account, repo):
    """True when the bounty account owns the target repository itself.

    There is no fork in that case: the head branch is pushed to the same repository and the
    metadata carries no ``parent``. Measured 2026-10-29 on the proof fixture, where the
    fork-parent gate refused to publish a head commit that was already correct:
    ``ValueError: Fork parent mismatch``.
    """
    return bool(account) and repo.lower().startswith(str(account).lower() + "/")


def engagement_comment(receipt, context, pr_url, head):
    """Build and post the six-part founder-facing report on the ORIGINAL issue.

    The delivery pipeline's verified evidence is the only thing that may ever appear in
    public: base/head SHAs, the native verification rows (argv, exit code, duration) and
    the execution receipt. ``outreach_report.build_report`` refuses to build without
    proof and refuses any body carrying payment coordinates (Silo Guide 3.3 / Startup
    Guide 4: rails belong in a private channel after the founder replies).
    """
    from outreach_report import build_report, MissingEvidence
    repo = context["repo"]
    number = context["issue_number"]
    rows = receipt.get("verification") or []
    steps = ["On the proposed head, run: " + " ".join(r.get("argv") or []) for r in rows[:4]] or ["Inspect the diff of " + pr_url]
    proof = [
        f"Verified base {receipt.get('base_sha')} -> head {head}",
        *(f"`{' '.join(r.get('argv') or [])}` exit {r.get('exit_code')}, {r.get('duration_s') or 0:.2f}s"
          for r in rows[:5]),
        f"Execution receipt: {receipt.get('run_url')}",
    ]
    body = build_report(
        impact=f"A native-verified fix for issue #{number} ({context['title']}) is submitted as "
               f"pull request {pr_url}.",
        affected=f"Maintainers and users of {repo} who hit the failure described in #{number}.",
        steps=steps,
        proof=proof,
        fix=f"Apply pull request {pr_url} on top of {receipt.get('base_sha')}.",
        detail=f"Engine run: {receipt.get('run_url')}",
        repo=repo,
    )
    api = GitHub()
    api.api(f"repos/{repo}/issues/{number}/comments", "POST", {"body": body})
    print(json.dumps({"phase": "ENGAGEMENT_COMMENT_POSTED", "repo": repo,
                      "issue_number": number, "pr_url": pr_url}), flush=True)


# Measured 2026-10-30: 64 external PRs, 47 closed unmerged, **0 reviewed and 0 merged**, while the
# account's only merge was our own `bounty-proof#6`. The missing step was not the patch. Both
# platforms require an explicit claim command, and neither pays on merge: Opire's docs say
# "Claiming a bounty never creates an automatic payment... that creator arranges payment", and
# Algora's bot asks the maintainer to "visit your org dashboard to reward". Without the claim the
# payer is never even notified. The token is emitted only where a platform bot has spoken, because
# a bare /claim on a non-platform issue is the "vibe code bounty tracker" signal that fyne#1062
# pushed back on in public.
_CLAIM_BOTS = frozenset(bot.replace("[bot]", "").lower() for bot in TRUSTED_BOTS)


def claim_line(context, number):
    """The platform claim command for this issue, or "" when no claimable platform is present.

    Pure: reads only what ``issue_context`` returned. Only a comment authored by a trusted bounty
    bot counts, never prose that merely mentions a platform - a maintainer writing "this is not an
    algora bounty" must not make us claim.
    """
    for comment in context.get("comments") or ():
        login = str((comment.get("user") or {}).get("login") or "").replace("[bot]", "").lower()
        if login and login in _CLAIM_BOTS:
            return "/claim #%d" % int(number)
    return ""


def pr_body(context, number, receipt, head, rows, claim=""):
    """The public PR body. ``claim`` is the platform claim command, empty when none applies."""
    return (f"Resolves #{number}: {context['title']}.\n\n"
            + (claim + "\n\n" if claim else "")
            + f"Verified base: {receipt['base_sha']}\nVerified head: {head}\n\n"
            "Regression: the companion test fails on the upstream source and passes with this change.\n\n"
            "Native verification:\n" + "\n".join(
                f"- {json.dumps(r['argv'])}: exit {r['exit_code']}, {r['duration_s']:.2f}s" for r in rows)
            + "\n\nExecution receipt: " + receipt["run_url"])


def post_claim(api, repo, pr_number, claim):
    """Claim an already-open PR.

    Both platforms read the command when content is *created* and ignore edits afterwards, so an
    edited body is not a claim - a new PR comment is. Failure is recorded and never hides the fact
    that the delivery itself succeeded.
    """
    try:
        api.api(f"repos/{repo}/issues/{pr_number}/comments", "POST", {"body": claim})
        print(json.dumps({"phase": "CLAIM_POSTED", "repo": repo, "pr": pr_number,
                          "claim": claim}), flush=True)
        return True
    except (GitHubError, OSError, ValueError) as exc:
        print(json.dumps({"phase": "CLAIM_POSTED_FAILED", "repo": repo, "pr": pr_number,
                          "claim": claim, "error": str(exc)[:300]}), flush=True)
        return False


def publish():
    receipt = read_json(artifacts() / "release.json")
    api, store = GitHub(), StateStore()
    identity, run_owner = receipt["task_id"], owner()
    state, _ = store.read(identity)
    if not state or state.get("owner") != run_owner or receipt["owner"] != run_owner:
        raise ValueError("Publication lease ownership lost")
    root = Path(tempfile.mkdtemp()) / "objects"
    repo, number, head = validate_bundle(receipt, artifacts() / "release.bundle", root)
    context = api.issue_context(repo, number)
    proof, reason = admit(context, quote=quote)
    if not proof:
        raise ValueError("Release funding/issue state blocked: " + reason)
    competition(api, repo, number, own_head=state.get("head_sha") or head)
    current_base = api.api(f"repos/{repo}/commits/{receipt.get('base_branch') or receipt['default_branch']}")["sha"]
    if current_base != receipt["base_sha"]:
        raise ValueError("Upstream base changed after native verification; rebase and reverify before publication")
    account = api.api("user")["login"]
    name = repo.split("/")[1]
    if not is_self_owned(account, repo):
        try:
            fork = api.api(f"repos/{account}/{name}")
        except GitHubError as exc:
            if "404" not in str(exc):
                raise
            fork = api.api(f"repos/{repo}/forks", "POST", {"default_branch_only": True})
        if (fork.get("parent") or {}).get("full_name", "").lower() != repo.lower():
            fork = api.api(f"repos/{account}/{name}")
            if (fork.get("parent") or {}).get("full_name", "").lower() != repo.lower():
                raise ValueError("Fork parent mismatch")
    branch = state.get("branch") or f"fix/bounty-{number}-{identity[:6]}-{state['attempt']}"
    prior_head = state.get("head_sha")
    store.owned_update(identity, run_owner, status="PUBLISHING", proposed_head=head,
                       proposed_branch=branch, verified_run=receipt["run_url"])
    subprocess.run(["gh", "auth", "setup-git"], check=True, timeout=30)
    lease = [f"--force-with-lease=refs/heads/{branch}:{prior_head}"] if state.get("pr_number") else []
    git(root, "push", *lease, f"https://github.com/{account}/{name}.git", head + ":refs/heads/" + branch)
    # Recover a server-acknowledged PR after an earlier client timeout.
    existing = [p for p in api.pages(f"repos/{repo}/pulls", state="open")
                if p["head"]["sha"] == head and p["head"]["repo"]
                and p["head"]["repo"]["owner"]["login"] == account]
    if len(existing) > 1:
        raise ValueError("Multiple matching PRs need reconciliation")
    rows = receipt["verification"]
    claim = claim_line(context, number)
    body = pr_body(context, number, receipt, head, rows, claim)
    if existing:
        pr = api.api(f"repos/{repo}/pulls/{existing[0]['number']}", "PATCH", {"body": body})
        if claim:
            # An edited body is not a new creation, so an already-open PR is claimed by comment.
            post_claim(api, repo, pr["number"], claim)
    else:
        competition(api, repo, number)
        pr = api.api(f"repos/{repo}/pulls", "POST",
                     {"head": account + ":" + branch,
                      "base": receipt.get("base_branch") or context["repository"]["default_branch"],
                      "title": f"fix: #{number} - {context['title']}", "body": body})
    store.owned_update(identity, run_owner, status="PUBLISHED_PENDING_CHECKS", pr_url=pr["html_url"],
                       pr_number=pr["number"], head_sha=head, branch=branch,
                       release_digest=hashlib.sha256((artifacts() / "release.json").read_bytes()).hexdigest())
    write_json(artifacts() / "publication.json", {"status": "PUBLISHED_PENDING_CHECKS", "pr_url": pr["html_url"],
                                               "head_sha": head, "at": utcnow()})
    try:
        engagement_comment(receipt, context, pr["html_url"], head)
    except (GitHubError, OSError, ValueError) as exc:
        # The PR is the deliverable and is already live. A comment that fails to post is
        # recorded loudly, never silently: the platforms notify the payer only through the
        # claim, so a lost engagement comment is a real loss worth reporting - but it must not
        # fail a run whose delivery already succeeded. Corrected 2026-10-30: the claim itself
        # never belonged on the issue (Opire: the command works "in a comment on a PR and in the
        # same description of the PR", never on an issue), so publication claims on the PR.
        print(json.dumps({"phase": "ENGAGEMENT_COMMENT_FAILED", "repo": repo,
                          "issue_number": number, "pr_url": pr["html_url"],
                          "error": str(exc)[:300]}), flush=True)


def terminal_result(folder, job_status):
    """The record a finished run leaves, inferred from what it wrote.

    The one failure class the taxonomy exists for used to be unclassifiable here. A SIGTERM
    (``exit_143``) kills the Python process before any ``except`` block can run, so neither
    ``engineering-result.json`` nor ``*-failure.json`` is written, and the run was recorded
    as ``FAILED_MISSING_RECEIPT`` -- an absent record treated as an absent receipt. Measured
    twice on 2026-10-29 (runs 40862366271 and 40862319897).

    Writing nothing while exiting non-zero is only possible if the phase was terminated
    before it could report, so that case is classified ``FAILED_RUNNER_SHUTDOWN`` and
    flagged ``inferred``: the conclusion comes from the absence of both files, never from an
    observation, and an inference must never be recorded as one.
    """
    folder = Path(folder)
    result_file = folder / "engineering-result.json"
    if result_file.exists():
        return read_json(result_file)
    for phase in ("engineer", "publish"):
        failure = folder / (phase + "-failure.json")
        if failure.exists():
            return read_json(failure)
    if job_status != "success":
        return {"status": "FAILED_RUNNER_SHUTDOWN", "kind": "runner_shutdown",
                "retryable": True, "inferred": True,
                "diagnostic": "No engineering result and no failure record: the phase was "
                              "terminated before it could report (exit 143 / runner shutdown)",
                "at": utcnow()}
    return {"status": "FAILED_MISSING_RECEIPT"}


def finish(job_status):
    store = StateStore()
    path = artifacts() / "claim.json"
    if not path.exists():
        return
    claim_doc = read_json(path)
    if claim_doc["mode"] == "canary":
        result = read_json(artifacts() / "engineering-result.json") if (artifacts() / "engineering-result.json").exists() else {}
        print(json.dumps({"mode": "canary", "job_status": job_status, "result": result}))
        return
    identity = claim_doc["context"]["task_id"]
    previous, _ = store.read(identity)
    if not previous or previous.get("owner") != owner():
        raise ValueError("Result owner mismatch")
    publication = artifacts() / "publication.json"
    result = terminal_result(artifacts(), job_status)
    if publication.exists():
        result = read_json(publication)
    elif str(result.get("status", "")).startswith("REJECTED_"):
        # A verified refusal is a terminal outcome, not a fault. The engineering phase ran,
        # the contract verified the answer, and the verdict is the deliverable. Prefixing it
        # with FAILED_ (as every non-published run did until now) erases the reason and
        # reports a correct decision as a broken pipeline: measured 2026-10-27, when a
        # by-design refusal on Expensify/App#105153 surfaced as FAILED_ENGINEER.
        pass
    elif job_status != "success" or result.get("status") != "VERIFIED":
        result["status"] = "FAILED_" + str(result.get("status", job_status)).removeprefix("FAILED_")
    else:
        result["status"] = "FAILED_PUBLICATION_MISSING"
    if result["status"].startswith("FAILED"):
        result["failures"] = [*previous.get("failures", []),
                              {"run_url": previous.get("run_url"), **result}]
    store.owned_update(identity, owner(), **result, finished_at=utcnow())
    summary(result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["claim", "engineer", "publish", "finish"])
    parser.add_argument("--event-file", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--job-status", default="failure")
    args = parser.parse_args()
    try:
        if args.phase == "claim":
            claim(args.event_file)
        elif args.phase == "engineer":
            engineer()
        elif args.phase == "publish":
            publish()
        else:
            finish(args.job_status)
    except PreparationRace as exc:
        # F4: preparation race is retryable, never an engineer failure.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_PREPARATION_RACE",
                    "kind": "preparation_race", "retryable": True,
                    "diagnostic": str(exc),
                    "base": exc.base, "live_sha": exc.live_sha,
                    "ahead_by": exc.ahead_by,
                    "overlap": sorted(exc.overlap), "overlap_unknown": exc.unknown,
                    "at": utcnow()})
        raise
    except ClineBudgetExhausted as exc:
        # F4: the budget ended while the agent was still working -- no code was judged.
        # Previously a RuntimeError, which the blanket handler stamped FAILED_ENGINEER and
        # made an out-of-time run indistinguishable from a broken patch.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_BUDGET_EXHAUSTED",
                    "kind": "budget", "retryable": True,
                    "diagnostic": str(exc),
                    "budget_seconds": exc.budget_seconds,
                    "at": utcnow()})
        raise
    except ClineDeliverableMissing as exc:
        # F4: Cline produced no receipt at all -- machine/infrastructure issue,
        # never an engineer failure.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_DELIVERABLE_MISSING",
                    "kind": "deliverable_missing", "retryable": True,
                    "diagnostic": str(exc),
                    "path": exc.path, "elapsed": exc.elapsed, "exit_code": exc.exit_code,
                    "at": utcnow()})
        raise
    except ClineDeliverableInvalid as exc:
        # F4 closes the deliverable status set at Missing plus Invalid. A malformed,
        # skeleton, or contract-violating receipt is a deliverable that did not arrive
        # in a usable form, so it lands under the same status and carries its reason in
        # ``kind`` and ``reason`` rather than inventing a status the ledger never defined.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_DELIVERABLE_MISSING",
                    "kind": "deliverable_invalid", "retryable": True,
                    "diagnostic": str(exc),
                    "path": exc.path, "reason": exc.reason,
                    "at": utcnow()})
        raise
    except RunnerShutdown as exc:
        # F4: Runner shutdown mid-delivery -- infrastructure fault, not engineer failure.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_RUNNER_SHUTDOWN",
                    "kind": "runner_shutdown", "retryable": True,
                    "diagnostic": str(exc),
                    "inferred": exc.inferred,
                    "message": exc.message,
                    "at": utcnow()})
        raise
    except InfrastructureFault as exc:
        # F4: Infrastructure fault -- disk, network, executable install, toolchain.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_INFRASTRUCTURE",
                    "kind": "infrastructure", "retryable": True,
                    "diagnostic": str(exc),
                    "subsystem": exc.subsystem,
                    "detail": exc.detail,
                    "at": utcnow()})
        raise
    except Exception as exc:
        # Genuine engineering failure: everything that is not an infrastructure,
        # delivery-contract, or preparation-race fault.
        write_json(artifacts() / (args.phase + "-failure.json"),
                   {"status": "FAILED_" + args.phase.upper(),
                    "kind": "engineer", "retryable": True,
                    "diagnostic": str(exc), "at": utcnow()})
        raise


if __name__ == "__main__":
    main()
