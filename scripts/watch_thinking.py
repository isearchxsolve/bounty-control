"""Watch the entry door think, live.

Baba 2026-10-31: "only way to diagnose is not to wait for more tests to complete - watch out what
it is thinking, in which direction. You will instantly know what is missing. Capture its thinking
via stdout logs live."

So this does not verify, does not gate, does not write a shortlist into the repo. It scaffolds one
workspace with the real TASK.md, runs the real Cline command with the real model, and streams every
line of its stdout/stderr to a timestamped log the instant it arrives, so a direction can be read
from the middle of a thought instead of inferred from a finished result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cline_entry_door as door  # noqa: E402

LOG = os.path.join("D:/bc/_probe", "thinking-live.log")


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    root = "D:/bc/_probe/thinking"
    os.makedirs(root, exist_ok=True)
    workdir = door.scaffold_workspace(root)
    data_dir = os.path.join(workdir, ".cline")
    model = os.environ.get("BOUNTY_ENTRY_MODEL", "deepseek-v4.1-flash:free")
    if not door.prepare_profile(data_dir, model=model):
        print(json.dumps({"phase": "WATCH_FAIL", "reason": "PROFILE_NOT_READY"}))
        return 2

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    started = time.time()
    log = open(LOG, "w", encoding="utf-8", buffering=1)
    log.write("# watching the entry door think | model=%s | budget=%ss\n"
              % (os.environ.get("BOUNTY_ENTRY_MODEL", "deepseek-v4.1-flash:free"), seconds))
    lock = threading.Lock()

    def emit(stream: str, line: str) -> None:
        text = line.rstrip("\n")
        if not text.strip():
            return
        with lock:
            log.write("[%06.1fs] %-6s %s\n" % (time.time() - started, stream, text))
            try:
                print("[%06.1fs] %s" % (time.time() - started, text[:400]), flush=True)
            except Exception:
                pass

    command = [*door.resolve_cline(None), "--data-dir", data_dir,
               "--provider", "openai-compatible", "--model", model,
               "--key", "tokenharbor-local-proxy", "-y", "--retries", "2",
               "-t", str(seconds), "-c", workdir, door.WORKTREE_PROMPT]
    log.write("# %s\n" % " ".join(command))
    env = dict(os.environ)
    env.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1")
    env.setdefault("OPENAI_API_BASE", "http://127.0.0.1:8080/v1")
    env.setdefault("OPENAI_API_KEY", env.get("TOKENHARBOR_KEY", "tok-local"))
    process = subprocess.Popen(command, cwd=workdir, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, errors="replace",
                               encoding="utf-8", env=env)
    readers = []
    for stream, pipe in (("OUT", process.stdout), ("ERR", process.stderr)):
        thread = threading.Thread(target=lambda s=stream, p=pipe: [emit(s, l) for l in p],
                                  daemon=True)
        thread.start()
        readers.append(thread)

    print(json.dumps({"phase": "WATCH_LIVE", "workdir": workdir, "log": LOG,
                      "prompt": door.WORKTREE_PROMPT[:80]}), flush=True)
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        emit("SYS", "killed at the watch budget")
    for thread in readers:
        thread.join(timeout=5)
    shortlist = os.path.join(workdir, "shortlist.jsonl")
    wrote = 0
    if os.path.exists(shortlist):
        with open(shortlist, encoding="utf-8", errors="replace") as handle:
            wrote = sum(1 for line in handle if line.strip().startswith("{"))
    log.write("# end: exit=%s rows=%d\n" % (process.returncode, wrote))
    log.close()
    print(json.dumps({"phase": "WATCH_DONE", "exit": process.returncode, "rows": wrote}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
