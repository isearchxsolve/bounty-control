"""Run the reviewed pipeline regression manifest, retaining every suite result.

No wildcard test discovery: this repository also contains live operational probes.
The selected suites mock external services; this runner is not an OS/network sandbox.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("pipeline_master_suites.json")


def discovered_no_tests(body: str) -> bool:
    """Did this suite's own log report that unittest found no assertions?

    ``unittest`` exits 0 and prints a clean OK when a module holds zero tests, so a demo
    script with a ``test_`` prefix lands in the manifest looking like a green suite. That is
    a fact about the log, not a judgement about the file, so it is a gate and not a rule:
    whether the module deserves to stay in the manifest is a human's call.
    """
    return bool(re.search(r"^Ran 0 tests", body, re.M)) or bool(re.search(r"^NO TESTS RAN", body, re.M))


def execute(suite, output, timeout):
    name = suite["file"]
    command = [sys.executable, "-W", "error"]
    if suite["mode"] == "unittest":
        command += ["-m", "unittest", "discover", "-s", "scripts", "-p", name, "-v"]
    else:
        command += [str(ROOT / "scripts" / name)]
    started = time.monotonic()
    result = {"suite": name, "status": "ERROR", "returncode": None,
              "log": name + ".log"}
    with tempfile.TemporaryDirectory(prefix="pipeline-master-") as temp:
        environment = {k: v for k, v in os.environ.items()
                       if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))}
        environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                           GH_CONFIG_DIR=temp, FLEET_SANDBOX_DIR=temp + "/sandbox",
                           FLEET_ARTIFACT_DIR=temp + "/artifacts")
        with (output / result["log"]).open("w", encoding="utf-8") as log:
            try:
                completed = subprocess.run(command, cwd=ROOT, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                result.update(returncode=completed.returncode,
                              status="PASS" if completed.returncode == 0 else "FAIL")
            except subprocess.TimeoutExpired:
                result["status"] = "TIMEOUT"
                log.write(f"\nMASTER: suite exceeded {timeout} seconds\n")
            except OSError as exc:
                log.write(f"\nMASTER: {type(exc).__name__}: {exc}\n")
    result["seconds"] = round(time.monotonic() - started, 3)
    if result["status"] == "PASS" and suite["mode"] == "unittest":
        # A module that discovers zero tests is not a passing suite, it is a demo script
        # with a test_ prefix, and unittest reports it as a clean OK. Measured 2026-11-06:
        # test_normalise_rest.py and test_discovery_queries.py both ran zero assertions -
        # the second only surfaced because CI has no gh credentials while my workstation
        # does, so a script that silently exits 0 was recorded as a green suite.
        log_path = output / result["log"]
        try:
            body = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        if discovered_no_tests(body):
            result["status"] = "FAIL"
            result["zero_tests"] = True
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\nMASTER: suite discovered zero tests; a manifest entry must assert\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "scratch" / "pipeline-master")
    parser.add_argument("--timeout", type=int, default=180, help="seconds per suite")
    parser.add_argument("--suite", action="append", help="exact manifest filename; repeat to select")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    suites = json.loads(MANIFEST.read_text(encoding="utf-8"))["suites"]
    names = [s["file"] for s in suites]
    if len(names) != len(set(names)):
        parser.error("manifest contains duplicate suites")
    for suite in suites:
        name = suite["file"]
        if Path(name).name != name or not name.startswith("test_") or not name.endswith(".py"):
            parser.error("invalid suite filename")
        if suite["mode"] not in ("script", "unittest") or not (ROOT / "scripts" / name).is_file():
            parser.error("missing suite or invalid execution mode: " + name)
    if args.suite:
        unknown = set(args.suite) - set(names)
        if unknown:
            parser.error("unknown suite(s): " + ", ".join(sorted(unknown)))
        suites = [s for s in suites if s["file"] in args.suite]
    if args.list:
        for suite in suites:
            print(suite["file"])
        return 0
    # Unique directories keep earlier failure evidence intact.
    output = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
              "planned_suites": len(suites), "results": []}
    def save():
        temporary = output / "report.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")
    save()
    print(f"Report: {output / 'report.json'}", flush=True)
    for suite in suites:
        print(f"RUN {suite['file']}", flush=True)
        result = execute(suite, output, args.timeout)
        report["results"].append(result)
        save()
        print(f"{result['status']} {result['suite']} ({result['seconds']}s)", flush=True)
    report["complete"] = True
    report["passed"] = all(r["status"] == "PASS" for r in report["results"])
    save()
    failures = sum(r["status"] != "PASS" for r in report["results"])
    print(f"{len(suites) - failures}/{len(suites)} suites passed; {failures} failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
