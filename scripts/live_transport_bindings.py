"""Inject faults on actual HTTP/process boundaries of the production GitHub client.

The HTTP endpoint is a labelled local fault resource, not a GitHub success fixture.
No subprocess result, clock reading, or sleep is mocked. Normal GitHub observations
remain direct; these resources exercise otherwise unsafe/unavailable negative conditions.
"""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

from actions_github import GitHub

ACTIVE = None


class Calls:
    def __init__(self, operation):
        self.operation = operation
        self.call_count = 0
    def __call__(self, *args, **kwargs):
        self.call_count += 1
        return self.operation(*args, **kwargs)
    def assert_not_called(self):
        if self.call_count:
            raise AssertionError('Unexpected actual transport call')


def client(**kwargs):
    if ACTIVE is None:
        return GitHub(**kwargs)
    base = ACTIVE.base
    kwargs.setdefault('token', 'non-secret-local-fault-resource')
    if ACTIVE.kind == 'timeout':
        kwargs['deadline'] = time.monotonic() + 0.5
    class Wire(GitHub):
        def api(self, endpoint, *args, **kw):
            return super().api(base + '/' + endpoint.lstrip('/'), *args, **kw)
    return Wire(**kwargs)


@contextlib.contextmanager
def fault(kind, status=500):
    global ACTIVE
    stopped = threading.Event()
    observations = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            observations.append(self.path)
            if kind == 'timeout':
                stopped.wait(3)
                return
            code = status if kind == 'status' else 429 if kind == 'throttle' else 200
            body = {'message': 'rate limit exceeded retry-after 1'} if kind == 'throttle' else {'message': 'injected HTTP boundary fault'}
            if kind == 'page':
                body = {'message': 'invalid page shape'} if 'page=2' in self.path else [{'id': 1}]
            encoded = b'{"partial":' if kind == 'json' else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            if kind == 'page' and 'page=2' not in self.path:
                self.send_header('Link', f'<http://127.0.0.1:{self.server.server_port}/issues?page=2>; rel="next"')
            self.end_headers()
            self.wfile.write(encoded)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    run, sleep = Calls(subprocess.run), Calls(time.sleep)
    previous, old_run, old_sleep = ACTIVE, subprocess.run, time.sleep
    old_path = os.environ.get('PATH')
    old_prompt = os.environ.get('GH_PROMPT_DISABLED')
    with tempfile.TemporaryDirectory() as empty:
        ACTIVE = SimpleNamespace(base=f'http://127.0.0.1:{server.server_port}', kind=kind)
        subprocess.run, time.sleep = run, sleep
        os.environ['GH_PROMPT_DISABLED'] = '1'
        if kind == 'missing':
            os.environ['PATH'] = empty
        try:
            yield SimpleNamespace(run=run, sleep=sleep, observations=observations)
            if kind in ('status', 'json', 'throttle', 'page') and not observations:
                raise AssertionError('The actual HTTP fault resource was never reached')
            if kind == 'page' and len(observations) < 2:
                raise AssertionError('The actual malformed second page was never fetched')
        finally:
            subprocess.run, time.sleep, ACTIVE = old_run, old_sleep, previous
            for name, value in (('PATH', old_path), ('GH_PROMPT_DISABLED', old_prompt)):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            stopped.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            print(json.dumps({'live_transport_fault': kind, 'status_input': status,
                              'actual_cli_calls': run.call_count, 'actual_http_requests': len(observations),
                              'actual_waits': sleep.call_count}), flush=True)
