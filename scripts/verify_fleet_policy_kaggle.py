"""Stage and run isolated policy checks on a private CPU Kaggle kernel."""
import json
import subprocess
import sys
from pathlib import Path

from deploy_kaggle_engines import kaggle_environment, FLEET_ACCOUNTS

root = Path(__file__).resolve().parent
stage = root.parent / "scratch" / "fleet_policy_verification"
stage.mkdir(parents=True, exist_ok=True)
worker = (root / "kaggle_engine_worker.py").read_text(encoding="utf-8")
tests = (root / "test_fleet_retry_policy.py").read_text(encoding="utf-8")
runner = "import sys, types, unittest\n"
runner += "m = types.ModuleType('kaggle_engine_worker')\nsys.modules[m.__name__] = m\n"
runner += f"exec(compile({worker!r}, 'kaggle_engine_worker.py', 'exec'), m.__dict__)\n"
runner += "t = types.ModuleType('fleet_policy_tests')\n"
runner += f"exec(compile({tests!r}, 'test_fleet_retry_policy.py', 'exec'), t.__dict__)\n"
runner += "result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(t))\n"
runner += "raise SystemExit(0 if result.wasSuccessful() else 1)\n"
(stage / "verify.py").write_text(runner, encoding="utf-8")
meta = dict(id="isearchxsolve/fleet-policy-verification", title="Fleet Policy Verification", code_file="verify.py",
    language="python", kernel_type="script", is_private=True, enable_gpu=False, enable_internet=False,
    dataset_sources=[], competition_sources=[], kernel_sources=[])
(stage / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
env, error = kaggle_environment(FLEET_ACCOUNTS[0]["account"], None)
if error:
    raise RuntimeError(error)
raise SystemExit(subprocess.run([sys.executable, "-m", "kaggle", "kernels", "push", "-p", str(stage)], env=env).returncode)
