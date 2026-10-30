import os
import sys
import time
import json
import base64
import subprocess
from typing import Tuple, List, Optional

KAGGLE_USERNAME = "isearchxsolve"
DEFAULT_KERNEL_SLUG = "bounty-ci-runner"

RUNNER_TEMPLATE = '''import subprocess
import sys
import os
import base64
import time

print("=== KAGGLE BOUNTY CI RUNNER STARTING ===")
print("Host:", os.uname().nodename if hasattr(os, "uname") else "unknown")
print("CPUs:", os.cpu_count())

env = os.environ.copy()

# 1. Toolchain Setup
ecosystem = "__ECOSYSTEM__"
if ecosystem == "rust":
    cargo_path = os.path.expanduser("~/.cargo/bin/cargo")
    if not os.path.exists(cargo_path):
        print("Installing Rust toolchain...")
        subprocess.run("curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable", shell=True, check=True)
    env["PATH"] = os.path.expanduser("~/.cargo/bin") + ":" + env.get("PATH", "")
elif ecosystem == "node":
    print("Checking Node.js & npm...")
    subprocess.run(["node", "--version"], env=env)
    subprocess.run(["npm", "--version"], env=env)
elif ecosystem == "python":
    print("Checking Python...")
    subprocess.run([sys.executable, "--version"], env=env)
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pytest"], env=env)

# 2. Clone Repository
repo_url = "__REPO_URL__"
base_ref = "__BASE_REF__"
repo_dir = "/kaggle/working/repo"

if os.path.exists(repo_dir):
    subprocess.run(["rm", "-rf", repo_dir])

print(f"Cloning {repo_url}...")
clone_cmd = ["git", "clone", "--depth", "10"]
if base_ref and base_ref != "HEAD":
    clone_cmd.extend(["--branch", base_ref])
clone_cmd.extend([repo_url, repo_dir])

res = subprocess.run(clone_cmd, capture_output=True, text=True)
if res.returncode != 0:
    # fallback to clone without branch
    subprocess.run(["git", "clone", "--depth", "10", repo_url, repo_dir], check=True)

# 3. Apply Patch if provided
patch_b64 = "__PATCH_B64__"
if patch_b64:
    patch_bytes = base64.b64decode(patch_b64)
    patch_path = os.path.join(repo_dir, "change.patch")
    with open(patch_path, "wb") as pf:
        pf.write(patch_bytes)
    print("Applying patch...")
    p_res = subprocess.run(["git", "apply", "change.patch"], cwd=repo_dir, capture_output=True, text=True)
    if p_res.returncode != 0:
        subprocess.run(["patch", "-p1", "-i", "change.patch"], cwd=repo_dir, check=True)
    subprocess.run(["git", "diff", "--stat"], cwd=repo_dir)

# 4. Execute Test Commands
test_commands = json.loads("""__TEST_COMMANDS_JSON__""")
all_passed = True
logs = []

for cmd in test_commands:
    print(f"\\n>>> Running: {' '.join(cmd)}")
    t0 = time.time()
    c_res = subprocess.run(cmd, cwd=repo_dir, env=env, capture_output=True, text=True)
    dur = time.time() - t0
    print(f"Completed in {dur:.2f}s with code {c_res.returncode}")
    if c_res.stdout:
        print("--- STDOUT ---")
        print(c_res.stdout)
    if c_res.stderr:
        print("--- STDERR ---")
        print(c_res.stderr)
    logs.append({
        "cmd": cmd,
        "exit_code": c_res.returncode,
        "duration": dur,
        "stdout": c_res.stdout,
        "stderr": c_res.stderr
    })
    if c_res.returncode != 0:
        all_passed = False
        break

receipt = {
    "all_passed": all_passed,
    "timestamp": time.time(),
    "logs": logs
}

with open("/kaggle/working/test_receipt.json", "w", encoding="utf-8") as rf:
    json.dump(receipt, rf, indent=2)

if not all_passed:
    sys.exit(1)

print("\\n>>> ALL KAGGLE REMOTE TESTS PASSED GREEN! <<<")
'''

def run_remote_kaggle_test(
    repo_url: str,
    base_ref: str,
    patch_content: str,
    test_commands: List[List[str]],
    ecosystem: str = "rust",
    scratch_dir: str = r"D:\anonym\scratch\kaggle_ci_runner",
    poll_interval: int = 15,
    timeout: int = 1200
) -> Tuple[bool, str, dict]:
    """
    Submits a test suite to Kaggle via Kaggle CLI, completely shielding local CPU.
    """
    os.makedirs(scratch_dir, exist_ok=True)
    out_dir = os.path.join(scratch_dir, "out")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Generate runner.py
    patch_b64 = base64.b64encode(patch_content.encode("utf-8")).decode("utf-8") if patch_content else ""
    code = RUNNER_TEMPLATE.replace("__ECOSYSTEM__", ecosystem)
    code = code.replace("__REPO_URL__", repo_url)
    code = code.replace("__BASE_REF__", base_ref)
    code = code.replace("__PATCH_B64__", patch_b64)
    code = code.replace('"""__TEST_COMMANDS_JSON__"""', json.dumps(json.dumps(test_commands)))

    runner_file = os.path.join(scratch_dir, "runner.py")
    with open(runner_file, "w", encoding="utf-8") as f:
        f.write(code)

    # 2. Generate kernel-metadata.json
    meta = {
        "id": f"{KAGGLE_USERNAME}/{DEFAULT_KERNEL_SLUG}",
        "title": "Bounty CI Runner",
        "code_file": "runner.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": False,
        "enable_internet": True,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": []
    }
    meta_file = os.path.join(scratch_dir, "kernel-metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # 3. Push kernel via kaggle CLI
    print(f"[Kaggle Remote] Pushing test suite for {repo_url} to Kaggle...")
    push_res = subprocess.run(["kaggle", "kernels", "push", "-p", scratch_dir], capture_output=True, text=True)
    if push_res.returncode != 0:
        return False, f"Failed to push Kaggle kernel: {push_res.stderr or push_res.stdout}", {}

    print(f"[Kaggle Remote] Kernel pushed successfully. Polling status...")
    kernel_id = f"{KAGGLE_USERNAME}/{DEFAULT_KERNEL_SLUG}"
    start_time = time.time()

    while time.time() - start_time < timeout:
        time.sleep(poll_interval)
        st_res = subprocess.run(["kaggle", "kernels", "status", kernel_id], capture_output=True, text=True)
        status_line = st_res.stdout.strip()
        print(f"[Kaggle Remote] Status: {status_line}")

        if "COMPLETE" in status_line:
            # Download outputs
            out_res = subprocess.run(["kaggle", "kernels", "output", kernel_id, "-p", out_dir], capture_output=True, text=True)
            receipt_path = os.path.join(out_dir, "test_receipt.json")
            if os.path.exists(receipt_path):
                with open(receipt_path, "r", encoding="utf-8") as rf:
                    receipt = json.load(rf)
                return receipt.get("all_passed", False), "Remote test completed successfully.", receipt
            
            # Read stdout/log files if any
            log_files = [f for f in os.listdir(out_dir) if f.endswith(".log") or f.endswith(".txt")]
            log_text = ""
            for lf in log_files:
                with open(os.path.join(out_dir, lf), "r", encoding="utf-8", errors="replace") as lfh:
                    log_text += f"\n--- {lf} ---\n" + lfh.read()
            return True, f"Kaggle kernel completed:\n{log_text}", {}

        elif "ERROR" in status_line or "FAILED" in status_line:
            subprocess.run(["kaggle", "kernels", "output", kernel_id, "-p", out_dir], capture_output=True, text=True)
            return False, f"Kaggle kernel failed: {status_line}", {}

    return False, f"Timed out waiting for Kaggle kernel after {timeout}s", {}
