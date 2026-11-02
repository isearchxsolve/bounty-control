"""Mutation check: does the live pipeline e2e suite actually catch a broken driver?

Target: ``live_pipeline_integration.py`` -- the live driver that owns the run journal,
the hydration drain evidence and the stdout tee -- exercised by
``test_live_pipeline_driver.py``, the only suite that imports it.

Each mutation is a single semantic break in the driver. The suite is run after each one;
a mutation that survives is a hole in the suite, not a pass. Mutations are applied to the
file and restored in a finally block, so an interrupted run cannot leave the tree mutated.

Run: python scripts/_mutation_check.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "live_pipeline_integration.py"

# The live pipeline e2e layer. This is the seam that carries a real run journal, real
# hydration artifacts and real stdout between hops, so it is the suite to mutate.
SUITES = ["test_live_pipeline_driver.py"]

# (name, find, replace) -- each find must appear exactly once in DRIVER.
MUTATIONS = [
    ("incomplete coverage no longer revokes green",
     "        if any(status != 'PASS' for status in self.data['coverage'].values()):\n"
     "            self.data['end_to_end_passed'] = False",
     "        if False:\n"
     "            self.data['end_to_end_passed'] = False"),
    ("an unrun case is recorded as a pass",
     "latest.get(case, 'NOT_RUN')",
     "latest.get(case, 'PASS')"),
    ("a later failure no longer revokes green",
     "        if status in ('FAIL', 'PENDING', 'INCOMPLETE'):",
     "        if False:"),
    ("drain accepts a non-hydration door reason",
     "    check(census.get('door_reason') == 'HYDRATE_ONLY', 'Hydration did not run the production agent-queue path')",
     "    check(True, 'Hydration did not run the production agent-queue path')"),
    ("drain accepts inherited stale cache evidence",
     "    check(datetime.fromisoformat(census['at'].replace('Z', '+00:00')) >= started,",
     "    check(True,"),
    ("drain accepts unexamined pending rows",
     "    check(all(datetime.fromisoformat(at.replace('Z', '+00:00')) >= started for (at,) in rows),",
     "    check(True,"),
    ("required case silently dropped from the contract",
     "'LIVE_RELEASE_HEAD', 'LIVE_RELEASE_TREE',",
     "'LIVE_RELEASE_TREE',"),
    ("tee stops forwarding the wrapped stream interface",
     "        return getattr(self.stream, name)",
     "        raise AttributeError(name)"),
    ("tee stops writing the evidence log",
     "        self.log.write(value)\n        self.log.flush()\n        return self.stream.write(value)",
     "        return self.stream.write(value)"),
]


def run_suite() -> tuple[int, str]:
    done = subprocess.run([sys.executable, "-m", "pytest", *SUITES, "-q", "--no-header"],
                          cwd=HERE, capture_output=True, text=True, timeout=900,
                          encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def main() -> int:
    code, output = run_suite()
    if code != 0:
        print("BASELINE IS NOT GREEN - fix that before mutating:\n" + output[-2000:])
        return 2
    print(f"baseline: green ({', '.join(SUITES)})\n")

    survived, killed = [], []
    for name, find, replace in MUTATIONS:
        original = DRIVER.read_text(encoding="utf-8")
        if original.count(find) != 1:
            print(f"SKIP  {name}: anchor appears {original.count(find)}x, not once")
            survived.append((name, "anchor did not resolve"))
            continue
        backup = DRIVER.with_suffix(DRIVER.suffix + ".mutation-backup")
        shutil.copy2(DRIVER, backup)
        try:
            DRIVER.write_text(original.replace(find, replace, 1), encoding="utf-8")
            code, output = run_suite()
        finally:
            shutil.copy2(backup, DRIVER)
            backup.unlink(missing_ok=True)
        if code == 0:
            print(f"SURVIVED  {name}")
            survived.append((name, "the live driver suite never reached it"))
        else:
            failing = [line for line in output.splitlines()
                       if line.startswith("FAILED") or line.startswith("ERROR")]
            print(f"killed    {name}  ({len(failing)} failing)")
            killed.append(name)

    print(f"\n=== {len(killed)} killed, {len(survived)} survived ===")
    for name, why in survived:
        print(f"  HOLE: {name} -- {why}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
