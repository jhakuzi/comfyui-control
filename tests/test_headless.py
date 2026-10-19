"""Real foreground processes and HTTP listeners, with no display server."""
from dataclasses import replace
import http.cookiejar
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from comfyui_control.config import Config, config_path
from comfyui_control.mobile.settings import MobileSettings, data_dir


def wait(predicate, timeout=7):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.02)
    assert predicate(), 'Foreground operation did not complete'


def unused_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def alive(pid):
    path = Path(f'/proc/{pid}/stat')
    return path.exists() and path.read_text().split()[2] != 'Z'


class Running:
    def __init__(self, command, env):
        self.output = []
        self.process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, start_new_session=True)
        def collect():
            self.output.extend(self.process.stdout)
        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()

    @property
    def text(self):
        return ''.join(self.output)

    def stop(self, sig=signal.SIGINT):
        if self.process.poll() is None:
            self.process.send_signal(sig)
        code = self.process.wait(timeout=12)
        self.reader.join(2)
        return code


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    folder = tmp_path / 'ComfyUI'
    folder.mkdir()
    (folder / 'main.py').write_text(
        'import argparse, json, os, pathlib, subprocess, sys, time\n'
        'p=argparse.ArgumentParser();p.add_argument("--output-directory",default="output")\n'
        'args,other=p.parse_known_args()\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"])\n'
        'pathlib.Path("processes.json").write_text(json.dumps([os.getpid(),child.pid]))\n'
        'output=pathlib.Path(args.output_directory);output.mkdir(parents=True,exist_ok=True)\n'
        '(output/"destination.txt").write_text(str(output.absolute()))\n'
        'print("server-ready",flush=True)\n'
        'while True:time.sleep(.1)\n')
    config = Config(comfy_dir=str(folder), python=sys.executable, monitoring_enabled=False)
    config.save()
    settings = MobileSettings(enabled=False, bind='127.0.0.1', port=unused_port(), require_auth=False,
                              comfy_url='http://127.0.0.1:9')
    settings.save()
    runners = []
    env = {**os.environ, 'QT_QPA_PLATFORM': 'not-a-real-platform'}
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
        env.pop(name, None)

    def launch(*flags, bootstrap=None):
        command = [sys.executable, '-m', 'comfyui_control.cli', *flags]
        if bootstrap:
            command = [sys.executable, '-c', bootstrap + '\nfrom comfyui_control.cli import main\nraise SystemExit(main())', *flags]
        runner = Running(command, env)
        runners.append(runner)
        return runner

    yield folder, config, settings, launch
    for runner in runners:
        if runner.process.poll() is None:
            runner.stop(signal.SIGTERM)
    path = folder / 'processes.json'
    if path.exists():
        for pid in json.loads(path.read_text()):
            if alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize('script', [False, True])
def test_both_components_without_display_and_ctrl_c_stops_owned_children(installation, script):
    folder, config, settings, launch = installation
    if script:
        path = folder / 'start.sh'
        path.write_text('exec ' + shlex.quote(sys.executable) + ' main.py "$@"\n')
        replace(config, mode='script', script=str(path)).save()
    output = folder / 'output'
    output.mkdir()
    png = Path(__file__).parents[1] / 'comfyui_control/assets/comfyui-control.png'
    (output / 'example.png').write_bytes(png.read_bytes())
    original = {path: path.read_bytes() for path in (config_path(), data_dir() / 'settings.json')}
    runner = launch('--start-server', '--start-webui')
    wait(lambda: 'server-ready' in runner.text and 'Mobile WebUI: Listening' in runner.text)
    pids = json.loads((folder / 'processes.json').read_text())
    assert all(alive(pid) for pid in pids)
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f'http://127.0.0.1:{settings.port}'
    with client.open(base + '/api/session', timeout=3) as response:
        assert json.load(response)['authenticated']
    with client.open(base + '/api/gallery?refresh=1', timeout=4) as response:
        gallery = json.load(response)
    image = next(item for item in gallery if item['filename'] == 'example.png')
    with client.open(base + image['url'], timeout=3) as response:
        assert response.read() == png.read_bytes()
    with client.open(base + image['thumbnail'], timeout=3) as response:
        assert response.headers['Content-Type'].startswith('image/') and response.read()
    assert runner.stop() == 0, runner.text
    wait(lambda: all(not alive(pid) for pid in pids))
    assert 'Process and its children successfully stopped.' in runner.text
    assert 'ComfyUI Control stopped.' in runner.text
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', settings.port)) != 0
    assert all(path.read_bytes() == contents for path, contents in original.items())
    assert not (config_path().parent / 'control.lock').exists()


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGHUP])
def test_termination_and_ssh_hangup_use_the_same_cleanup(installation, sig):
    folder, _, _, launch = installation
    runner = launch('--start-server')
    wait(lambda: 'server-ready' in runner.text)
    pids = json.loads((folder / 'processes.json').read_text())
    assert runner.stop(sig) == 0, runner.text
    wait(lambda: all(not alive(pid) for pid in pids))


def test_webui_only_does_not_start_or_stop_an_external_server(installation):
    folder, config, settings, launch = installation
    replace(config, python='/not/an/interpreter').save()
    runner = launch('--start-webui')
    wait(lambda: 'Mobile WebUI: Listening' in runner.text)
    assert not (folder / 'processes.json').exists()
    assert '127.0.0.1:' + str(settings.port) in runner.text
    assert runner.stop() == 0
    assert 'Stopping process and its children' not in runner.text


def test_server_only_ignores_mobile_enable_preference_and_bad_mobile_settings(installation):
    folder, _, settings, launch = installation
    replace(settings, enabled=True).save()
    (data_dir() / 'settings.json').write_text('invalid mobile settings')
    runner = launch('--start-server')
    wait(lambda: 'server-ready' in runner.text)
    assert runner.process.poll() is None
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', settings.port)) != 0
    assert runner.stop() == 0


def test_conflicting_instance_uses_the_desktop_lock_and_preserves_the_first(installation):
    folder, _, _, launch = installation
    first = launch('--start-server')
    wait(lambda: 'server-ready' in first.text)
    pids = json.loads((folder / 'processes.json').read_text())
    second = launch('--start-server', '--start-webui')
    assert second.process.wait(timeout=5) == 1
    second.reader.join(1)
    assert 'already running' in second.text
    assert first.process.poll() is None and all(alive(pid) for pid in pids)
    assert first.stop() == 0


@pytest.mark.parametrize('problem', ['missing', 'corrupt', 'password'])
def test_configuration_errors_are_noninteractive_and_do_not_spawn_server(installation, problem):
    folder, _, _, launch = installation
    if problem == 'missing':
        config_path().unlink()
    elif problem == 'corrupt':
        config_path().write_text('{bad configuration')
    else:
        path = data_dir() / 'settings.json'
        data = json.loads(path.read_text())
        data.update(require_auth=True, password='')
        path.write_text(json.dumps(data))
    runner = launch('--start-server', '--start-webui')
    assert runner.process.wait(timeout=5) == 1
    runner.reader.join(1)
    assert 'Could not start ComfyUI Control' in runner.text
    assert not (folder / 'processes.json').exists()


def test_port_conflict_reports_failure_and_cleans_up_any_started_server(installation):
    folder, _, settings, launch = installation
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', settings.port))
        listener.listen()
        runner = launch('--start-server', '--start-webui')
        assert runner.process.wait(timeout=7) == 1
    runner.reader.join(1)
    assert 'Could not start Mobile WebUI' in runner.text
    path = folder / 'processes.json'
    if path.exists():
        wait(lambda: all(not alive(pid) for pid in json.loads(path.read_text())))


@pytest.mark.parametrize('ready', [False, True])
def test_start_waits_for_nfs_probe_then_uses_selected_output(installation, ready):
    folder, config, settings, launch = installation
    replace(config, nfs_enabled=True, nfs_server='nas', nfs_export='/images').save()
    network = folder / 'network'
    network.mkdir()
    bootstrap = f'''
import sys
import comfyui_control.network_output_widgets as widgets
original = widgets.specification
def spec(server, export):
    return dict(original(server,export),where={str(network)!r})
widgets.specification = spec
def worker(operation,*args):
    return [sys.executable,'-c', 'import time,sys;time.sleep(.25);print(' + repr('{{"ok":true}}' if {ready!r} else '{{"error":"NAS offline"}}') + ');sys.exit(' + str(0 if {ready!r} else 1) + ')']
widgets.worker_command = worker
'''
    runner = launch('--start-server', '--start-webui', bootstrap=bootstrap)
    wait(lambda: 'server-ready' in runner.text and 'Mobile WebUI: Listening' in runner.text)
    destination = network if ready else folder / 'output'
    assert (destination / 'destination.txt').read_text() == str(destination)
    assert not ((folder / 'output') if ready else network).joinpath('destination.txt').exists()
    if not ready:
        assert 'Upload images saved here' in runner.text and 'NAS offline' in runner.text
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f'http://127.0.0.1:{settings.port}'
    with client.open(base + '/api/session', timeout=3):
        pass
    with client.open(base + '/api/state', timeout=3) as response:
        state = json.load(response)
    assert state['output_status']['path'] == str(destination)
    assert state['output_status']['destination'] == ('network' if ready else 'local_fallback')
    assert runner.stop() == 0


def test_ctrl_c_during_network_startup_does_not_launch_comfyui(installation):
    folder, config, _, launch = installation
    replace(config, nfs_enabled=True, nfs_server='nas', nfs_export='/images').save()
    bootstrap = '''
import sys
import comfyui_control.network_output_widgets as widgets
widgets.worker_command = lambda *args: [sys.executable,'-c','import time;time.sleep(60)']
'''
    runner = launch('--start-server', '--start-webui', bootstrap=bootstrap)
    wait(lambda: 'Checking network output before starting ComfyUI' in runner.text)
    assert runner.stop() == 0
    assert not (folder / 'processes.json').exists()


def test_failed_launch_and_exhausted_recovery_exit_with_failure(installation):
    folder, config, _, launch = installation
    (folder / 'main.py').write_text('raise SystemExit(7)\n')
    replace(config, auto_restart=True, restart_limit=1, restart_backoff=1).save()
    runner = launch('--start-server')
    assert runner.process.wait(timeout=7) == 1
    runner.reader.join(1)
    assert 'Restart attempt 1/1' in runner.text
    assert 'Recovery limit reached' in runner.text
    assert runner.text.count('Server exited (code 7)') == 2


def test_help_and_version_need_no_display_or_configuration(tmp_path):
    for flag in ('--help', '--version'):
        result = subprocess.run([sys.executable, '-m', 'comfyui_control.cli', flag],
                                capture_output=True, text=True, timeout=4,
                                env={**os.environ, 'XDG_CONFIG_HOME': str(tmp_path), 'QT_QPA_PLATFORM': 'not-real'})
        assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'comfyui-control').exists()


def test_mobile_hardware_samples_reuse_the_worker_and_stop_without_demand(app, installation):
    from unittest.mock import Mock
    from PySide6.QtTest import QTest
    from comfyui_control.headless import TerminalSession
    _, config, settings, _ = installation
    session = TerminalSession(config, settings, start_server=False, start_webui=False)
    metrics = dict(gpus=[dict(utilization=23, vram_used=1024)])
    session.reader = Mock()
    session.reader.sample.return_value = metrics
    session.mobile.publish_hardware = Mock()
    assert not session.hardware_timer.isActive()
    session._hardware_demand(True)
    deadline = time.monotonic() + 3
    while session.sample is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    session.mobile.publish_hardware.assert_called_once_with(metrics)
    assert session.reader.sample.call_count == 1
    session._hardware_demand(False)
    QTest.qWait(80)
    assert session.reader.sample.call_count == 1 and not session.hardware_timer.isActive()
    session.shutdown()
    session.deleteLater()
