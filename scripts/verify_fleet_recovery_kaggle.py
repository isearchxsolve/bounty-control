"""Upload real sources and live receipts; compile and test exclusively on Kaggle."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from deploy_kaggle_engines import kaggle_environment, worker_source_for_deployment

root = Path(__file__).resolve().parent.parent
stage = root / 'scratch' / 'fleet_recovery_verification_20261026'
stage.mkdir(parents=True, exist_ok=True)
sources = [
    'scripts/autonomous_icu_pipeline.py', 'scripts/kaggle_engine_worker.py',
    'scripts/deploy_kaggle_engines.py', 'scripts/tokenharbor_router.py',
    'scripts/fleet_recovery_policy.py', 'scripts/test_icu_pipeline_suite.py',
    'scripts/test_fleet_recovery_live_receipts.py',
    'scripts/test_worker_process_streaming.py',
    'scratch/fleet_recovery_live_snapshot_20261026.json',
]
archive = io.BytesIO()
hashes = {}
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
    for filename in sources:
        data = (root / filename).read_bytes()
        hashes[filename] = hashlib.sha256(data).hexdigest()
        bundle.writestr(filename, data)
    bundle.writestr('scripts/bundled_worker.py', worker_source_for_deployment())
payload = base64.b64encode(archive.getvalue()).decode('ascii')
runner = '''import base64, hashlib, io, json, os, pathlib, subprocess, sys, zipfile
root = pathlib.Path('/kaggle/working/fleet_recovery_verification')
root.mkdir(parents=True, exist_ok=True)
zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))).extractall(root)
hashes = HASHES
for name, expected in hashes.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
env = dict(os.environ)
env['PYTHONPATH'] = str(root / 'scripts')
env['FLEET_RECOVERY_SNAPSHOT'] = str(root / 'scratch/fleet_recovery_live_snapshot_20261026.json')
commands = [
    [sys.executable, '-m', 'py_compile', 'scripts/autonomous_icu_pipeline.py', 'scripts/kaggle_engine_worker.py', 'scripts/deploy_kaggle_engines.py', 'scripts/fleet_recovery_policy.py', 'scripts/bundled_worker.py'],
    [sys.executable, '-c', "import bundled_worker; assert bundled_worker.CLINE_MODEL == 'deepseek-v4.1-flash:free'; assert bundled_worker.CLINE_PROVIDER == 'openai-compatible'; assert bundled_worker.CLINE_NODE_EXE is not None; assert callable(bundled_worker.TokenHarborRouter.chat_completion)"],
    [sys.executable, 'scripts/test_icu_pipeline_suite.py'],
    [sys.executable, 'scripts/test_fleet_recovery_live_receipts.py'],
    [sys.executable, 'scripts/test_worker_process_streaming.py'],
]
results = []
for index, command in enumerate(commands):
    process = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=600)
    log = process.stdout + process.stderr
    (root.parent / f'recovery_check_{index}.log').write_text(log, encoding='utf-8')
    print(log, flush=True)
    results.append({'command': command, 'exit_code': process.returncode})
receipt = {'source_sha256': hashes, 'checks': results, 'passed': all(r['exit_code'] == 0 for r in results)}
(root.parent / 'fleet_recovery_verification_receipt.json').write_text(json.dumps(receipt, indent=2))
print('VERIFICATION_RESULT', json.dumps(receipt), flush=True)
raise SystemExit(0 if receipt['passed'] else 1)
'''.replace('PAYLOAD', repr(payload)).replace('HASHES', repr(hashes))
(stage / 'verify.py').write_text(runner, encoding='utf-8')
metadata = dict(
    id='isearchxsolve/fleet-recovery-verification-20261026',
    title='Fleet Recovery Verification 20261026', code_file='verify.py',
    language='python', kernel_type='script', is_private=True,
    enable_gpu=False, enable_internet=False,
    dataset_sources=[], competition_sources=[], kernel_sources=[], model_sources=[],
)
(stage / 'kernel-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
env, error = kaggle_environment('isearchxsolve', None)
if error:
    raise RuntimeError(error)
raise SystemExit(subprocess.run([sys.executable, '-m', 'kaggle', 'kernels', 'push', '-p', str(stage)], env=env).returncode)
