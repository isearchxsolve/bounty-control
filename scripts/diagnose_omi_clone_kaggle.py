"""Measure Omi clone behavior on Kaggle; keep GitHub credentials in its dataset."""
import json
from pathlib import Path
import subprocess
import sys

stage = Path(__file__).resolve().parent.parent / 'scratch/omi_clone_diagnostic_20261026'
stage.mkdir(parents=True, exist_ok=True)
code = r'''import base64, glob, json, os, pathlib, signal, subprocess, time
root = pathlib.Path('/kaggle/working')
full_timeout = FULL_TIMEOUT_SECONDS
files = glob.glob('/kaggle/input/**/github_token.txt', recursive=True)
if len(files) != 1:
    raise RuntimeError('Expected exactly one private GitHub credential file')
token = pathlib.Path(files[0]).read_text().strip()
env = dict(os.environ)
env['GIT_TERMINAL_PROMPT'] = '0'
env['GIT_CONFIG_COUNT'] = '1'
env['GIT_CONFIG_KEY_0'] = 'http.https://github.com/.extraheader'
env['GIT_CONFIG_VALUE_0'] = 'Authorization: Basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
results = []
def run(label, argv, timeout):
    start = time.monotonic()
    p = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(p.pid, signal.SIGTERM)
        try:
            out, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate()
    row = dict(label=label, argv=argv, timeout=timeout, timed_out=timed_out,
               elapsed_seconds=round(time.monotonic()-start, 2), exit_code=p.returncode,
               stdout=out.replace(token, '[REDACTED]'), stderr=err.replace(token, '[REDACTED]'))
    results.append(row)
    (root / 'omi_clone_diagnostic.json').write_text(json.dumps(results, indent=2))
    print(label, 'elapsed=', row['elapsed_seconds'], 'exit=', p.returncode, 'timeout=', timed_out, flush=True)
    print(row['stderr'][-1800:], flush=True)
    return row
run('git_version', ['git', '--version'], 10)
url = 'https://github.com/isearchxsolve/omi'
run('github_handshake', ['git', 'ls-remote', '--symref', url, 'HEAD'], 45)
full = str(root / 'omi_full_clone_diagnostic')
run(f'original_full_clone_{full_timeout}s', ['git', 'clone', '--progress', url, full], full_timeout)
if pathlib.Path(full).exists():
    state = dict(label='destination_after_first_clone', exists=True,
                 git_exists=pathlib.Path(full, '.git').exists(), entries=[p.name for p in pathlib.Path(full).iterdir()][:20])
    results.append(state)
    print(json.dumps(state), flush=True)
    if results[-2]['exit_code'] != 0:
        run('same_destination_retry', ['git', 'clone', '--progress', url, full], 15)
run('shallow_single_branch_clone', ['git', 'clone', '--progress', '--depth', '1', '--single-branch', '--no-tags', '--branch', 'main', url, str(root / 'omi_shallow_clone_diagnostic')], 180)
(root / 'omi_clone_diagnostic.json').write_text(json.dumps(results, indent=2))
'''
full_timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 90
if full_timeout not in (90, 600):
    raise ValueError('Choose the original 90s limit or the proposed 600s limit.')
code = code.replace('FULL_TIMEOUT_SECONDS', str(full_timeout))
(stage / 'audit.py').write_text(code, encoding='utf-8')
metadata = dict(
    id='isearchxsolve/omi-clone-diagnostic-20261026', title='Omi Clone Diagnostic 20261026',
    code_file='audit.py', language='python', kernel_type='script', is_private=True,
    enable_gpu=False, enable_internet=True,
    dataset_sources=['isearchxsolve/omniroute-github-credential-20261026'],
    competition_sources=[], kernel_sources=[], model_sources=[],
)
(stage / 'kernel-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
raise SystemExit(subprocess.run([sys.executable, '-m', 'kaggle', 'kernels', 'push', '-p', str(stage)]).returncode)
