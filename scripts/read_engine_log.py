import subprocess
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from deploy_kaggle_engines import FLEET_ACCOUNTS, kaggle_environment

for node in FLEET_ACCOUNTS:
    idx = node["engine"]
    acc = node["account"]
    env, err = kaggle_environment(acc, node["token_file"])
    if err:
        print(f"Engine {idx} ({acc}): {err}")
        continue
    kid = f"{acc}/bounty-engine-{idx}"
    res = subprocess.run(["kaggle", "kernels", "status", kid], env=env, capture_output=True, text=True, errors="replace")
    print(f"Engine {idx} ({kid}): {res.stdout.strip()}")
