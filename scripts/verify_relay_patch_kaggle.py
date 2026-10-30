"""Parse the real Cloudflare relay modules on Kaggle before uploading a patch."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parent.parent
stage = root / 'scratch/relay_patch_verification'
stage.mkdir(parents=True, exist_ok=True)
buffer = io.BytesIO()
hashes = {}
with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted((root / 'scratch/relay_coordinator_repair').glob('*.js')):
        data = path.read_bytes()
        hashes[path.name] = hashlib.sha256(data).hexdigest()
        bundle.writestr(path.name, data)
    bundle.writestr('snapshot.json', (root / 'scratch/fleet_recovery_live_snapshot_20261026.json').read_bytes())
    bundle.writestr('scripts/fleet_local_relay.py', (root / 'scripts/fleet_local_relay.py').read_bytes())
    bundle.writestr('scripts/test_fleet_local_relay.py', (root / 'scripts/test_fleet_local_relay.py').read_bytes())
    bundle.writestr('scripts/migrate_fleet_ledger_to_sqlite.py', (root / 'scripts/migrate_fleet_ledger_to_sqlite.py').read_bytes())
    bundle.writestr('scripts/deploy_local_fleet_proxy.py', (root / 'scripts/deploy_local_fleet_proxy.py').read_bytes())
    bundle.writestr('scripts/record_fresh_fleet_epoch.py', (root / 'scripts/record_fresh_fleet_epoch.py').read_bytes())
    bundle.writestr('war-log/son-relay.js', (root / 'war-log/son-relay.js').read_bytes())
payload = base64.b64encode(buffer.getvalue()).decode()
runner = '''import base64, hashlib, io, json, os, pathlib, shutil, subprocess, sys, zipfile
root=pathlib.Path('/kaggle/working/relay_source');root.mkdir(exist_ok=True)
zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))).extractall(root)
node=shutil.which('node')
if not node:
    subprocess.run(['apt-get','update','-qq'],check=False,timeout=180)
    subprocess.run(['apt-get','install','-y','-qq','nodejs'],check=True,timeout=240)
    node=shutil.which('node')
if not node: raise RuntimeError('Node parser is unavailable')
checks=[]
for name, expected in HASHES.items():
    data=(root/name).read_bytes()
    assert hashlib.sha256(data).hexdigest()==expected
    p=subprocess.run([node,'--input-type=module','--check'],input=data,capture_output=True,timeout=30)
    print(name,p.returncode,p.stderr.decode(errors='replace'),flush=True)
    checks.append({'module':name,'sha256':expected,'exit_code':p.returncode})
env=dict(os.environ);env['PYTHONPATH']=str(root/'scripts');env['FLEET_RELAY_DB']=str(root.parent/'fleet-relay-test.sqlite3');env['FLEET_RECOVERY_SNAPSHOT']=str(root/'snapshot.json')
for name in ('scripts/fleet_local_relay.py','scripts/test_fleet_local_relay.py','scripts/migrate_fleet_ledger_to_sqlite.py','scripts/deploy_local_fleet_proxy.py','scripts/record_fresh_fleet_epoch.py'):
    p=subprocess.run([sys.executable,'-m','py_compile',name],cwd=root,env=env,capture_output=True,timeout=30)
    print(name,'py_compile',p.returncode,p.stderr.decode(errors='replace'),flush=True)
    checks.append({'module':name,'exit_code':p.returncode})
p=subprocess.run([sys.executable,'scripts/test_fleet_local_relay.py'],cwd=root,env=env,capture_output=True,text=True,timeout=120)
print(p.stdout,p.stderr,flush=True);checks.append({'module':'test_fleet_local_relay.py','exit_code':p.returncode})
node_source=(root/'war-log/son-relay.js').read_bytes()
p=subprocess.run([node,'--check'],input=node_source,capture_output=True,timeout=30)
print('son-relay.js',p.returncode,p.stderr.decode(errors='replace'),flush=True)
checks.append({'module':'son-relay.js','exit_code':p.returncode})
import sqlite3, re
source=(root/'web_job_coordinator.js').read_text()
statements=re.findall(r'this\.sql\.exec\("([^"]+)"',source)
def sql(prefix):
    return next(statement for statement in statements if statement.startswith(prefix))
database=sqlite3.connect(':memory:')
database.execute(sql('CREATE TABLE IF NOT EXISTS ledger_orders'))
# Exercise migration from the actual pre-patch metadata schema.
database.execute('CREATE TABLE ledger_meta (id INTEGER PRIMARY KEY CHECK(id=1), initialized INTEGER NOT NULL)')
database.execute(sql('ALTER TABLE ledger_meta'))
database.execute('INSERT INTO ledger_meta(id,initialized) VALUES(1,1)')
snapshot=json.loads((root/'snapshot.json').read_text())
records=[row for rows in snapshot.values() if isinstance(rows,list) for row in rows if isinstance(row,dict) and isinstance(row.get('text'),str) and isinstance(row.get('at'),(int,float))]
assert records, 'Real ledger snapshot required'
for index,record in enumerate(records):
    encoded=json.dumps({'at':record['at'],'text':record['text']},separators=(',',':'))
    count=database.execute('SELECT COUNT(*) FROM ledger_orders').fetchone()[0]
    database.execute(sql('INSERT INTO ledger_orders(dedupe,body) VALUES'),(str(index),encoded))
    if count>=2000:
        database.execute(sql('DELETE FROM ledger_orders WHERE id IN'),(count+1-2000,))
    database.execute(sql('UPDATE ledger_meta SET record_count'),(min(count+1,2000),))
    assert database.execute('SELECT record_count FROM ledger_meta').fetchone()[0]==database.execute('SELECT COUNT(*) FROM ledger_orders').fetchone()[0]
full=database.execute('SELECT body FROM ledger_orders ORDER BY id DESC LIMIT 2000').fetchall()
for limit in (1,20,100,200,2000):
    bounded=database.execute(sql('SELECT body FROM ledger_orders ORDER BY id DESC LIMIT ?'),(limit,)).fetchall()
    assert bounded==full[:limit]
chronological=database.execute('SELECT body FROM ledger_orders ORDER BY id ASC').fetchall()
page_statement=sql('SELECT body FROM ledger_orders ORDER BY id ASC LIMIT ? OFFSET ?')
for offset in range(0,len(chronological),200):
    page=database.execute(page_statement,(200,offset)).fetchall()
    assert page==chronological[offset:offset+200]
assert database.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print('Real SQLite migration, append counts, bounded reads and integrity passed:',len(records),'authentic snapshot receipts',flush=True)
receipt={'checks':checks,'sqlite_real_receipts':len(records),'sqlite_passed':True,'passed':all(c['exit_code']==0 for c in checks)}
(root.parent/'relay_syntax_receipt.json').write_text(json.dumps(receipt,indent=2))
raise SystemExit(0 if receipt['passed'] else 1)
'''.replace('PAYLOAD', repr(payload)).replace('HASHES', repr(hashes))
(stage / 'verify.py').write_text(runner, encoding='utf-8')
metadata = dict(
    id='isearchxsolve/relay-patch-verification-20261026', title='Relay Patch Verification 20261026',
    code_file='verify.py', language='python', kernel_type='script', is_private=True,
    enable_gpu=False, enable_internet=True, dataset_sources=[], competition_sources=[], kernel_sources=[], model_sources=[],
)
(stage / 'kernel-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
raise SystemExit(subprocess.run([sys.executable,'-m','kaggle','kernels','push','-p',str(stage)]).returncode)
