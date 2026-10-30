"""Deploy the Kaggle-verified task integrity repair without replacing relay bindings."""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from deploy_local_fleet_proxy import BASE, ROOT, api_headers, get_live


def main():
    stage = ROOT / 'scratch/redeploy_e2e_20261026'
    receipt = json.loads((stage / 'verification/output_v2/dispatch_repair_receipt.json').read_text())
    if receipt.get('passed') is not True:
        raise RuntimeError('Kaggle verification did not pass')
    repair = ROOT / 'scratch/relay_coordinator_repair'
    names = ('worker.js', 'web_job_coordinator.js', 'film_vault.js')
    hashes = {}
    for name in names:
        source = repair / name
        expected = receipt['source_sha256']['scratch/relay_coordinator_repair/' + name]
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Source changed after Kaggle verification: ' + name)
        hashes[name] = actual
    headers = api_headers()
    headers['User-Agent'] = 'Mozilla/5.0 (compatible; fleet-dispatch-integrity/1.0)'
    settings, live = get_live(headers)
    before = stage / 'relay-before'
    recorded = json.loads((before / 'settings.json').read_text())
    if settings.get('bindings') != recorded.get('bindings'):
        raise RuntimeError('Concurrent binding change; refusing deployment')
    for name in names:
        if live.get(name) != (before / name).read_bytes():
            raise RuntimeError('Concurrent live source change: ' + name)
        if name != 'worker.js' and live[name] != (repair / name).read_bytes():
            raise RuntimeError('Unrelated relay module must remain byte-identical: ' + name)
    bindings = []
    for binding in settings.get('bindings', []):
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
        'annotations': {'workers/message': 'Preserve fleet task JSON and reject malformed tasks'},
    }
    boundary = 'dispatch-integrity-' + uuid.uuid4().hex
    parts = []

    def add(name, data, content_type, filename=None):
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        parts.append((f'--{boundary}\r\n{disposition}\r\nContent-Type: {content_type}\r\n\r\n').encode() + data + b'\r\n')

    add('metadata', json.dumps(metadata).encode(), 'application/json')
    for name in names:
        add(name, (repair / name).read_bytes(), 'application/javascript+module', name)
    payload = b''.join(parts) + f'--{boundary}--\r\n'.encode()
    request = urllib.request.Request(BASE, data=payload, method='PUT', headers={
        **headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary,
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode('utf-8', errors='replace')
        raise RuntimeError(f'Worker upload rejected: HTTP {error.code}: {detail}') from None
    if result.get('success') is not True:
        raise RuntimeError('Worker deployment was not accepted')
    after, deployed = get_live(headers)
    if after.get('bindings') != settings.get('bindings'):
        raise RuntimeError('Binding identity changed during upload')
    for name, digest in hashes.items():
        if hashlib.sha256(deployed[name]).hexdigest() != digest:
            raise RuntimeError('Deployed source hash mismatch: ' + name)
    saved = {'success': True, 'deployment_id': result.get('result', {}).get('deployment_id'),
             'source_sha256': hashes, 'bindings_preserved': [b['name'] for b in settings.get('bindings', [])]}
    (stage / 'relay-integrity-deployment.json').write_text(json.dumps(saved, indent=2), encoding='utf-8')
    print(json.dumps(saved, indent=2))


if __name__ == '__main__':
    main()
