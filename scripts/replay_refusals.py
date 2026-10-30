"""Replay the measured REJECTED_PREPARATION tasks through the F9 class gate.

Answers one question with a number: of the N tasks Cline refused at preparation time, how
many does ``is_code_change_request`` refuse today? Without this number any new gate is
guesswork.

Reads the refusal list from ``--from-fleet-state`` (a local directory of fleet-state JSON
documents) or from an explicit ``--case repo#number`` list. Fetches each issue through the
GitHub API and never writes to the repository.

Windows note: ``gh`` output is decoded as UTF-8 explicitly. The 2026-10-30 attempt died with
``UnicodeDecodeError: 'charmap' codec ... 0x8f`` because subprocess fell back to cp1252 for a
repo whose body contained an emoji.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from actions_dispatch import is_code_change_request  # noqa: E402

REFUSAL_STATUS = "REJECTED_PREPARATION"


def cases_from_fleet_state(directory):
    """(repo, number, cline_reason) for every record Cline refused at preparation."""
    found = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("status") != REFUSAL_STATUS:
            continue
        # Cline's refusal text lives at the top level on the records written by the
        # 2026-10-28 dispatch loop; older records carried it under failures[].
        reason = str(record.get("reason") or "")
        if not reason:
            for failure in record.get("failures") or []:
                reason = str(failure.get("diagnostic") or failure.get("reason") or "")
                if reason:
                    break
        found.append((record["repo"], record["issue_number"], reason))
    return found


def gh_json(endpoint):
    """GitHub REST read with explicit UTF-8, so cp1252 can never decide a result again."""
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError("gh api " + endpoint + " failed: "
                           + result.stderr.decode("utf-8", "replace").strip())
    return json.loads(result.stdout.decode("utf-8", "replace"))


def main(argv=None):
    # The Windows console is cp1252. One non-ASCII character in a title or reason killed the
    # 2026-10-30 attempt mid-run; make the stream safe before anything is printed.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-fleet-state", default=None,
                        help="directory of fleet-state JSON documents")
    parser.add_argument("--case", action="append", default=[],
                        help="explicit repo#number, repeatable")
    parser.add_argument("--write-fixtures", default=None,
                        help="write the fetched cases as a labelled fixture file")
    args = parser.parse_args(argv)

    cases = cases_from_fleet_state(args.from_fleet_state) if args.from_fleet_state else []
    for spec in args.case:
        repo, number = spec.rsplit("#", 1)
        cases.append((repo, int(number), ""))
    if not cases:
        parser.error("no cases: pass --from-fleet-state or --case")
    cases.sort()

    rows, refused = [], 0
    for repo, number, cline_reason in cases:
        issue = gh_json(f"repos/{repo}/issues/{number}")
        labels = [l.get("name", "") if isinstance(l, dict) else str(l)
                  for l in issue.get("labels", [])]
        admitted, reason = is_code_change_request(
            issue.get("title", ""), issue.get("body") or "", labels)
        if not admitted:
            refused += 1
        rows.append({
            "repo": repo,
            "number": number,
            "title": issue.get("title", ""),
            # Full body, not a preview: a truncated body changed a gate verdict on 2026-10-30
            # (os-moda#3 looks like a video bounty until the full text shows reproduction steps).
            "body": issue.get("body") or "",
            "labels": labels,
            "cline_refused": bool(cline_reason),
            "cline_reason": cline_reason[:400],
            "gate_admitted": admitted,
            "gate_reason": reason,
        })
        print(f"{repo}#{number}: {'ADMITTED' if admitted else 'refused'} - {reason}")

    total = len(rows)
    print(f"\nCATCH RATE {refused}/{total} refused by the F9 gate "
          f"({(100.0 * refused / total) if total else 0:.0f}%)")

    if args.write_fixtures:
        # A rerun must not erase the hand-assigned expected_class, or the test file silently
        # skips every case and looks like coverage. Measured 2026-10-30: it did exactly that.
        previous = {}
        if os.path.exists(args.write_fixtures):
            with open(args.write_fixtures, encoding="utf-8") as handle:
                for row in json.load(handle):
                    if row.get("expected_class"):
                        previous[(row["repo"], row["number"])] = row["expected_class"]
        for row in rows:
            if (row["repo"], row["number"]) in previous:
                row["expected_class"] = previous[(row["repo"], row["number"])]
        with open(args.write_fixtures, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        kept = sum(1 for row in rows if row.get("expected_class"))
        print("wrote %s (%d/%d rows carry expected_class)"
              % (args.write_fixtures, kept, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
