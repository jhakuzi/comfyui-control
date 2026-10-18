"""NFS fixtures and disposable workers; no administrator changes or NAS mounts."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import patch
import http.cookiejar
import urllib.request

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from comfyui_control.app import MainWindow, SettingsDialog
from comfyui_control.background_process import BackgroundProcess, run_background
from comfyui_control.config import Config
from comfyui_control.controller import Controller
from comfyui_control.launch_script import create_launch_script
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.network_output import specification, units, read_image, install_mount, _system_command, probe
from comfyui_control.network_output_widgets import NetworkOutput, worker_command


def wait(predicate, timeout=5):
    until = time.monotonic() + timeout
    while not predicate() and time.monotonic() < until:
        QTest.qWait(10)
    assert predicate()


def network_config(tmp_path, **kwargs):
    return Config(comfy_dir=str(tmp_path), python=sys.executable, nfs_enabled=True,
                  nfs_server='192.0.2.10', nfs_export='/images', nfs_auto_connect=False, **kwargs)


@pytest.mark.parametrize('server,export', [('nas.example', '/images'), ('192.0.2.10', '/images/'), ('2001:db8::1', '/images')])
def test_mount_names_and_unit_definitions_are_data_only(tmp_path, server, export):
    spec = specification(server, export)
    assert spec['where'].startswith('/mnt/comfyui-nfs-')
    assert len(units(spec)) == 2
    escaped = subprocess.check_output(['systemd-escape', '--path', spec['where']], text=True).strip() if shutil.which('systemd-escape') else spec['unit']
    assert spec['unit'] == escaped
    for name, contents in units(spec).items():
        (tmp_path / name).write_text(contents)
        assert 'ExecStart=' not in contents
    if shutil.which('systemd-analyze'):
        result = subprocess.run(['systemd-analyze', 'verify', *map(str, tmp_path.iterdir())], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('server,export', [('https://nas', '/images'), ('nas;reboot', '/images'), ('-bad', '/images'),
    ('nas', '/images\nOptions=exec'), ('nas', '/images/../etc'), ('nas', '/images%h'), ('nas', '/images with spaces'),
    ('fe80::1%eth0', '/images'), ('fe80::1%x\nWhere=/etc', '/images')])
def test_invalid_mount_inputs_are_rejected(server, export):
    with pytest.raises(ValueError):
        specification(server, export)


def test_setup_is_never_run_without_administrator_authorization(monkeypatch):
    monkeypatch.setattr('comfyui_control.network_output.os.geteuid', lambda: 1000)
    with pytest.raises(ValueError, match='administrator'):
        install_mount(specification('nas', '/images'))


def test_setup_reports_system_command_error_instead_of_hiding_stderr():
    with pytest.raises(ValueError, match='Enabling the NFS automount failed.*permission denied by systemd'):
        _system_command([sys.executable, '-c', 'import sys; print("permission denied by systemd",file=sys.stderr);sys.exit(2)'],
                        'Enabling the NFS automount', 2)


def test_connection_error_identifies_server_and_nfs_port():
    with patch.object(Path, 'is_file', return_value=True), patch('comfyui_control.network_output.socket.create_connection', side_effect=OSError('Connection refused')):
        with pytest.raises(ValueError, match='nas.*TCP port 2049.*Connection refused'):
            probe(specification('nas', '/images'))


def test_mounted_but_unwritable_export_is_distinguished_from_connection_failure():
    from contextlib import nullcontext
    with patch.object(Path, 'is_file', return_value=True), \
         patch('comfyui_control.network_output.os.scandir'), \
         patch('comfyui_control.network_output.socket.create_connection', return_value=nullcontext()), \
         patch('comfyui_control.network_output.mounted', return_value=True), \
         patch('comfyui_control.network_output.tempfile.mkstemp', side_effect=PermissionError('Permission denied')):
        with pytest.raises(ValueError, match='nas:/images is mounted.*UID.*GID.*Permission denied'):
            probe(specification('nas', '/images'))


def test_runtime_output_never_persists_and_disabled_nfs_preserves_old_behavior(tmp_path):
    config = network_config(tmp_path, arguments='--output-directory "/old path" --port 8188', output_dir='/old-browser-folder')
    assert config.folder('output') == tmp_path / 'output'
    assert config.command()[-4:] == ['--port', '8188', '--output-directory', str(tmp_path / 'output')]
    active = replace(config, session_output_dir='/mnt/example', session_network_output=True)
    path = tmp_path / 'config.json'
    active.save(path)
    assert 'session_output' not in path.read_text() and 'session_network' not in path.read_text()
    assert Config.load(path).folder('output') == tmp_path / 'output'
    local = replace(config, nfs_enabled=False)
    assert local.folder('output') == Path('/old-browser-folder')
    assert local.command()[-4:] == ['--port', '8188', '--output-directory', '/old-browser-folder']


def test_script_output_routing_requires_forwarding_and_preserves_source(tmp_path):
    (tmp_path / 'main.py').touch()
    script = tmp_path / 'start.sh'
    config = network_config(tmp_path, mode='script', script=str(script))
    script.write_text('exec python main.py\n')
    with pytest.raises(ValueError, match='does not accept'):
        config.validate()
    script.write_text('exec python main.py --output-directory /wrong "$@"\n')
    with pytest.raises(ValueError, match='hardcodes'):
        config.validate()
    script.write_text('exec python main.py "$@"\n')
    config.validate()
    original = script.read_bytes()
    assert config.command()[-2:] == ['--output-directory', str(tmp_path / 'output')]
    assert script.read_bytes() == original


@pytest.mark.parametrize('script_mode', [False, True])
def test_real_owned_process_writes_to_selected_output_and_fallback(app, tmp_path, script_mode):
    (tmp_path / 'main.py').write_text('import argparse, pathlib\np=argparse.ArgumentParser()\np.add_argument("--output-directory")\na=p.parse_args()\nd=pathlib.Path(a.output_directory)\nd.mkdir(parents=True,exist_ok=True)\n(d/"result.txt").write_text("saved")\n')
    config = network_config(tmp_path)
    if script_mode:
        script = tmp_path / 'start.sh'
        create_launch_script(tmp_path, script, [], sys.executable)
        config = replace(config, mode='script', script=str(script), managed_script=True)
    manager = NetworkOutput()
    manager.configure(config)
    controller = Controller(config)
    controller.output_selector = manager.select
    controller.start()
    wait(lambda: controller.process is None)
    assert (tmp_path / 'output/result.txt').read_text() == 'saved'
    assert not controller.config.session_network_output
    # A ready mount's location is simulated with an ordinary test directory.
    import comfyui_control.network_output_widgets as widgets
    spec = specification(config.nfs_server, config.nfs_export)
    spec['where'] = str(tmp_path / 'network')
    with patch.object(widgets, 'specification', return_value=spec):
        manager.spec = spec
        manager.ready = True
        controller.start()
        wait(lambda: controller.process is None)
    assert (tmp_path / 'network/result.txt').read_text() == 'saved'
    assert controller.config.session_network_output
    controller.shutdown(); manager.stop()


def test_settings_persist_nfs_fields_and_do_not_override_output_preview(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    (tmp_path / 'main.py').touch()
    config = network_config(tmp_path)
    dialog = SettingsDialog(config)
    assert dialog.network_fields.location.text() == specification(config.nfs_server, config.nfs_export)['where']
    assert not dialog.output_dir.isEnabled()
    dialog.network_fields.setChecked(False)
    assert dialog.output_dir.isEnabled()
    dialog.network_fields.setChecked(True)
    dialog._save()
    assert dialog.result_config.nfs_enabled and dialog.result_config.nfs_server == config.nfs_server


def test_timeout_and_failed_probe_use_fallback_without_blocking_qt(app, tmp_path, monkeypatch):
    manager = NetworkOutput()
    config = network_config(tmp_path)
    manager.configure(config)
    notices = []
    manager.notification.connect(notices.append)
    manager._start('probe', [sys.executable, '-c', 'import time; time.sleep(60)'], .08)
    wait(lambda: manager.job is None)
    assert notices and 'timed out' in notices[-1]
    assert manager.select(config).folder('output') == tmp_path / 'output'
    assert not manager.select(config).session_network_output
    manager.retry()  # The real worker finds that no system mount setup exists.
    wait(lambda: manager.job is None)
    assert not manager.ready and 'Set up mount' in manager.message
    manager.stop()


def test_worker_concurrency_is_bounded_and_cancel_does_not_wait_for_io():
    jobs = [BackgroundProcess([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(4)]
    try:
        with pytest.raises(OSError, match='busy'):
            BackgroundProcess([sys.executable, '-c', 'pass'])
    finally:
        started = time.monotonic()
        for job in jobs:
            job.cancel()
        assert time.monotonic() - started < 1
    # Ordinary killed children are reaped without consuming future slots.
    wait(lambda: all(job.process.poll() is not None for job in jobs))
    job = BackgroundProcess([sys.executable, '-c', 'print("ready")'])
    wait(lambda: job.process.poll() is not None)
    assert job.poll().strip() == b'ready'


def test_cancelled_setup_never_starts_a_privileged_command(app, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    manager = NetworkOutput()
    manager.configure(network_config(tmp_path))
    with patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/pkexec'), patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Cancel), patch.object(manager, '_start') as start:
        manager.setup(None)
        start.assert_not_called()
        assert manager.message == 'Mount setup cancelled.'
    manager.stop()


def test_settings_mount_button_saves_and_opens_setup_for_the_new_configuration(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    (tmp_path / 'main.py').touch()
    window = MainWindow(Config(comfy_dir=str(tmp_path), python=sys.executable, monitoring_enabled=False))
    def save_and_setup(dialog):
        dialog.network_fields.setChecked(True)
        dialog.network_fields.server.setText('nas')
        dialog.network_fields.export.setText('/images')
        assert dialog.network_fields.setup_button.isEnabled()
        dialog.network_fields.setup_button.click()
        assert dialog.setup_mount_requested
        return dialog.result()
    try:
        with patch.object(SettingsDialog, 'exec', save_and_setup), patch.object(window.network_output, 'setup') as setup:
            window._settings()
            QTest.qWait(30)
            setup.assert_called_once_with(window)
        saved = Config.load()
        assert saved.nfs_enabled and saved.nfs_server == 'nas' and saved.nfs_export == '/images'
        assert window.network_output.spec == specification('nas', '/images')
    finally:
        window._closing = True
        window.close()


def test_invalid_settings_cannot_start_mount_setup(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    dialog = SettingsDialog(network_config(tmp_path))
    with patch('comfyui_control.app.QMessageBox.warning') as warning:
        dialog.network_fields.setup_button.click()
    assert dialog.result_config is None and not dialog.setup_mount_requested
    assert 'main.py' in warning.call_args.args[-1]


def test_explicit_mount_setup_replaces_probe_and_suppresses_retries_in_dialog(app, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    manager = NetworkOutput()
    manager.configure(network_config(tmp_path))
    manager._start('probe', [sys.executable, '-c', 'import time;time.sleep(60)'], 12)
    old_job = manager.job
    def authorize(dialog):
        assert manager.setup_open and manager.job is None
        manager.retry()
        assert manager.job is None
        return QMessageBox.StandardButton.Ok
    with patch('comfyui_control.network_output_widgets.nfs_client_available', return_value=True), \
         patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/pkexec'), \
         patch.object(QMessageBox, 'exec', authorize), patch.object(manager, '_start') as start:
        manager.setup(None)
        assert start.call_args.args[0] == 'setup'
    assert not manager.setup_open
    wait(lambda: old_job.process.poll() is not None)
    manager.stop()


def test_successful_retry_does_not_switch_running_server_or_mobile_scope(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    (tmp_path / 'main.py').touch()
    window = MainWindow(network_config(tmp_path, monitoring_enabled=False))
    QTest.qWait(20)
    assert window.network_row.isHidden() is False
    config = window.controller.config
    window.controller.state = 'running'
    window.network_output._start('probe', [sys.executable, '-c', 'print(\'{"ok":true}\')'], 2)
    wait(lambda: window.network_output.job is None)
    assert window.network_output.ready
    assert window.controller.config == config
    assert 'next ComfyUI start' in window.network_status.text()
    assert window.controller.config.folder('output') == tmp_path / 'output'
    window.controller.state = 'stopped'
    window._network_changed()
    assert window.controller.config.session_network_output
    assert str(window.controller.config.folder('output')).startswith('/mnt/comfyui-nfs-')
    window._closing = True
    window.close()


def test_isolated_file_worker_keeps_metadata_and_rejects_symlinks(tmp_path):
    async def scenario():
        image = QImage(16, 24, QImage.Format.Format_RGB32)
        image.fill(0)
        image.setText('prompt', json.dumps({'text': {'class_type': 'Text', 'inputs': {'text': 'saved prompt'}}}))
        assert image.save(str(tmp_path / 'one.png'))
        descriptor = {'filename': 'one.png', 'subfolder': '', 'type': 'output', 'id': 'one'}
        found = json.loads(await run_background(worker_command('scan', tmp_path), [descriptor]))
        assert found['found'][0][2] == 'one.png' and 'one' in found['valid']
        contents = await run_background(worker_command('read', tmp_path), descriptor)
        from comfyui_control.mobile.image_metadata import png_details
        details = png_details(contents, {})
        assert details['image'] == {'width': 16, 'height': 24}
        assert details['positive'][0]['value'] == 'saved prompt'
        (tmp_path / 'link.png').symlink_to(tmp_path / 'one.png')
        for name in ('link.png', '../one.png'):
            with pytest.raises(FileNotFoundError):
                await run_background(worker_command('read', tmp_path), {**descriptor, 'filename': name})
    asyncio.run(scenario())


def test_network_gallery_http_privacy_deletion_and_unavailable_share(tmp_path):
    async def scenario():
        output = tmp_path / 'network'
        output.mkdir()
        image = QImage(12, 20, QImage.Format.Format_RGB32)
        image.fill(0)
        image.setText('prompt', 'private image metadata')
        assert image.save(str(output / 'one.png'))
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=True)
        service.jobs['job'] = {'id': 'job', 'owner': 'someone-else', 'created': 1}
        ref = service.image_ref({'filename': 'one.png'}, 'job')
        service.jobs['job']['images'] = [dict(ref)]
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            gallery = await (await client.get('/api/gallery')).json()
            assert len(gallery) == 1 and gallery[0]['job'] is None
            response = await client.get(gallery[0]['url'])
            assert response.status == 200
            assert b'private image metadata' not in await response.read()
            assert (await client.get(gallery[0]['thumbnail'])).status == 200
            assert (await (await client.get('/api/images/' + ref['id'] + '/details')).json())['restricted']
            (output / 'one.png').unlink()
            assert (await client.get(gallery[0]['url'])).status == 404
            assert await (await client.get('/api/gallery?refresh=1')).json() == []
            # An unmounted production path is an error, never an empty local
            # directory scan that would discard the gallery on a transient failure.
            service.change_output(specification('nas', '/images')['where'], network_output=True)
            response = await client.get('/api/gallery?refresh=1')
            assert response.status == 503
        finally:
            await client.close()
    asyncio.run(scenario())


def test_mount_error_warns_without_claiming_a_running_network_save_moved(tmp_path):
    config = network_config(tmp_path)
    manager = NetworkOutput()
    manager.configure(config)
    manager._failed(OSError('NAS refused write access'))
    fallback = manager.status(manager.select(config))
    assert fallback['destination'] == 'local_fallback'
    assert fallback['path'] == str(tmp_path / 'output')
    assert fallback['error'] == 'NAS refused write access'
    assert 'Upload images saved here' in fallback['message']
    running = replace(config, session_network_output=True, session_output_dir=manager.spec['where'])
    status = manager.status(running)
    assert status['destination'] == 'network' and status['level'] == 'error'
    assert 'running server still targets NFS' in status['message']
    assert 'Restart ComfyUI' in status['message']
    assert manager.status(replace(config, nfs_enabled=False)) == {}
    manager.stop()


def test_desktop_and_live_mobile_recover_fallback_warning_and_gallery(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    (tmp_path / 'main.py').touch()
    output = tmp_path / 'output'
    output.mkdir()
    image = QImage(16, 24, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(output / 'local-result.png'))
    # Real embedded HTTP lifecycle, no mount or privileged operations.
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    settings = MobileSettings(enabled=True, bind='127.0.0.1', port=port)
    settings.save()
    window = MainWindow(network_config(tmp_path, monitoring_enabled=False))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def get(path):
        return opener.open(f'http://127.0.0.1:{port}' + path, timeout=3)
    def state():
        with get('/api/state') as response:
            return json.load(response)
    try:
        wait(lambda: window.mobile.status == 'Listening')
        window.network_output._failed(OSError('NAS is offline'))
        assert 'NAS is offline' in window.network_status.text()
        assert 'Upload images saved here' in window.network_status.text()
        assert 'Upload images saved here' in window.log.toPlainText()
        with get('/api/session'):
            pass
        warning = state()['output_status']
        assert warning['error'] == 'NAS is offline'
        assert warning['destination'] == 'local_fallback'
        with get('/api/gallery') as response:
            gallery = json.load(response)
        assert [item['filename'] for item in gallery] == ['local-result.png']
        with get(gallery[0]['url']) as response:
            assert response.read().startswith(b'\x89PNG')
        # Both a reconnected SSE snapshot and live partial updates carry the
        # warning; no new polling loop or browser-local warning state is needed.
        with get('/api/events') as response:
            snapshot = json.loads(response.readline().removeprefix(b'data: '))
            assert snapshot['output_status'] == warning
            window.network_output._failed(OSError('NAS still offline'))
            for _ in range(6):
                line = response.readline()
                if not line.startswith(b'data: '):
                    continue
                update = json.loads(line.removeprefix(b'data: '))
                if update['output_status'].get('error') == 'NAS still offline':
                    assert update['partial']
                    break
            else:
                pytest.fail('Fallback warning did not reach the live stream')
        # Restarting the mobile listener retains the desktop's active warning.
        window.mobile.stop()
        wait(lambda: not window.mobile.running)
        window.mobile.configure(settings, window.controller.config)
        wait(lambda: window.mobile.status == 'Listening')
        assert state()['output_status']['error'] == 'NAS still offline'
        window._set_config(replace(window.controller.config, nfs_enabled=False))
        assert state()['output_status'] == {}
    finally:
        window._closing = True
        window.close()
        wait(lambda: not window.mobile.running)
