"""Package-install offers use simulated commands; never alter the host packages."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox

from comfyui_control.config import Config
from comfyui_control.network_output import nfs_client_available
from comfyui_control.network_output_widgets import NetworkOutput, nfs_install_command, nfs_install_script


@pytest.mark.parametrize('release,package,command', [
    ({'ID': 'fedora'}, 'nfs-utils', ['/usr/bin/dnf', 'install', 'nfs-utils']),
    ({'ID': 'rocky', 'ID_LIKE': 'rhel centos fedora'}, 'nfs-utils', ['/usr/bin/dnf', 'install', 'nfs-utils']),
    ({'ID': 'ubuntu', 'ID_LIKE': 'debian'}, 'nfs-common', ['/usr/bin/apt-get', 'install', 'nfs-common']),
    ({'ID': 'debian'}, 'nfs-common', ['/usr/bin/apt-get', 'install', 'nfs-common']),
    ({'ID': 'arch'}, 'nfs-utils', ['/usr/bin/pacman', '-S', '--needed', 'nfs-utils']),
    ({'ID': 'manjaro', 'ID_LIKE': 'arch'}, 'nfs-utils', ['/usr/bin/pacman', '-S', '--needed', 'nfs-utils']),
])
def test_installer_uses_only_the_distro_nfs_package(release, package, command):
    with patch('comfyui_control.network_output_widgets.platform.freedesktop_os_release', return_value=release), \
         patch.object(Path, 'exists', return_value=False), patch.object(Path, 'is_file', return_value=True), \
         patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/sudo'):
        assert nfs_install_command() == (package, ['/usr/bin/sudo', *command])


def test_unsupported_and_image_based_systems_require_manual_setup():
    with patch.object(Path, 'exists', return_value=True):
        with pytest.raises(ValueError, match='layering'):
            nfs_install_command()
    with patch.object(Path, 'exists', return_value=False), \
         patch('comfyui_control.network_output_widgets.platform.freedesktop_os_release', return_value={'ID': 'unknown'}):
        with pytest.raises(ValueError, match='manually'):
            nfs_install_command()


def test_nfs_helper_is_detected_outside_desktop_path():
    with patch('comfyui_control.network_output.shutil.which', return_value=None), \
         patch.object(Path, 'is_file', lambda path: str(path) == '/usr/sbin/mount.nfs'):
        assert nfs_client_available()
    with patch('comfyui_control.network_output.shutil.which', return_value=None), patch.object(Path, 'is_file', return_value=False):
        assert not nfs_client_available()


@pytest.fixture
def manager(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    instance = NetworkOutput()
    instance.configure(Config(comfy_dir=str(tmp_path), nfs_enabled=True, nfs_server='nas', nfs_export='/images', nfs_auto_connect=False))
    yield instance
    instance.stop()


def test_declining_install_never_opens_terminal_or_privileged_setup(manager):
    with patch('comfyui_control.network_output_widgets.nfs_client_available', return_value=False), \
         patch('comfyui_control.network_output_widgets.nfs_install_command', return_value=('nfs-utils', ['sudo', '/usr/bin/dnf', 'install', 'nfs-utils'])), \
         patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Cancel), \
         patch('comfyui_control.network_output_widgets.QProcess.startDetached') as terminal, patch.object(manager, '_start') as start:
        manager.setup(None)
        terminal.assert_not_called()
        start.assert_not_called()
    assert manager.select(manager.config).folder('output') == manager.config.directory / 'output'


def test_accepting_install_opens_private_script_and_rechecks_on_next_setup(manager):
    def accept(box):
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        assert box.button(QMessageBox.StandardButton.Yes).text() == 'Install nfs-utils'
        assert 'Set up mount again' in box.informativeText()
        return QMessageBox.StandardButton.Yes
    with patch('comfyui_control.network_output_widgets.nfs_client_available', return_value=False), \
         patch('comfyui_control.network_output_widgets.nfs_install_command', return_value=('nfs-utils', ['sudo', '/usr/bin/dnf', 'install', 'nfs-utils'])), \
         patch.object(QMessageBox, 'exec', accept), \
         patch('comfyui_control.network_output_widgets.terminal_command', side_effect=lambda script: ['/terminal', '/bin/bash', str(script)]), \
         patch('comfyui_control.network_output_widgets.QProcess.startDetached', return_value=(True, 123)) as terminal, \
         patch.object(manager, '_start') as start:
        manager.setup(None)
        script = Path(terminal.call_args.args[1][-1])
        assert script.stat().st_mode & 0o777 == 0o600
        assert 'sudo /usr/bin/dnf install nfs-utils' in script.read_text()
        assert manager.error == ''
        assert 'opened in terminal' in manager.message
        assert not manager.ready
        start.assert_not_called()
    # An installed helper goes directly to the existing authorized mount setup.
    with patch('comfyui_control.network_output_widgets.nfs_client_available', return_value=True), \
         patch('comfyui_control.network_output_widgets.shutil.which', return_value='/usr/bin/pkexec'), \
         patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Ok), \
         patch.object(manager, '_offer_client_install') as offer, patch.object(manager, '_start') as start:
        manager.setup(None)
        offer.assert_not_called()
        assert start.call_args.args[0] == 'setup'
    script.unlink()


@pytest.mark.parametrize('failure', ['missing terminal', 'terminal failed to open'])
def test_terminal_failure_explains_manual_command_and_keeps_fallback(manager, failure):
    with patch('comfyui_control.network_output_widgets.nfs_client_available', return_value=False), \
         patch('comfyui_control.network_output_widgets.nfs_install_command', return_value=('nfs-utils', ['sudo', 'dnf', 'install', 'nfs-utils'])), \
         patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
         patch('comfyui_control.network_output_widgets.terminal_command', side_effect=ValueError('No terminal') if failure == 'missing terminal' else None, return_value=['terminal']), \
         patch('comfyui_control.network_output_widgets.QProcess.startDetached', return_value=(False, 0)), \
         patch.object(QMessageBox, 'warning') as warning:
        manager.setup(None)
        assert 'sudo dnf install nfs-utils' in warning.call_args.args[-1]
    assert not manager.ready
    assert not list(Path(manager.config.comfy_dir).rglob('nfs-client-*.sh'))


@pytest.mark.parametrize('exit_code', [0, 7])
def test_install_script_reports_success_or_failure_without_touching_packages(tmp_path, exit_code):
    executable = tmp_path / 'simulated package manager'
    executable.write_text(f'import sys; sys.exit({exit_code})')
    script = tmp_path / 'install.sh'
    script.write_text(nfs_install_script([sys.executable, str(executable)]))
    result = subprocess.run(['/bin/bash', str(script)], input='\n', capture_output=True, text=True)
    assert result.returncode == exit_code
    assert ('Set up mount again' if exit_code == 0 else 'failed or was cancelled') in result.stdout
    assert not script.exists()
