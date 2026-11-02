"""Trusted release validation: exact paths, native receipts and real regression."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

from delivery_errors import PreparationContractViolation


def git(root, *args, check=True):
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                            capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result


def safe_path(root, name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or "\\" in name or any(p in ("..", ".git") for p in path.parts):
        raise ValueError("Unsafe worktree path")
    if name.startswith(".github/workflows/"):
        raise ValueError("Workflow mutation is prohibited")
    target = Path(root) / name
    if target.is_symlink() or not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Symlink/worktree boundary violation")
    return target


def status_paths(root):
    entries = iter(git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z").stdout.split(b"\0"))
    paths = []
    for entry in entries:
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise ValueError("Malformed Git status")
        paths.append(os.fsdecode(entry[3:]))
        if b"R" in entry[:2] or b"C" in entry[:2]:
            original = next(entries, b"")
            if not original:
                raise ValueError("Missing rename/copy source")
            paths.append(os.fsdecode(original))
    for path in paths:
        safe_path(root, path)
    return sorted(set(paths))


def restore_tracked_files(root):
    """Return every tracked worktree file to its committed bytes; leave untracked trees alone.

    A package manager installing the baseline's dependencies may rewrite a tracked manifest:
    npm 7+ updates package-lock.json even under ``--no-save`` (and this pipeline's own plan
    generator proposes a plain ``npm install``), yarn writes yarn.lock on every install. Those
    bytes are provisioning's, not engineering's -- ``node_modules`` and build outputs are
    untracked or ignored, so restoring the tracked files returns the baseline to its own
    commit while the installed tree stays in place and usable.

    Measured 2026-11-01: OpenOrg-gg/AmphoraProtocol#4 (run 41357319521) and
    Manthan-cpp/GramRaksha-AI#2 both aborted seconds before engineering began, because their
    bootstrap rewrote the tracked lockfile and the untouched-baseline gate read that as the
    engineer having touched the source. Cline had verified the opposite -- it ran the same
    install and proved ``git status`` clean -- so the mutation belonged to provisioning, whose
    checkout it is.

    Untracked files are never removed: a regression test authored for this delivery, an
    artifact directory or an installed ``node_modules`` survives, because only committed
    content is restored.
    """
    git(root, "checkout", "HEAD", "--", ".")
    return status_paths(root)


def guard_untouched_baseline(root):
    """Prove the baseline is untouched after provisioning, discarding provisioning's own writes.

    Two different things appear in ``git status`` here and they are not the same fault. A
    package manager installing the baseline's dependencies may rewrite a tracked manifest:
    that write belongs to provisioning, whose checkout it was, and it is discarded. A change
    in the delivered tree does not: it is either an earlier phase's contract violation or a
    sign the verified tree is not the tree engineering will build on, so it fails loudly with
    the paths named rather than as an anonymous "the baseline moved".

    Measured 2026-11-01: OpenOrg-gg/AmphoraProtocol#4 (run 41357319521) and
    Manthan-cpp/GramRaksha-AI#2 both aborted seconds before engineering began because their
    bootstrap rewrote the tracked lockfile and this gate read it as a mutated source. Cline
    had run the same install itself and verified ``git status`` clean, so the write was never
    engineering's to answer for.
    """
    changed = status_paths(root)
    delivered = product_paths(changed)
    if delivered:
        raise ValueError("Repository tree changed before engineering: " + ", ".join(delivered[:10]))
    restore_tracked_files(root)
    remaining = status_paths(root)
    if remaining:
        raise ValueError("Provisioning mutated the untouched source baseline: "
                         + ", ".join(remaining[:10]))
    return remaining


def is_test(path):
    return bool(re.search(r"(?:^|/)(?:tests?|specs?|__tests__)(?:/|$)|"
                          r"(?:^|/)test_[^/]+|[._](?:test|spec)[._]", path, re.I))


def product_paths(paths):
    return [p for p in paths if not is_test(p) and not p.startswith(("docs/", ".github/"))
            and not p.lower().endswith((".md", ".rst", ".txt", ".lock", "lock.json", "lock.yaml"))
            and Path(p).name not in {"yarn.lock", "package-lock.json", "bun.lockb", "Cargo.lock"}]


def manifest(root, paths):
    result = {}
    for name in sorted(paths):
        path = safe_path(root, name)
        result[name] = ({"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "mode": path.stat().st_mode & 0o777} if path.is_file() else {"deleted": True})
    return result


def protect_baseline_tests(root, base_sha, paths, head_sha=None):
    for name in paths:
        existing = git(root, "cat-file", "-e", f"{base_sha}:{name}", check=False).returncode == 0
        if existing and is_test(name):
            raise ValueError("Existing master test mutation: " + name)
        if existing and (re.search(r"(?:vitest|jest|pytest|eslint|ruff|mypy|coverage).*config|"
                                   r"(?:^|/)(?:pytest.ini|conftest.py|.coveragerc)$", name, re.I)):
            raise ValueError("Existing verification configuration mutation: " + name)
        if existing and Path(name).name == "package.json":
            before = json.loads(git(root, "show", f"{base_sha}:{name}").stdout)
            path = Path(root) / name
            if head_sha or path.exists():
                after = json.loads(git(root, "show", f"{head_sha}:{name}").stdout if head_sha else path.read_bytes())
                for key, value in before.get("scripts", {}).items():
                    if re.search(r"test|build|lint|check|format|type", key, re.I) and after.get("scripts", {}).get(key) != value:
                        raise ValueError("Existing native verification script changed: " + key)


def warning_output(text):
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return bool(re.search(r"(?im)^\s*(?:npm\s+warn|warning[:\s\[]|.*DeprecationWarning:|"
                          r"\d+:\d+\s+warning\b|the CJS build .* deprecated)|"
                          r"\b[1-9]\d*\s+warnings?\b", plain))


def validate_plan_contract(plan, path=None):
    """Every native plan phase must be present.

    A missing phase is a malformed agent deliverable, not an engineering verdict. Measured
    2026-10-29, the bare ``ValueError`` here reached the blanket handler and was stamped
    ``FAILED_ENGINEER`` for code that was never judged -- ``isearchxsolve/bounty-proof#1``,
    "Mandatory native plan phase missing: builds". Typed as a deliverable-contract violation
    so the ledger says what actually happened, exactly as the dirty-baseline case already
    does (``PreparationContractViolation``, run 40852325249).

    ``path`` names the artefact that carried the incomplete plan, so the failure record
    explains itself without a log dig.
    """
    for name in ("builds", "baseline_tests", "final_tests"):
        if not getattr(plan, name, None):
            raise PreparationContractViolation(
                path or "<native plan contract>",
                "Mandatory native plan phase missing: " + name)
    # The command checks below judge the same object as the phase checks above -- a plan the
    # agent supplied -- so they share one type. A bypassed command was a bare ``ValueError``
    # too, and the blanket handler stamped it ``FAILED_ENGINEER`` for the same wrong reason.
    for phase in ("bootstrap", "builds", "baseline_tests", "targeted_tests", "final_tests", "linters", "format_checks"):
        for command in getattr(plan, phase, []):
            if (not isinstance(command, list) or not command
                    or any(not isinstance(p, str) or "\0" in p for p in command)):
                raise PreparationContractViolation(
                    path or "<native plan contract>",
                    "Native command must be a nonempty argv array in phase " + phase)
            if (Path(command[0]).name.lower() in {"true", "echo", "printf"}
                    or any(v in command for v in ("--if-present", "--passWithNoTests"))
                    or re.search(r"\|\|\s*(?:true|exit\s+0)", " ".join(command))
                    or (Path(command[0]).name.startswith("python") and "-c" in command)):
                raise PreparationContractViolation(
                    path or "<native plan contract>",
                    "Bypassed or synthetic native verification command in phase " + phase
                    + ": " + " ".join(command))


def require_commands(commands, results):
    if not commands:
        raise ValueError("No native verification commands")
    if any(row["exit_code"] != 0 for row in results):
        raise ValueError("A final native command failed")
    for command in commands:
        matching = [row for row in results if row["argv"] == command]
        if not matching or matching[-1]["exit_code"] != 0:
            raise ValueError("Native command lacks a successful receipt: " + repr(command))
        if warning_output(matching[-1].get("stdout", "") + "\n" + matching[-1].get("stderr", "")):
            raise ValueError("Native verification emitted warnings: " + repr(command))
        text = matching[-1].get("stdout", "") + "\n" + matching[-1].get("stderr", "")
        if re.search(r"No tests?(?: files)? (?:found|ran|collected)|Ran 0 tests", text, re.I):
            raise ValueError("Native runner reported zero executed tests: " + repr(command))


def regression_proof(root, base_sha, document, execute):
    """Run new companion tests against actual base source, then restored fix."""
    files, command = document.get("test_files"), document.get("argv")
    expected = document.get("expected_failure")
    if not files or not command or not isinstance(expected, str) or len(expected) < 12:
        raise ValueError("Specific regression test files/command/failure assertion are mandatory")
    changed = status_paths(root)
    if not set(files).issubset(changed) or not all(is_test(p) for p in files):
        raise ValueError("Regression must name the actual added companion tests")
    for name in files:
        if git(root, "cat-file", "-e", f"{base_sha}:{name}", check=False).returncode == 0:
            raise ValueError("Regression cannot replace an existing master test")
    final = manifest(root, changed)
    backups = {}
    try:
        for name in changed:
            if name in files:
                continue
            path = safe_path(root, name)
            backups[name] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None
            baseline = git(root, "show", f"{base_sha}:{name}", check=False)
            if baseline.returncode == 0:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(baseline.stdout)
            elif path.exists():
                path.unlink()
        red = execute(command)
        output = red.stdout + "\n" + red.stderr
        if (red.exit_code == 0 or expected not in output or re.search(
                r"Cannot find module|ModuleNotFoundError|command not found|No such file", output, re.I)):
            raise ValueError("Base regression did not fail on the specified defect assertion:\n" + output)
    finally:
        for name, backup in backups.items():
            path = safe_path(root, name)
            if backup is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(backup[0])
                path.chmod(backup[1])
    if manifest(root, changed) != final:
        raise ValueError("Regression probe changed the proposed fix")
    green = execute(command)
    if green.exit_code or warning_output(green.stdout + "\n" + green.stderr):
        raise ValueError("Final issue regression is not green:\n" + green.stdout + "\n" + green.stderr)
    return {"argv": command, "test_files": files, "expected_failure": expected,
            "red_exit": red.exit_code, "green_exit": green.exit_code,
            "red_output_sha256": hashlib.sha256(output.encode()).hexdigest()}


def write_json(path, document):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(json.dumps(document, indent=2, ensure_ascii=True).encode())


def restore_checkpoint(root, base_sha, archive):
    """Restore exact owned artifact bytes, never extract arbitrary ZIP paths."""
    with zipfile.ZipFile(archive) as saved:
        info = json.loads(saved.read("checkpoint.json"))
        if info.get("schema") != 1 or info["head_sha"] != base_sha:
            raise ValueError("Checkpoint baseline differs; retain artifact for explicit Cline rebase")
        files = {}
        for entry in saved.infolist():
            if entry.filename.startswith(("tracked/", "untracked/")):
                name = entry.filename.split("/", 1)[1]
                safe_path(root, name)
                if entry.file_size > 20_000_000 or len(files) >= 10000:
                    raise ValueError("Oversized source checkpoint requires explicit recovery")
                if entry.filename.startswith("untracked/") and safe_path(root, name).exists():
                    raise ValueError("Checkpoint companion would overwrite upstream: " + name)
                files[name] = (entry, saved.read(entry))
        # Git validates the binary patch before any companion file is written.
        patch_file = Path(archive).with_suffix(".patch")
        patch_file.write_bytes(saved.read("tracked.patch"))
        git(root, "apply", "--allow-empty", "--check", str(patch_file))
        git(root, "apply", "--allow-empty", str(patch_file))
        for name, (entry, data) in files.items():
            target = safe_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            mode = (entry.external_attr >> 16) & 0o777
            if mode:
                target.chmod(mode)
    return {"status": "RESTORED", "archive_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            "checkpoint": info, "files": manifest(root, status_paths(root))}
