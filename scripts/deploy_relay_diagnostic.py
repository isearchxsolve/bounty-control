"""Upload the verified diagnostic patch while retaining existing relay bindings."""
import email.parser
import email.policy
import hashlib
import json
import sys
from pathlib import Path
import tomllib
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = 'c95d86ef4985346cae29bcd4dbfc67af'
BASE = f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/omniroute-relay'


def main():
    bounded = '--bounded-reads' in sys.argv
    receipt_folder = 'v3_output' if bounded else 'output'
    receipt = json.loads((ROOT / f'scratch/relay_patch_verification/{receipt_folder}/relay_syntax_receipt.json').read_text())
    if not receipt['passed']:
        raise RuntimeError('Kaggle relay syntax verification failed')
    if bounded and not receipt.get('sqlite_passed'):
        raise RuntimeError('Real SQLite verification is required')
    repair = ROOT / 'scratch/relay_coordinator_repair'
    for check in receipt['checks']:
        if hashlib.sha256((repair / check['module']).read_bytes()).hexdigest() != check['sha256']:
            raise RuntimeError('Relay source changed after cloud verification')
    for name in (('film_vault.js',) if bounded else ('film_vault.js', 'web_job_coordinator.js')):
        if (repair / name).read_bytes() != (ROOT / 'scratch/cloudflare_relay_live/original' / name).read_bytes():
            raise RuntimeError('Diagnostic deployment must retain the existing coordinator and film modules')
    auth = tomllib.loads(Path('C:/Users/Admin/AppData/Roaming/xdg.config/.wrangler/config/default.toml').read_text())
    headers = {'Authorization': 'Bearer ' + auth['oauth_token']}
    with urllib.request.urlopen(urllib.request.Request(BASE + '/settings', headers=headers), timeout=20) as response:
        settings = json.load(response)['result']
    recorded = json.loads((ROOT / 'scratch/cloudflare_worker_settings.json').read_text())['result']
    if settings['bindings'] != recorded['bindings']:
        raise RuntimeError('Live relay bindings changed; refusing to overwrite concurrent changes')
    with urllib.request.urlopen(urllib.request.Request(BASE, headers=headers), timeout=20) as response:
        content_type = response.headers['Content-Type']
        raw = response.read()
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
    current = {(part.get_filename() or part.get_param('name', header='content-disposition')):
               part.get_payload(decode=True) for part in message.iter_parts()}
    if bounded:
        for name in ('worker.js', 'web_job_coordinator.js', 'film_vault.js'):
            if current.get(name) != (ROOT / 'scratch/relay_before_optimization' / name).read_bytes():
                raise RuntimeError('Live relay source changed; refusing to overwrite concurrent changes')
    elif current.get('worker.js') != (ROOT / 'scratch/cloudflare_relay_live/worker.js').read_bytes():
        raise RuntimeError('Live relay source changed; refusing to overwrite concurrent changes')
    bindings = []
    for binding in settings['bindings']:
        if binding['type'] in ('secret_text', 'secret_key'):
            continue
        if binding['type'] == 'durable_object_namespace':
            bindings.append({key: binding[key] for key in ('type', 'name', 'class_name', 'script_name', 'environment') if key in binding})
        else:
            bindings.append(binding)
    metadata = {
        'main_module': 'worker.js', 'bindings': bindings,
        'keep_bindings': ['secret_text', 'secret_key'],
        'compatibility_date': settings['compatibility_date'],
        'compatibility_flags': settings.get('compatibility_flags', []),
        'usage_model': settings.get('usage_model', 'standard'),
        'logpush': settings.get('logpush', False),
        'tail_consumers': settings.get('tail_consumers', []),
        'tags': settings.get('tags', []),
    }
    boundary = 'fleet-relay-' + uuid.uuid4().hex
    parts = []
    def add(name, data, content_type, filename=None):
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        parts.append((f'--{boundary}\r\n{disposition}\r\nContent-Type: {content_type}\r\n\r\n').encode() + data + b'\r\n')
    add('metadata', json.dumps(metadata).encode(), 'application/json')
    for path in sorted(repair.glob('*.js')):
        add(path.name, path.read_bytes(), 'application/javascript+module', path.name)
    payload = b''.join(parts) + f'--{boundary}--\r\n'.encode()
    request = urllib.request.Request(BASE, data=payload, method='PUT', headers={
        **headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary,
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        deployed = json.load(response)
    artifact = 'relay_bounded_reads_deployment.json' if bounded else 'relay_diagnostic_deployment.json'
    (ROOT / 'scratch' / artifact).write_text(json.dumps(deployed, indent=2))
    if not deployed.get('success'):
        raise RuntimeError('Cloudflare rejected the diagnostic deployment')
    with urllib.request.urlopen(urllib.request.Request(BASE + '/settings', headers=headers), timeout=20) as response:
        after = json.load(response)['result']
    old_ids = {b['name']: b.get('namespace_id') for b in settings['bindings'] if b['type'] == 'durable_object_namespace'}
    new_ids = {b['name']: b.get('namespace_id') for b in after['bindings'] if b['type'] == 'durable_object_namespace'}
    if old_ids != new_ids:
        raise RuntimeError('Durable Object identity changed unexpectedly')
    if {b['name'] for b in settings['bindings']} != {b['name'] for b in after['bindings']}:
        raise RuntimeError('Relay binding set changed unexpectedly')
    print('Diagnostic deployed; existing Durable Object IDs, secret bindings, KV, and R2 bindings retained.')


if __name__ == '__main__':
    main()
