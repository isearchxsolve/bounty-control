"""Bounded native jobs for agents whose shell calls have a short timeout.

The agent chooses the command. This tool records bytes and the OS exit status;
neither a live PID nor a quiet log is evidence of successful completion.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def write_json(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def stop_process(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    process.wait(timeout=10)


def execute_job(folder):
    request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
    started = time.time()
    deadline = time.monotonic() + request['timeout']
    process = None
    receipt = {'started_at': started, 'status': 'START_FAILED', 'exit_code': None}
    try:
        with (folder / 'stdout.log').open('wb') as out, (folder / 'stderr.log').open('wb') as err:
            options = {'start_new_session': True} if os.name == 'posix' else {
                'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            process = subprocess.Popen(request['argv'], cwd=request['cwd'], stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err, **options)
            write_json(folder / 'started.json', {'pid': process.pid, 'started_at': started})
            reason = 'EXITED'
            while process.poll() is None:
                if (folder / 'cancel').exists() or time.monotonic() >= deadline:
                    reason = 'CANCELLED' if (folder / 'cancel').exists() else 'TIMED_OUT'
                    stop_process(process)
                    break
                time.sleep(0.1)
            receipt.update(status=reason, exit_code=process.wait())
    except (OSError, subprocess.SubprocessError) as exc:
        receipt['error'] = str(exc)
    finally:
        if process is not None and process.poll() is None:
            stop_process(process)
        receipt['finished_at'] = time.time()
        write_json(folder / 'exit.json', receipt)


def observe(folder, cursor, wait):
    generation, stdout_offset, stderr_offset = map(int, cursor.split(':'))
    if min(generation, stdout_offset, stderr_offset) < 0:
        raise ValueError('Cursor values must be nonnegative')
    until = time.monotonic() + wait
    while not (folder / 'exit.json').exists() and time.monotonic() < until:
        time.sleep(min(0.1, max(0, until - time.monotonic())))
    receipt = (json.loads((folder / 'exit.json').read_text(encoding='utf-8'))
               if (folder / 'exit.json').exists() else
               {'status': 'PENDING_EXIT_RECEIPT', 'exit_code': None})
    offsets = []
    for name, offset in (('stdout', stdout_offset), ('stderr', stderr_offset)):
        path = folder / (name + '.log')
        if path.exists():
            with path.open('rb') as handle:
                if offset > path.stat().st_size:
                    raise ValueError('Cursor exceeds actual log size')
                handle.seek(offset)
                receipt[name] = handle.read(16384).decode('utf-8', errors='replace')
                offsets.append(handle.tell())
        else:
            if offset:
                raise ValueError('Cursor references a missing log')
            receipt[name] = ''
            offsets.append(0)
    # An observation sequence plus byte offsets lets a caller request the next real
    # observation even during a quiet compile, without repeating an identical tool call.
    receipt.update(job=str(folder), observed_at=time.time(),
                   next_cursor=f'{generation + 1}:{offsets[0]}:{offsets[1]}')
    return receipt


def positive_seconds(value):
    value = float(value)
    if not 0 < value <= 14400:
        raise argparse.ArgumentTypeError('Timeout must be >0 and <=14400 seconds')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    start = commands.add_parser('start')
    start.add_argument('--root', type=Path, required=True)
    start.add_argument('--cwd', type=Path, required=True)
    start.add_argument('--timeout', type=positive_seconds, required=True)
    start.add_argument('argv', nargs=argparse.REMAINDER)
    wait = commands.add_parser('wait')
    wait.add_argument('job', type=Path)
    wait.add_argument('--cursor', required=True, help='Use the previous next_cursor; initially 0:0:0')
    wait.add_argument('--seconds', type=float, default=20)
    cancel = commands.add_parser('cancel')
    cancel.add_argument('job', type=Path)
    worker = commands.add_parser('_execute')
    worker.add_argument('job', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'start':
        command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
        if not command:
            parser.error('Supply an actual command after --')
        if not args.cwd.is_dir():
            parser.error('Working directory does not exist')
        folder = args.root.resolve() / uuid.uuid4().hex
        folder.mkdir(parents=True)
        write_json(folder / 'request.json', {'argv': command, 'cwd': str(args.cwd.resolve()),
                                             'timeout': args.timeout})
        options = {'start_new_session': True} if os.name == 'posix' else {
            'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        with (folder / 'worker.log').open('wb') as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_execute', str(folder)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        result = {'job': str(folder), 'next_cursor': '0:0:0', 'status': 'START_REQUESTED'}
    elif args.action == '_execute':
        execute_job(args.job.resolve())
        return
    else:
        folder = args.job.resolve()
        if not (folder / 'request.json').is_file():
            parser.error('Job request does not exist')
        if args.action == 'cancel':
            (folder / 'cancel').touch()
            result = {'job': str(folder), 'status': 'CANCELLATION_REQUESTED'}
        else:
            if not 0 <= args.seconds <= 20:
                parser.error('Wait must be between 0 and 20 seconds')
            result = observe(folder, args.cursor, args.seconds)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
