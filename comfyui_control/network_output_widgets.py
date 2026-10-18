"""Desktop NFS settings and non-blocking, user-authorized mount operations."""
from dataclasses import replace
import json
from pathlib import Path
import platform
import shlex
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .background_process import BackgroundProcess
from .config import config_path
from .network_output import nfs_client_available, specification, units
from .setup import terminal_command

WORKER = str(Path(__file__).with_name('network_output.py'))


def worker_command(operation, *args):
    return [sys.executable, '-I', WORKER, operation, *map(str, args)]


def nfs_install_command():
    """Choose only the distro's NFS client; never upgrade the whole system."""
    if Path('/run/ostree-booted').exists():
        raise ValueError('On an image-based Fedora system, install nfs-utils using your system’s package layering tools, reboot if required, then retry Set up mount.')
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        raise ValueError('Could not detect this distribution. Install its NFS client, then retry Set up mount.') from None
    families = {release.get('ID', ''), *release.get('ID_LIKE', '').split()}
    if families & {'fedora', 'rhel', 'centos'}:
        package, args = 'nfs-utils', ['/usr/bin/dnf', 'install', 'nfs-utils']
    elif families & {'debian', 'ubuntu'}:
        package, args = 'nfs-common', ['/usr/bin/apt-get', 'install', 'nfs-common']
    elif families & {'arch'}:
        package, args = 'nfs-utils', ['/usr/bin/pacman', '-S', '--needed', 'nfs-utils']
    else:
        raise ValueError('Install this distribution’s NFS client manually, then retry Set up mount. Fedora/Arch: nfs-utils; Debian/Ubuntu: nfs-common.')
    if not Path(args[0]).is_file() or not shutil.which('sudo'):
        raise ValueError('Run this command as administrator, then retry Set up mount: ' + shlex.join(args))
    return package, [shutil.which('sudo'), *args]


def nfs_install_script(command):
    return ('#!/usr/bin/env bash\n'
            'trap \'rm -- "$0"\' EXIT\n'
            + shlex.join(command) + '\nresult=$?\n'
            'if [ "$result" -eq 0 ]; then\n'
            '  echo "Installation finished. Return to ComfyUI Control and click Set up mount again."\n'
            'else\n'
            '  echo "Installation failed or was cancelled. Local fallback remains available; check the output above and retry."\n'
            'fi\n'
            'read -r -p "Press Enter to close this terminal. " _\n'
            'exit "$result"\n')


class NetworkFields(QGroupBox):
    setup_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__('Network output (NFS)', parent)
        self.setCheckable(True)
        self.setChecked(config.nfs_enabled)
        outer = QVBoxLayout(self)
        self.contents = QWidget()
        outer.addWidget(self.contents)
        form = QFormLayout(self.contents)
        self.server = QLineEdit(config.nfs_server)
        self.server.setPlaceholderText('NAS IP address or hostname')
        self.export = QLineEdit(config.nfs_export)
        self.export.setPlaceholderText('/export/comfy-output')
        self.location = QLineEdit()
        self.location.setReadOnly(True)
        self.automatic = QCheckBox('Connect when ComfyUI Control starts')
        self.automatic.setChecked(config.nfs_auto_connect)
        form.addRow('Server', self.server)
        form.addRow('Exported folder', self.export)
        form.addRow('Local mount', self.location)
        form.addRow(self.automatic)
        self.setup_button = QPushButton('Save and set up mount')
        self.setup_button.clicked.connect(self.setup_requested.emit)
        form.addRow(self.setup_button)
        setup_hint = QLabel('Saves settings, closes this window and opens the one-time administrator setup.')
        setup_hint.setWordWrap(True)
        form.addRow(setup_hint)
        note = QLabel('Fallback: this installation’s ComfyUI/output. Simple launch scripts are updated with a backup when saving. Folder changes apply on the next ComfyUI start.')
        note.setWordWrap(True)
        form.addRow(note)
        self.server.textChanged.connect(self._preview)
        self.export.textChanged.connect(self._preview)
        self._preview()
        self.contents.setVisible(self.isChecked())
        self.toggled.connect(self.contents.setVisible)

    def _preview(self):
        try:
            self.location.setText(specification(self.server.text(), self.export.text())['where'])
        except ValueError:
            self.location.clear()
        self.setup_button.setEnabled(bool(self.location.text()))

    def values(self):
        return dict(nfs_enabled=self.isChecked(), nfs_server=self.server.text().strip(),
                    nfs_export=self.export.text().strip(), nfs_auto_connect=self.automatic.isChecked())


class NetworkOutput(QObject):
    changed = Signal()
    notification = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = None
        self.spec = None
        self.ready = False
        self.message = ''
        self.error = ''
        self.job = None
        self.operation = None
        self.stopped = True
        self.setup_open = False
        self.removing = False
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)

    def configure(self, config):
        identity = (config.nfs_enabled, config.nfs_server, config.nfs_export, config.nfs_auto_connect)
        previous = None if not self.config else (self.config.nfs_enabled, self.config.nfs_server, self.config.nfs_export, self.config.nfs_auto_connect)
        self.config = replace(config)
        if identity == previous:
            return
        self.stop()
        self.stopped = False
        self.ready = False
        self.error = ''
        self.spec = None
        if config.nfs_enabled:
            try:
                self.spec = specification(config.nfs_server, config.nfs_export)
                self.message = 'Not connected — using local fallback'
                if config.nfs_auto_connect:
                    QTimer.singleShot(0, self.retry)
            except ValueError as exc:
                self.message = str(exc)
                self.error = str(exc)
        else:
            self.message = ''
        self.changed.emit()

    def select(self, config):
        use_network = bool(config.nfs_enabled and self.ready and self.spec and
                           self.spec == specification(config.nfs_server, config.nfs_export))
        path = self.spec['where'] if use_network else str(config.directory / 'output')
        return replace(config, session_output_dir=path if config.nfs_enabled else '',
                       session_network_output=use_network)

    def status(self, config):
        """One output warning shared by desktop and mobile, without changing jobs."""
        if not config.nfs_enabled:
            return {}
        path = str(config.folder('output'))
        if not config.session_network_output:
            title = 'Local fallback — manual upload required'
            message = (f'Using the local fallback folder: {path}. '
                       'Upload images saved here to your network storage manually.')
            if self.ready:
                message += ' Network output is ready and applies on next ComfyUI start; restart ComfyUI to use it.'
            level = 'warning'
        elif not self.ready:
            title = 'Network output unavailable'
            message = ('The running server still targets NFS. Restart ComfyUI to use the local '
                       'fallback folder. An in-progress save cannot be redirected.')
            level = 'error'
        else:
            title = 'Network output ready'
            message = 'Output: ' + path
            level = 'info'
        return dict(destination='network' if config.session_network_output else 'local_fallback',
                    path=path, level=level, title=title, message=message,
                    connection=self.message, error=self.error)

    def retry(self):
        if self.stopped or not self.spec or self.job or self.setup_open or self.removing:
            return
        self._start('probe', worker_command('probe', self.spec['server'], self.spec['export']), 12)

    def setup(self, parent):
        if not self.spec or self.stopped or self.setup_open or self.removing or (self.job and self.operation != 'probe'):
            return
        self.setup_open = True
        try:
            # A startup probe must not swallow a user's explicit setup action.
            # Suppress scheduled retries while the authorization dialog is open.
            if self.job:
                self.job.cancel()
                self.job = None
                self.timer.stop()
                self.message = 'Network check stopped for mount setup.'
            self.changed.emit()
            self._setup(parent)
        finally:
            self.setup_open = False
            self.changed.emit()

    def _setup(self, parent):
        if not nfs_client_available():
            self._offer_client_install(parent)
            return
        if not shutil.which('pkexec') or not Path('/usr/bin/python3').is_file():
            self.message = 'Install polkit/pkexec and system Python to authorize mount setup. See the NFS setup guide for a terminal alternative.'
            self.notification.emit(self.message)
            return
        box = QMessageBox(parent)
        box.setWindowTitle('Set up NFS output')
        box.setText(f'Install an on-demand mount for {self.spec["source"]}?')
        box.setInformativeText(f'Administrator authorization is required once. Linux will mount it at {self.spec["where"]}. This does not move images or modify your launch script.')
        box.setDetailedText('\n\n'.join(name + '\n' + text for name, text in units(self.spec).items()))
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Ok:
            self._start('setup', [shutil.which('pkexec'), '/usr/bin/python3', '-I', '-S', WORKER,
                                  'setup', self.spec['server'], self.spec['export']], 120)
        else:
            self.message = 'Mount setup cancelled.'
        box.deleteLater()

    def remove(self, parent, in_use=False):
        if in_use:
            QMessageBox.information(parent, 'Stop ComfyUI first', 'Stop ComfyUI before removing its network output mount.')
            return
        if not self.spec or self.stopped or self.setup_open or self.removing or (self.job and self.operation != 'probe'):
            return
        if not shutil.which('pkexec') or not Path('/usr/bin/python3').is_file():
            self.notification.emit('Mount removal needs polkit/pkexec and system Python. See the NFS setup guide for a terminal alternative.')
            return
        self.setup_open = self.removing = True
        if self.job:
            self.job.cancel()
            self.job = None
            self.timer.stop()
        self.changed.emit()
        box = QMessageBox(parent)
        box.setWindowTitle('Remove NFS output mount')
        box.setText(f'Remove this app’s mount for {self.spec["source"]}?')
        box.setInformativeText('Administrator authorization is required. Close file managers and other programs using this folder first. '
                               'Only this app’s two generated units will be disabled and removed. NAS files, other mounts and /etc/fstab are left unchanged. '
                               'Local fallback remains available. The empty local mount folder is kept.')
        box.setDetailedText('\n\n'.join(name + '\n' + text for name, text in units(self.spec).items()))
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText('Remove mount')
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        try:
            if box.exec() == QMessageBox.StandardButton.Ok:
                self._start('remove', [shutil.which('pkexec'), '/usr/bin/python3', '-I', '-S', WORKER,
                                       'remove', self.spec['server'], self.spec['export']], 120)
            else:
                self.message = 'Mount removal cancelled.'
        finally:
            box.deleteLater()
            self.setup_open = False
            if self.job is None:
                self.removing = False
            self.changed.emit()

    def _offer_client_install(self, parent):
        try:
            package, command = nfs_install_command()
            box = QMessageBox(parent)
            box.setWindowTitle('NFS client required')
            box.setText(f'The NFS client tools are missing. Install {package}?')
            box.setInformativeText('Installation opens in your terminal and requires administrator authorization. '
                                   'When it finishes, click Set up mount again in the main window. Local fallback remains available.')
            box.setDetailedText(shlex.join(command))
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            box.button(QMessageBox.StandardButton.Yes).setText('Install ' + package)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            accepted = box.exec() == QMessageBox.StandardButton.Yes
            box.deleteLater()
            if not accepted:
                self.message = 'NFS client installation cancelled. Install the NFS tools before setting up this mount.'
                return
            # Match the existing Comfy CLI setup: detached terminal owns the
            # package transaction, so closing the app cannot kill it halfway.
            directory = config_path().parent
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', prefix='nfs-client-', suffix='.sh',
                                             dir=directory, delete=False) as stream:
                script = Path(stream.name)
                stream.write(nfs_install_script(command))
            try:
                terminal = terminal_command(script)
                ok, _ = QProcess.startDetached(terminal[0], terminal[1:])
                if not ok:
                    raise ValueError('Could not open the installation terminal. Run: ' + shlex.join(command))
            except (OSError, ValueError) as exc:
                script.unlink(missing_ok=True)
                raise ValueError(str(exc) + '\nInstall manually: ' + shlex.join(command)) from exc
            self.message = 'NFS client installation opened in terminal. When it finishes, click Set up mount again in the main window.'
            self.error = ''
            self.changed.emit()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(parent, 'Could not install NFS client', str(exc))
            self.notification.emit(str(exc))

    def _start(self, operation, command, timeout):
        self.operation = operation
        self.error = ''
        self.message = {'probe': 'Checking network output…', 'setup': 'Waiting for mount setup / authorization…',
                        'remove': 'Waiting for mount removal / authorization…'}[operation]
        if operation == 'remove':
            self.ready = False
        try:
            self.job = BackgroundProcess(command, timeout=timeout)
            self.timer.start()
        except OSError as exc:
            self._failed(exc)
        self.changed.emit()

    def _poll(self):
        if self.job is None:
            return
        try:
            result = self.job.poll()
            if result is None:
                return
            self.job = None
            self.timer.stop()
            reply = json.loads(result)
            if not isinstance(reply, dict) or reply.get('ok') is not True:
                raise ValueError('The network worker returned an unexpected response.')
            if self.operation == 'setup':
                self.retry()
                return
            if self.operation == 'remove':
                self.removing = self.ready = False
                self.error = ''
                self.message = 'Managed NFS mount removed. Using local fallback. Use Set up mount to reconnect.'
                self.changed.emit()
                self.notification.emit(self.message)
                return
            self.ready = True
            self.error = ''
            self.message = 'Network output ready'
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._failed(exc)

    def _failed(self, error):
        self.job = None
        self.timer.stop()
        self.ready = False
        self.removing = False
        self.error = str(error)
        self.message = f'{"Mount removal" if self.operation == "remove" else "Network mount"} failed: {error}'
        self.changed.emit()
        self.notification.emit(self.message)

    def stop(self):
        self.stopped = True
        self.removing = False
        self.timer.stop()
        if self.job:
            self.job.cancel()
            self.job = None
