import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path

VAULT_DIR = Path(r"D:\anonym\vault")
SCRATCH_DIR = Path(r"D:\anonym\scratch\kaggle_engines")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
GITHUB_TOKEN_FILE = VAULT_DIR / "gh_token.txt"
GITHUB_CREDENTIAL_DATASET = "omniroute-github-credential-20261026"
TOKENHARBOR_KEYS_FILE = VAULT_DIR / "tokenharbor_keys.json"
TOKENHARBOR_DATASET_PREFIX = "omniroute-tokenharbor-engine"
TOTAL_ENGINES = 5

# Engine five intentionally shares the kunaldas3104 account but uses its fifth
# credential, giving the fleet five independently scheduled Kaggle kernels.
FLEET_ACCOUNTS = [
    {"engine": 1, "account": "isearchxsolve", "token_file": None},
    {"engine": 2, "account": "kkk3213", "token_file": VAULT_DIR / "kaggle_token_2.txt"},
    {"engine": 3, "account": "kunaldas3104", "token_file": VAULT_DIR / "kaggle_token_3.txt"},
    {"engine": 4, "account": "kdas19999", "token_file": VAULT_DIR / "kaggle_token_4.txt"},
    {"engine": 5, "account": "kunaldas3104", "token_file": VAULT_DIR / "kaggle_token_5.txt"},
]

def kaggle_environment(account: str, token_file: Path | None) -> tuple[dict | None, str | None]:
    """Return account-scoped Kaggle credentials without logging their values."""
    env = dict(os.environ)
    if token_file is None:
        return env, None
    if not token_file.exists():
        return None, f"token file missing: {token_file}"
    key = token_file.read_text(encoding="utf-8").strip()
    if not key:
        return None, f"token file is empty: {token_file}"
    if key.startswith("KGAT_"):
        env["KAGGLE_API_TOKEN"] = key
        env.pop("KAGGLE_USERNAME", None)
        env.pop("KAGGLE_KEY", None)
    else:
        env["KAGGLE_USERNAME"] = account
        env["KAGGLE_KEY"] = key
    return env, None


def ensure_private_github_credential_dataset(account: str, env: dict) -> tuple[bool, str]:
    """Publish the GitHub token only as a private, account-owned Kaggle dataset."""
    if not GITHUB_TOKEN_FILE.exists():
        return False, "GitHub credential file is missing"
    github_token = GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not github_token:
        return False, "GitHub credential file is empty"

    dataset_ref = f"{account}/{GITHUB_CREDENTIAL_DATASET}"
    with tempfile.TemporaryDirectory(prefix="kaggle-private-gh-", dir=str(SCRATCH_DIR)) as temp_dir:
        dataset_dir = Path(temp_dir)
        (dataset_dir / "github_token.txt").write_text(github_token, encoding="utf-8")
        metadata = {
            "title": "Omniroute Private GitHub Credential",
            "id": dataset_ref,
            "licenses": [{"name": "Other"}],
        }
        (dataset_dir / "dataset-metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        status = subprocess.run(
            [sys.executable, "-m", "kaggle", "datasets", "status", dataset_ref],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if status.returncode == 0:
            command = [
                sys.executable, "-m", "kaggle", "datasets", "version",
                "-p", str(dataset_dir), "-m", "Rotate private fleet credential",
                "-q", "-t", "-r", "skip",
            ]
        else:
            command = [
                sys.executable, "-m", "kaggle", "datasets", "create",
                "-p", str(dataset_dir), "-q", "-t", "-r", "skip",
            ]
        upload = subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)
        if upload.returncode != 0:
            return False, f"private credential dataset upload failed (exit {upload.returncode})"

        verify = subprocess.run(
            [sys.executable, "-m", "kaggle", "datasets", "status", dataset_ref],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if verify.returncode != 0:
            return False, f"private credential dataset status failed (exit {verify.returncode})"
    return True, dataset_ref


def load_tokenharbor_keys() -> list[str]:
    """Read and validate the full TokenHarbor pool without logging key values."""
    if not TOKENHARBOR_KEYS_FILE.exists():
        raise FileNotFoundError(f"TokenHarbor key pool is missing: {TOKENHARBOR_KEYS_FILE}")
    document = json.loads(TOKENHARBOR_KEYS_FILE.read_text(encoding="utf-8"))
    if isinstance(document, list):
        keys = document
    elif isinstance(document, dict):
        keys = document.get("keys", document.get("value", []))
    else:
        raise ValueError("TokenHarbor key pool must contain a list.")
    if not isinstance(keys, list) or not all(isinstance(key, str) and key.strip() for key in keys):
        raise ValueError("TokenHarbor key pool contains invalid entries.")
    keys = [key.strip() for key in keys]
    if len(keys) < TOTAL_ENGINES or len(set(keys)) != len(keys):
        raise ValueError(f"Expected at least {TOTAL_ENGINES} unique TokenHarbor keys; found {len(keys)} entries.")
    return keys


def shard_tokenharbor_keys(keys: list[str], engine_index: int, total_engines: int = TOTAL_ENGINES) -> list[str]:
    """Assign a deterministic, disjoint modulo shard to one fleet engine."""
    if total_engines <= 0 or engine_index < 1 or engine_index > total_engines:
        raise ValueError("engine_index must be within the configured fleet.")
    if not keys:
        raise ValueError("TokenHarbor key pool cannot be empty.")
    shard = [key for index, key in enumerate(keys) if index % total_engines == engine_index - 1]
    if not shard:
        raise ValueError(f"TokenHarbor key pool assigned no keys to engine {engine_index}.")
    return shard


def ensure_private_tokenharbor_dataset(account: str, engine_index: int, keys: list[str], env: dict) -> tuple[bool, str, str]:
    """Store one engine's disjoint TokenHarbor shard in a private Kaggle dataset."""
    dataset_slug = f"{TOKENHARBOR_DATASET_PREFIX}-{engine_index}-20261026"
    dataset_ref = f"{account}/{dataset_slug}"
    with tempfile.TemporaryDirectory(prefix=f"kaggle-private-th-{engine_index}-", dir=str(SCRATCH_DIR)) as temp_dir:
        dataset_dir = Path(temp_dir)
        (dataset_dir / "tokenharbor_keys.json").write_text(json.dumps(keys), encoding="utf-8")
        (dataset_dir / "key-manifest.json").write_text(
            json.dumps({
                "engine_index": engine_index,
                "total_engines": TOTAL_ENGINES,
                "key_count": len(keys),
                "shard_rule": "zero-based-key-index modulo total_engines equals engine_index minus one",
            }, indent=2),
            encoding="utf-8",
        )
        metadata = {
            "title": f"Omniroute Private TokenHarbor Shard Engine {engine_index}",
            "id": dataset_ref,
            "licenses": [{"name": "Other"}],
        }
        (dataset_dir / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        status = subprocess.run(
            [sys.executable, "-m", "kaggle", "datasets", "status", dataset_ref],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if status.returncode == 0:
            command = [
                sys.executable, "-m", "kaggle", "datasets", "version",
                "-p", str(dataset_dir), "-m", f"Rotate engine {engine_index} TokenHarbor shard",
                "-q", "-t", "-r", "skip",
            ]
        else:
            command = [
                sys.executable, "-m", "kaggle", "datasets", "create",
                "-p", str(dataset_dir), "-q", "-t", "-r", "skip",
            ]
        upload = subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)
        if upload.returncode != 0:
            return False, dataset_ref, f"private TokenHarbor dataset upload failed (exit {upload.returncode})"
        verify = subprocess.run(
            [sys.executable, "-m", "kaggle", "datasets", "status", dataset_ref],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if verify.returncode != 0:
            return False, dataset_ref, f"private TokenHarbor dataset status failed (exit {verify.returncode})"
    return True, dataset_ref, ""


def worker_source_for_deployment() -> str:
    """Bundle the shared policy into Kaggle's single-file script upload."""
    script_dir = Path(__file__).resolve().parent
    source = (script_dir / 'kaggle_engine_worker.py').read_text(encoding='utf-8')
    policy = (script_dir / 'fleet_recovery_policy.py').read_text(encoding='utf-8')
    supervisor = (script_dir / 'delivery_supervisor.py').read_text(encoding='utf-8')
    bootstrap = (
        '\nimport sys as _fleet_sys, types as _fleet_types\n'
        "_fleet_policy = _fleet_types.ModuleType('fleet_recovery_policy')\n"
        "_fleet_sys.modules['fleet_recovery_policy'] = _fleet_policy\n"
        f"exec(compile({policy!r}, 'fleet_recovery_policy.py', 'exec'), _fleet_policy.__dict__)\n"
        "_supervisor = _fleet_types.ModuleType('delivery_supervisor')\n"
        "_fleet_sys.modules['delivery_supervisor'] = _supervisor\n"
        f"exec(compile({supervisor!r}, 'delivery_supervisor.py', 'exec'), _supervisor.__dict__)\n"
    )
    return source.replace('from __future__ import annotations', 'from __future__ import annotations' + bootstrap, 1)


def deploy_all_engines(engine_indexes: set[int] | None = None) -> list[dict]:
    if engine_indexes is not None and (not engine_indexes or not engine_indexes <= {1, 2, 3, 4, 5}):
        raise ValueError('Select engine indexes between 1 and 5.')
    worker_src_path = Path(r"D:\anonym\scripts\kaggle_engine_worker.py")
    if not worker_src_path.exists():
        raise FileNotFoundError(f"Missing worker script: {worker_src_path}")
    worker_src = worker_source_for_deployment()

    tokenharbor_keys = load_tokenharbor_keys()
    results = []
    credential_datasets: dict[str, str] = {}
    for node in FLEET_ACCOUNTS:
        idx = node["engine"]
        if engine_indexes is not None and idx not in engine_indexes:
            continue
        account = node["account"]
        tok_file = node["token_file"]

        env, credential_error = kaggle_environment(account, tok_file)
        if credential_error:
            print(f"[FAILED] Engine {idx} ({account}): {credential_error}.")
            results.append({"engine": idx, "account": account, "success": False, "output": credential_error})
            continue

        if account not in credential_datasets:
            dataset_ok, dataset_result = ensure_private_github_credential_dataset(account, env)
            if not dataset_ok:
                print(f"[FAILED] Engine {idx} ({account}): {dataset_result}.")
                results.append({"engine": idx, "account": account, "success": False, "output": dataset_result})
                continue
            credential_datasets[account] = dataset_result
            print(f"[Credential] Engine {idx} ({account}): private dataset verified.")

        tokenharbor_shard = shard_tokenharbor_keys(tokenharbor_keys, idx)
        tokenharbor_ok, tokenharbor_dataset, tokenharbor_error = ensure_private_tokenharbor_dataset(
            account, idx, tokenharbor_shard, env
        )
        if not tokenharbor_ok:
            print(f"[FAILED] Engine {idx} ({account}): {tokenharbor_error}.")
            results.append({"engine": idx, "account": account, "success": False, "output": tokenharbor_error})
            continue
        print(f"[TokenHarbor] Engine {idx} ({account}): private {len(tokenharbor_shard)}-key shard verified.")

        engine_slug = f"bounty-engine-{idx}"
        engine_dir = SCRATCH_DIR / f"engine_{idx}"
        engine_dir.mkdir(parents=True, exist_ok=True)

        # 1. Write worker.py with non-secret engine-specific dataset metadata only.
        tokenharbor_key_file = f"/kaggle/input/{TOKENHARBOR_DATASET_PREFIX}-{idx}-20261026/tokenharbor_keys.json"
        engine_id_line = (
            "import os\n"
            + f'os.environ["ENGINE_ID"] = "{account}-{engine_slug}"\n'
            + f'os.environ["ENGINE_INDEX"] = "{idx}"\n'
            + f'os.environ["TOKENHARBOR_KEY_FILE"] = "{tokenharbor_key_file}"\n'
            + f'os.environ["TOKENHARBOR_EXPECTED_KEY_COUNT"] = "{len(tokenharbor_shard)}"\n'
        )
        if "from __future__ import annotations" in worker_src:
            parts = worker_src.split("from __future__ import annotations", 1)
            worker_code = parts[0] + "from __future__ import annotations\n" + engine_id_line + parts[1]
        else:
            worker_code = engine_id_line + worker_src
        (engine_dir / "worker.py").write_text(worker_code, encoding="utf-8")
        # 2. Write kernel-metadata.json
        meta = {
            "id": f"{account}/{engine_slug}",
            "title": f"Bounty Engine {idx}",
            "code_file": "worker.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": False,
            "enable_internet": True,
            "dataset_sources": [credential_datasets[account], tokenharbor_dataset],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": []
        }
        (engine_dir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        print(f"[Deploy] Pushing Engine {idx} ({engine_slug}) to Kaggle account '{account}'...")
        res = subprocess.run(
            [sys.executable, "-m", "kaggle", "kernels", "push", "-p", str(engine_dir)],
            capture_output=True,
            text=True,
            env=env
        )
        out = (res.stdout or "") + (res.stderr or "")
        success = res.returncode == 0
        print(f" -> Result for Engine {idx}: {'OK (LIVE)' if success else 'FAILED: ' + out[:150]}")
        results.append({"engine": engine_slug, "account": account, "success": success, "output": out[:500]})

    return results

if __name__ == "__main__":
    deployment_results = deploy_all_engines()
    raise SystemExit(0 if deployment_results and all(row["success"] for row in deployment_results) else 1)
