"""Real foreground demo startup without a configured ComfyUI installation."""
import http.cookiejar
import json
import os
import signal
import subprocess
import sys
import urllib.request
import uuid

import pytest

from test_headless import Running, unused_port, wait


@pytest.fixture
def preview(tmp_path):
    settings = tmp_path / 'settings' / 'comfyui-control'
    settings.mkdir(parents=True)
    # Invalid existing settings must not be loaded or "fixed" by preview mode.
    (settings / 'config.json').write_bytes(b'private config sentinel, not JSON')
    (settings / 'mobile').mkdir()
    (settings / 'mobile' / 'settings.json').write_bytes(b'private mobile sentinel')
    snapshot = {p.relative_to(settings): p.read_bytes() for p in settings.rglob('*') if p.is_file()}
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    port = unused_port()
    env = {**os.environ, 'XDG_CONFIG_HOME': str(tmp_path / 'settings'), 'TMPDIR': str(scratch),
           'QT_QPA_PLATFORM': 'invalid-demo-needs-no-display'}
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
        env.pop(key, None)
    runner = Running([sys.executable, '-m', 'comfyui_control.cli', '--demo-webui', '--demo-port', str(port)], env)
    try:
        wait(lambda: 'Demo WebUI:' in runner.text or runner.process.poll() is not None, timeout=15)
        assert runner.process.poll() is None, runner.text
        origin = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def request(path, body=None):
            headers = {'Origin': origin, 'Content-Type': 'application/json'}
            req = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
            with opener.open(req, timeout=5) as response:
                return response.read()
        request('/api/session')
        yield runner, request, scratch
    finally:
        if runner.process.poll() is None:
            assert runner.stop(signal.SIGINT) == 0, runner.text
        assert not list(scratch.iterdir()), 'Temporary demo data was left behind'
        assert snapshot == {p.relative_to(settings): p.read_bytes() for p in settings.rglob('*') if p.is_file()}


def submit(request):
    presets = json.loads(request('/api/presets'))
    preset = json.loads(request('/api/presets/' + presets[0]['id']))
    return json.loads(request('/api/generate', dict(request_id=str(uuid.uuid4()), preset=preset['id'],
        revision=preset['revision'], values={'positive': 'A demo prompt', 'seed': 41})))


def test_demo_without_configuration_generates_and_recovers_same_browser(preview):
    runner, request, _ = preview
    page = request('/').decode()
    assert 'id="demo-notice"' in page and 'No ComfyUI connection' in page
    wait(lambda: json.loads(request('/api/state'))['online'])
    assert len(json.loads(request('/api/gallery'))) == 6
    job = submit(request)
    def current():
        return next(j for j in json.loads(request('/api/state'))['jobs'] if j['id'] == job['id'])
    wait(lambda: current()['status'] == 'complete', timeout=12)
    wait(lambda: bool(current()['images']))
    wait(lambda: len(json.loads(request('/api/gallery'))) == 7)
    # The existing client identity and state endpoint restore this job on reopen.
    request('/')
    assert current()['status'] == 'complete'
    assert 'SIMULATED generation only' in runner.text


def test_demo_cancellation_uses_existing_job_endpoint(preview):
    _, request, _ = preview
    wait(lambda: json.loads(request('/api/state'))['online'])
    job = submit(request)
    wait(lambda: next(j for j in json.loads(request('/api/state'))['jobs'] if j['id'] == job['id'])['status'] == 'running')
    request('/api/jobs/' + job['id'] + '/cancel', {'confirm_interrupt': True})
    # Existing service reports an interrupted running generation as failed,
    # with an interruption message (queued cancellation uses "cancelled").
    def interrupted():
        current = next(j for j in json.loads(request('/api/state'))['jobs'] if j['id'] == job['id'])
        return current['status'] == 'failed' and 'interrupt' in current.get('error', '').lower()
    wait(interrupted)
    assert len(json.loads(request('/api/gallery'))) == 6


@pytest.mark.parametrize('args', [
    ['--demo-webui', '--start-server'], ['--demo-webui', '--start-webui'],
    ['--demo-port', '8189'], ['--demo-host', '0.0.0.0'],
    ['--demo-webui', '--demo-port', '0'], ['--demo-webui', '--demo-host', 'not-an-ip'],
])
def test_demo_rejects_conflicting_or_invalid_options(args):
    result = subprocess.run([sys.executable, '-m', 'comfyui_control.cli', *args], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and result.stderr
    assert 'Traceback' not in result.stderr


def test_demo_port_conflict_reports_reason_and_cleans_up(tmp_path):
    import socket
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        result = subprocess.run([sys.executable, '-m', 'comfyui_control.cli', '--demo-webui',
                                 '--demo-port', str(listener.getsockname()[1])],
                                env={**os.environ, 'TMPDIR': str(tmp_path)}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1 and 'address already in use' in result.stderr.lower()
    assert 'Traceback' not in result.stderr
    assert not list(tmp_path.iterdir())
