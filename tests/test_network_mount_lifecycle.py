"""Automount activation and conservative removal; never mutate host mounts."""
from contextlib import nullcontext
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from comfyui_control import network_output as nfs
from comfyui_control.app import MainWindow
from comfyui_control.config import Config
from comfyui_control.network_output_widgets import NetworkOutput


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('cover', [False, True])
def test_mount_stack_uses_parent_relationship_not_line_order(reverse, cover):
    spec = nfs.specification('nas', '/images')
    lines = [f'40 1 0:40 / {spec["where"]} rw - autofs systemd-1 rw',
             f'50 40 0:50 / {spec["where"]} rw - nfs4 nas:/images rw']
    if cover:
        lines.append(f'60 50 0:60 / {spec["where"]} rw - tmpfs foreign rw')
    if reverse:
        lines.reverse()
    with patch.object(Path, 'read_text', return_value='\n'.join(lines)):
        assert nfs.mount_record(spec['where']) == (('tmpfs', 'foreign') if cover else ('nfs4', 'nas:/images'))
        assert nfs.mounted(spec) is not cover


def test_probe_opens_empty_directory_to_activate_mount_before_any_write(tmp_path):
    spec = dict(nfs.specification('nas', '/images'), where=str(tmp_path))
    activated = False
    actual_scandir = os.scandir

    def open_directory(path):
        nonlocal activated
        assert Path(path) == tmp_path
        activated = True
        return actual_scandir(path)

    def mounted(_):
        return activated

    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(nfs.socket, 'create_connection', return_value=nullcontext()), \
         patch.object(nfs, 'mounted', mounted), patch.object(nfs.os, 'scandir', open_directory):
        nfs.probe(spec)
    assert activated and list(tmp_path.iterdir()) == []  # Write probe removed.


@pytest.mark.parametrize('activation_error', [None, PermissionError('Access denied by server')])
def test_failed_activation_never_writes_to_underlying_local_directory(activation_error):
    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(nfs.socket, 'create_connection', return_value=nullcontext()), \
         patch.object(nfs.os, 'scandir', side_effect=activation_error) as opened, \
         patch.object(nfs, 'mounted', return_value=False), \
         patch.object(nfs.tempfile, 'mkstemp') as write:
        with pytest.raises(ValueError, match='Access denied by server' if activation_error else 'no write was attempted'):
            nfs.probe(nfs.specification('nas', '/images'))
        opened.assert_called_once()
        write.assert_not_called()


@pytest.fixture
def managed(tmp_path, monkeypatch):
    directory = tmp_path / 'units'
    directory.mkdir()
    other = tmp_path / 'other-units'
    other.mkdir()
    spec = nfs.specification('nas', '/images')
    for name, contents in nfs.units(spec).items():
        (directory / name).write_text(contents)
        (directory / name).chmod(0o644)
    monkeypatch.setattr(nfs, 'UNIT_DIRECTORY', directory)
    monkeypatch.setattr(nfs, 'OTHER_UNIT_DIRECTORIES', (other,))
    monkeypatch.setattr(nfs.os, 'geteuid', lambda: 0)
    # Simulate root ownership of fixtures, retaining real file type/mode.
    original = Path.stat
    def root_owned(path, **kwargs):
        info = original(path, **kwargs)
        if path.parent == directory or str(path) == '/mnt':
            values = list(info)
            values[4] = 0
            if str(path) == '/mnt':
                values[0] = 0o40755
            return os.stat_result(values)
        return info
    monkeypatch.setattr(Path, 'stat', root_owned)
    return spec, directory, other


def test_removal_only_targets_exact_managed_units_and_preserves_other_files(managed):
    spec, directory, other = managed
    unrelated = directory / 'another.mount'
    unrelated.write_text('Other mount\n')
    fstab = other / 'fstab'
    fstab.write_text('Existing system mounts\n')
    with patch.object(nfs, 'mount_record', side_effect=[('nfs4', spec['source']), None]), \
         patch.object(nfs, '_system_command', return_value='') as commands:
        nfs.remove_mount(spec)
    assert [call.args[0] for call in commands.call_args_list] == [
        ['/usr/bin/systemctl', 'show', '--property=RequiredBy,RequisiteOf,BoundBy,ConsistsOf,PropagatesStopTo',
         spec['unit'] + '.automount', spec['unit'] + '.mount'],
        ['/usr/bin/systemctl', 'disable', '--now', spec['unit'] + '.automount'],
        ['/usr/bin/systemctl', 'stop', spec['unit'] + '.mount'],
        ['/usr/bin/systemctl', 'daemon-reload']]
    assert list(directory.iterdir()) == [unrelated]
    assert unrelated.read_text() == 'Other mount\n' and fstab.read_text() == 'Existing system mounts\n'


@pytest.mark.parametrize('problem', ['edited', 'foreign', 'symlink', 'writable', 'missing', 'override', 'generated'])
def test_removal_refuses_other_peoples_units_before_any_system_command(managed, problem):
    spec, directory, other = managed
    name = spec['unit'] + '.mount'
    path = directory / name
    if problem == 'edited':
        path.write_text(path.read_text().replace('What=nas:/images', 'What=other:/private'))
    elif problem == 'foreign':
        path.write_text('Not managed by this app\n')
    elif problem == 'symlink':
        path.unlink()
        path.symlink_to(other / 'target')
    elif problem == 'writable':
        path.chmod(0o666)
    elif problem == 'missing':
        path.unlink()
    elif problem == 'override':
        (directory / (name + '.d')).mkdir()
    else:
        (other / name).write_text('Generated from an existing fstab entry\n')
    before = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    with patch.object(nfs, '_system_command') as commands:
        with pytest.raises(ValueError):
            nfs.remove_mount(spec)
        commands.assert_not_called()
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('record', [('nfs4', 'other:/images'), ('tmpfs', 'foreign'), ('autofs', 'other')])
def test_foreign_filesystem_is_never_stopped_or_reconfigured(managed, record):
    spec, _, _ = managed
    with patch.object(nfs, 'mount_record', return_value=record), patch.object(nfs, '_system_command') as commands:
        with pytest.raises(ValueError, match='another filesystem'):
            nfs.remove_mount(spec)
        with patch.object(nfs, 'nfs_client_available', return_value=True):
            with pytest.raises(ValueError, match='another filesystem'):
                nfs.install_mount(spec)
        commands.assert_not_called()


def test_unowned_matching_automount_is_not_adopted(managed):
    spec, directory, _ = managed
    for path in directory.iterdir():
        path.unlink()
    with patch.object(nfs, 'mount_record', return_value=('autofs', 'systemd-1')), \
         patch.object(nfs, 'nfs_client_available', return_value=True), patch.object(nfs, '_system_command') as commands:
        with pytest.raises(ValueError, match='not managed by this app'):
            nfs.install_mount(spec)
        commands.assert_not_called()


def test_nested_mount_is_not_stopped_as_dependency_of_our_mount(managed):
    spec, _, _ = managed
    with patch.object(nfs, 'mount_record', return_value=('nfs4', spec['source'])), \
         patch.object(Path, 'read_text', autospec=True, side_effect=lambda path, **_: (
             f'60 50 0:60 / {spec["where"]}/another rw - tmpfs foreign rw'
             if str(path) == '/proc/self/mountinfo' else nfs.units(spec)[path.name])), \
         patch.object(nfs, '_system_command') as commands:
        with pytest.raises(ValueError, match='nested mount'):
            nfs.remove_mount(spec)
        commands.assert_not_called()


@pytest.mark.parametrize('property', ['RequiredBy', 'RequisiteOf', 'BoundBy', 'ConsistsOf', 'PropagatesStopTo'])
def test_systemd_stop_dependencies_cannot_stop_other_mounts_or_services(managed, property):
    spec, directory, _ = managed
    before = {p: p.read_bytes() for p in directory.iterdir()}
    with patch.object(nfs, 'mount_record', return_value=('nfs4', spec['source'])), \
         patch.object(nfs, '_system_command', return_value=f'{property}=other.mount important.service\n') as commands:
        with pytest.raises(ValueError, match='Other system units depend.*important.service.*other.mount'):
            nfs.remove_mount(spec)
        assert len(commands.call_args_list) == 1
        assert commands.call_args.args[0][1] == 'show'  # Read-only preflight only.
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('still_mounted', [False, True])
def test_busy_or_still_mounted_share_keeps_definitions_for_retry(managed, still_mounted):
    spec, directory, _ = managed
    before = {p: p.read_bytes() for p in directory.iterdir()}
    def command(args, *_):
        if 'stop' in args and not still_mounted:
            raise ValueError('Target is busy')
    with patch.object(nfs, 'mount_record', return_value=('nfs4', spec['source'])), \
         patch.object(nfs, '_system_command', side_effect=command):
        with pytest.raises(ValueError, match='still mounted' if still_mounted else 'busy'):
            nfs.remove_mount(spec)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_removal_requires_administrator(monkeypatch):
    monkeypatch.setattr(nfs.os, 'geteuid', lambda: 1000)
    with pytest.raises(ValueError, match='administrator'):
        nfs.remove_mount(nfs.specification('nas', '/images'))


def test_removal_ui_is_blocked_during_generation_and_cancel_preserves_ready_state(app, tmp_path):
    manager = NetworkOutput()
    manager.configure(Config(comfy_dir=str(tmp_path), nfs_enabled=True, nfs_server='nas', nfs_export='/images', nfs_auto_connect=False))
    manager.ready = True
    with patch.object(QMessageBox, 'information') as warning, patch.object(manager, '_start') as start:
        manager.remove(None, in_use=True)
        warning.assert_called_once()
        start.assert_not_called()
    with patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/pkexec'), \
         patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Cancel), patch.object(manager, '_start') as start:
        manager.remove(None)
        start.assert_not_called()
    assert manager.ready and not manager.removing and not manager.setup_open
    manager.stop()


def test_authorized_removal_runs_in_background_then_switches_gallery_to_fallback(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    (tmp_path / 'main.py').touch()
    config = Config(comfy_dir=str(tmp_path), nfs_enabled=True, nfs_server='nas', nfs_export='/images', nfs_auto_connect=False, monitoring_enabled=False)
    window = MainWindow(config)
    QTest.qWait(20)
    manager = window.network_output
    manager.ready = True
    window._network_changed()
    assert window.controller.config.session_network_output
    window.controller.state = 'running'
    window._state_changed('running')
    assert not window.network_remove.isEnabled()
    window.controller.state = 'stopped'
    window._state_changed('stopped')
    original = manager._start
    commands = []
    def start(operation, command, timeout):
        import sys
        commands.append((operation, command, timeout))
        original(operation, [sys.executable, '-c', 'import time;time.sleep(.1);print(\'{"ok":true}\')'], timeout)
    with patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/pkexec'), \
         patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Ok), patch.object(manager, '_start', start):
        window.network_remove.click()
    assert commands[0][0] == 'remove' and commands[0][1][-3:] == ['remove', 'nas', '/images']
    assert not window.start_stop.isEnabled() and not window.config_button.isEnabled()
    for _ in range(200):
        if manager.job is None:
            break
        QTest.qWait(10)
    assert manager.job is None and not manager.ready and not manager.removing
    assert window.start_stop.isEnabled() and window.config_button.isEnabled()
    assert window.controller.config.folder('output') == tmp_path / 'output'
    assert not window.controller.config.session_network_output
    assert window.mobile.output_status['destination'] == 'local_fallback'
    assert 'removed' in manager.message
    window._quit_requested = True
    window.close()
