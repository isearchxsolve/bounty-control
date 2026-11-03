"""Independent durable-state probes on labelled real GitHub fault resources.

The production StateStore and GitHub CLI perform every read/write. Concurrent
writes cause real CAS conflicts. HTTP error and lost-ack resources inject faults
at the actual wire boundary; repository dispatches go only to a verified sandbox
without a repository_dispatch workflow, never the production delivery repository.
"""
import base64
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
from types import SimpleNamespace
import unittest
import uuid

from actions_github import GitHub, GitHubError, StateStore


class Calls:
    def __init__(self, operation):
        self.operation, self.call_count, self.call_args = operation, 0, None
        self.side_effect = None
    def __call__(self, *args, **kwargs):
        self.call_count += 1
        self.call_args = SimpleNamespace(args=args, kwargs=kwargs)
        return self.operation(*args, **kwargs)
    def assert_not_called(self):
        if self.call_count:
            raise AssertionError('Unexpected actual repository dispatch')


def new_store():
    store = StateStore(GitHub(), os.environ.get(
        'LIVE_DURABLE_CONTROL', 'isearchxsolve/oss-hunter-livefire'))
    if store.repo == 'isearchxsolve/bounty-control':
        raise ValueError('Durable dispatch fault inputs require a separate sandbox repository')
    store.branch = 'live-probes/durable-' + uuid.uuid4().hex
    store.ensure()
    print(json.dumps({'durable_fault_repository': store.repo, 'branch': store.branch}), flush=True)
    return store


@contextlib.contextmanager
def http_fault(handler):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/fault'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def json_body(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b';', 1)[0], 16)
                if not size:
                    while self.rfile.readline().strip():
                        pass
                    break
                chunks.append(self.rfile.read(size))
                if self.rfile.read(2) != b'\r\n':
                    raise ValueError('Malformed actual HTTP chunk framing')
            body = b''.join(chunks)
        else:
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        return json.loads(body)


@contextlib.contextmanager
def conflict(identity, exhausted=False):
    store = new_store()
    store.mutate(identity, lambda old: {'status': 'CLAIMED', 'count': 1, 'fault_fixture': True})
    contender = StateStore(GitHub(), store.repo)
    contender.branch = store.branch
    original = store.write
    winning = SimpleNamespace(sha=None)
    def competing_write(*args):
        if exhausted or write.call_count == 1:
            contender.mutate(identity, lambda old: {**old, 'count': 9,
                                                   'competing_write': uuid.uuid4().hex})
            winning.sha = contender.read(identity)[1]
        return original(*args)
    write = Calls(competing_write)
    store.write = write
    yield store, write, winning


@contextlib.contextmanager
def write_failure(identity, status):
    if status == 409:
        with conflict(identity, exhausted=True) as (store, write, winning):
            yield store, write
        return
    store = new_store()
    store.mutate(identity, lambda old: {'status': 'DISPATCHING', 'fault_fixture': True})
    requests = []
    class RejectPUT(QuietHandler):
        def do_PUT(self):
            document = self.json_body()
            if document.get('branch') != store.branch:
                raise AssertionError('Fault request escaped its isolated branch')
            requests.append(document)
            payload = json.dumps({'message': f'injected durable HTTP {status}'}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    with http_fault(RejectPUT) as endpoint:
        class WriteFaultAPI(GitHub):
            def api(self, path, method='GET', data=None, **kwargs):
                if method == 'PUT':
                    return GitHub(token='non-secret-local-fault-resource').api(endpoint, method, data, **kwargs)
                return super().api(path, method, data, **kwargs)
        store.api = WriteFaultAPI()
        write = Calls(store.write)
        store.write = write
        yield store, write
        if len(requests) < write.call_count:
            raise AssertionError('A durable failure bypassed the actual HTTP fault resource')
        print(json.dumps({'injected_durable_status': status, 'actual_put_requests': len(requests)}), flush=True)


class RemoteRow:
    def __init__(self, store, identity):
        self.store, self.identity = store, identity
    def __getitem__(self, field):
        return self.store.read(self.identity)[0][field]
    def __setitem__(self, field, value):
        self.store.mutate(self.identity, lambda row: {**row, field: value})


class Rows:
    def __init__(self, store):
        self.store = store
    def __getitem__(self, identity):
        return RemoteRow(self.store, identity)


def dispatch_fixture():
    store = new_store()
    # Every dispatch is accepted by a real sandbox repository with no receiver
    # capable of starting customer engineering work.
    workflows = store.api.api(f'repos/{store.repo}/actions/workflows')['workflows']
    for workflow in workflows:
        content = store.api.api(f'repos/{store.repo}/contents/{workflow["path"]}')
        if 'repository_dispatch' in base64.b64decode(content['content']).decode():
            raise unittest.SkipTest('BLOCKED: sandbox workflow declares repository_dispatch; use a receiver-free probe repository')
    store.rows = Rows(store)
    upstream = GitHub()
    accepted = []
    operation = None
    def send(path, method='GET', data=None, **kwargs):
        if path != f'repos/{store.repo}/dispatches' or method != 'POST':
            raise AssertionError('Dispatch escaped the isolated probe repository')
        effect = operation.side_effect
        if isinstance(effect, Exception):
            class LoseAcknowledgement(QuietHandler):
                def do_POST(self):
                    payload = self.json_body()
                    upstream.api(path, 'POST', payload)
                    accepted.append(payload['client_payload']['dispatch_id'])
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
            with http_fault(LoseAcknowledgement) as endpoint:
                try:
                    return GitHub(token='non-secret-local-fault-resource').api(endpoint, 'POST', data)
                finally:
                    if len(accepted) != 1:
                        raise AssertionError(f'Lost-ack probe accepted {len(accepted)} real dispatches instead of one')
                    print(json.dumps({'real_dispatch_accepted': accepted, 'acknowledgement': 'connection closed'}), flush=True)
        result = upstream.api(path, method, data, **kwargs)
        accepted.append(data['client_payload']['dispatch_id'])
        if callable(effect):
            effect(path, method, data)
        print(json.dumps({'real_dispatch_accepted': accepted, 'repository': store.repo}), flush=True)
        return result
    operation = Calls(send)
    return store, SimpleNamespace(api=operation)


@contextlib.contextmanager
def unavailable_reservation(store):
    previous = store.api
    store.api = GitHub(token='invalid-live-durable-storage-probe')
    try:
        yield
    finally:
        store.api = previous
