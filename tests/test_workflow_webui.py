import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from comfyui_control.workflow_webui import WorkflowWebUI


class FixtureServer:
    def __init__(self):
        self.ready = True
        self.wrong = False
        self.paths = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.paths.append(self.path)
                self.send_response(200 if owner.ready or owner.wrong else 503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                try:
                    self.wfile.write(json.dumps({'hello': 'other server'} if owner.wrong else
                        {'system': {'os': 'fixture'}, 'devices': []} if owner.ready else {'error': 'starting'}).encode())
                except (BrokenPipeError, ConnectionResetError): pass
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler, bind_and_activate=False)
        self.server.server_bind()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'
        self.thread = None
    def start(self):
        self.server.server_activate()
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
    def close(self):
        if self.thread:
            self.server.shutdown(); self.thread.join(timeout=2)
        self.server.server_close()


@pytest.fixture
def server():
    fixture = FixtureServer()
    yield fixture
    fixture.close()


def wait(opener):
    deadline = time.monotonic() + 4
    while opener.busy and time.monotonic() < deadline: QTest.qWait(10)
    assert not opener.busy


def build(server, state='stopped', confirm=True, **kwargs):
    current = {'state': state}
    opened, starts, questions, statuses = [], [], [], []
    def start():
        starts.append(True)
        current['state'] = 'starting'
        server.ready = False
        server.start()
        QTimer.singleShot(50, lambda: setattr(server, 'ready', True))
        return True
    def ask(): questions.append(True); return confirm
    def open_url(url):
        assert server.ready and not server.wrong, 'Browser opened before ComfyUI readiness'
        opened.append(url.toString())
        return True
    opener = WorkflowWebUI(server.url, state=lambda: current['state'], start=start, confirm=ask,
        open_url=open_url,
        retry_ms=20, request_ms=200, wait_seconds=.4, **kwargs)
    opener.status.connect(statuses.append)
    return opener, current, opened, starts, questions, statuses


def test_ready_external_server_opens_without_start_or_confirmation(app, server):
    server.start()
    opener, _, opened, starts, questions, _ = build(server)
    opener.open(); wait(opener)
    assert opened == [server.url] and not starts and not questions
    assert server.paths == ['/system_stats']


def test_stopped_server_starts_once_then_opens_only_after_ready(app, server):
    opener, _, opened, starts, questions, _ = build(server)
    opener.open(); opener.open()
    wait(opener)
    assert starts == [True] and questions == [True] and opened == [server.url]
    assert server.ready and server.paths


def test_cancelled_start_never_starts_or_opens(app, server):
    opener, _, opened, starts, questions, statuses = build(server, confirm=False)
    opener.open(); wait(opener)
    assert questions == [True] and not starts and not opened
    assert 'not started' in statuses[-1]


@pytest.mark.parametrize('state', ['starting', 'running', 'restarting'])
def test_existing_process_waits_for_api_without_duplicate_start(app, server, state):
    server.ready = False; server.start()
    opener, _, opened, starts, questions, _ = build(server, state=state)
    opener.open()
    QTimer.singleShot(60, lambda: setattr(server, 'ready', True))
    wait(opener)
    assert opened == [server.url] and not starts and not questions


def test_readiness_timeout_does_not_open_or_restart(app, server):
    server.ready = False; server.start()
    opener, _, opened, starts, questions, statuses = build(server, state='running')
    opener.open(); wait(opener)
    assert not opened and not starts and not questions and 'not ready' in statuses[-1]


def test_crash_while_waiting_stops_without_browser(app, server):
    server.ready = False; server.start()
    opener, current, opened, starts, _, statuses = build(server, state='starting')
    opener.open()
    QTimer.singleShot(30, lambda: current.update(state='crashed'))
    wait(opener)
    assert not opened and not starts and 'stopped' in statuses[-1]


def test_close_cancels_pending_browser_open(app, server):
    server.ready = False; server.start()
    opener, _, opened, starts, _, _ = build(server, state='running')
    opener.open()
    QTimer.singleShot(30, opener.cancel)
    QTimer.singleShot(60, lambda: setattr(server, 'ready', True))
    QTest.qWait(120)
    assert not opener.busy and not opened and not starts


def test_wrong_http_server_never_triggers_local_start(app, server):
    server.wrong = True; server.start()
    opener, _, opened, starts, questions, statuses = build(server)
    opener.open(); wait(opener)
    assert not opened and not starts and not questions and 'could not be verified' in statuses[-1]


@pytest.mark.parametrize('state', ['updating', 'stopping', 'unavailable'])
def test_busy_or_changed_installation_does_not_start(app, server, state):
    opener, _, opened, starts, questions, statuses = build(server, state=state)
    opener.open(); wait(opener)
    assert not opened and not starts and not questions and 'operation' in statuses[-1]


def test_controller_rejecting_start_does_not_open(app, server):
    opener, _, opened, _, _, statuses = build(server)
    opener.start = lambda: False
    opener.open(); wait(opener)
    assert not opened and 'could not be started' in statuses[-1]


def test_changed_installation_never_opens_even_if_old_endpoint_is_ready(app, server):
    server.start()
    opener, _, opened, starts, questions, _ = build(server, state='unavailable')
    opener.open(); wait(opener)
    assert not opened and not starts and not questions


def test_failed_browser_launch_reports_error_without_start(app, server):
    server.start()
    opener, _, opened, starts, questions, statuses = build(server)
    opener.open_url = lambda url: False
    opener.open(); wait(opener)
    assert not opened and not starts and not questions and 'Could not open the browser' in statuses[-1]
