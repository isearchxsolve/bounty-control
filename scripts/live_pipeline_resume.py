"""Restore an actual master campaign without resetting its task or attempt history."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from actions_github import GitHub, utcnow


def restore_files(source, destination, *, source_run, control, target, driver_sha):
    source, destination = Path(source), Path(destination)
    journal = json.loads((source / 'run.json').read_text(encoding='utf-8'))
    if (journal.get('mode') != 'PIPELINE' or journal.get('control') != control
            or journal.get('target') != target or journal.get('existing_issue')):
        raise ValueError('Checkpoint must belong to this unfiltered production campaign')
    if (destination / 'run.json').exists():
        raise ValueError('Refusing to overwrite another campaign journal')
    shutil.copytree(source, destination, dirs_exist_ok=True)
    evidence = destination / 'continuations' / str(source_run['id'])
    evidence.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'run.json', evidence / 'run.json')
    journal.setdefault('continuations', []).append({
        'at': utcnow(), 'source_run': source_run['html_url'],
        'source_driver_sha': source_run['head_sha'], 'driver_sha': driver_sha,
        'previous_deployed_sha': journal.get('deployed_sha')})
    # The prior driver identity remains in the immutable archived journal. This
    # continuation executes the repaired driver; delivery receipts keep their own SHA.
    journal['deployed_sha'] = driver_sha
    journal['end_to_end_passed'] = False
    (destination / 'run.json').write_text(json.dumps(journal, indent=2), encoding='utf-8')
    for child_path in (destination / 'originals').glob('*/run.json'):
        child = json.loads(child_path.read_text(encoding='utf-8'))
        queue = child_path.parent / 'queue'
        if queue.is_dir():
            child['queue_dir'] = str(queue.resolve())
        child_path.write_text(json.dumps(child, indent=2), encoding='utf-8')
    memory = destination / 'entry-scout' / 'discovery-memory'
    memory.mkdir(parents=True, exist_ok=True)
    retained = sorted(str(path.resolve()) for path in (destination / 'entry-scout').glob('run-*/*')
                      if path.name in ('agent.log', 'shortlist.jsonl', 'decisions.jsonl', 'admitted-stream.jsonl'))
    # The aggregate real log is retained when a killed agent never closed agent.log.
    retained += [str(path.resolve()) for path in destination.glob('run-*.log')]
    manifest = memory / 'CONTINUATION.json'
    manifest.write_text(json.dumps({'source_run': source_run['html_url'],
        'retained_entry_observations': retained,
        'instruction': 'Continue the incomplete entry stage from these actual observations. '
                       'Recheck live sources; these logs are not admission or successful test receipts.'}, indent=2),
                       encoding='utf-8')
    notes = memory / 'RESEARCH.md'
    prior = notes.read_text(encoding='utf-8') if notes.exists() else '# Unverified discovery research\n'
    notes.write_text(prior + '\n\nRetained checkpoint: read ' + str(manifest.resolve())
                     + ' before repeating research. Prior observations require live revalidation.\n', encoding='utf-8')
    return journal


def restore_campaign(run_id, destination, control, target, *, api=None):
    if not str(run_id).isdecimal():
        raise ValueError('Resume source must be a GitHub Actions run ID')
    api = api or GitHub()
    run = api.api(f'repos/{control}/actions/runs/{run_id}')
    if (run.get('status') != 'completed'
            or run.get('path') != '.github/workflows/pipeline-live-integration.yml'):
        raise ValueError('Resume requires a completed master integration run from this control repository')
    control_info = api.api(f'repos/{control}')
    driver = api.api(f'repos/{control}/commits/{control_info["default_branch"]}')['sha']
    with tempfile.TemporaryDirectory(prefix='live-checkpoint-') as folder:
        subprocess.run(['gh', 'run', 'download', str(run_id), '--repo', control,
            '--name', 'live-integration-' + str(run_id), '--dir', folder], check=True, timeout=300)
        result = restore_files(folder, destination, source_run=run, control=control,
                               target=target, driver_sha=driver)
    print(json.dumps({'phase': 'RESUMED_CHECKPOINT', 'source_run': run['html_url'],
                      'campaign': result['id'], 'pipeline_admitted': result.get('pipeline_admitted', False),
                      'cohort_size': len(result.get('cohort', {}))}), flush=True)
    return result
