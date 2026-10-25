"""Optional native workflow installer; all installation filesystem work is isolated."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout

from .background_process import BackgroundProcess
from .bundled_workflows import RELATIVE_TARGET, WORKFLOWS
from .workflow_webui import WorkflowWebUI

SETUP_NOTICE = ('Open the regular ComfyUI WebUI at least once and load each installed workflow. '
                'Use ComfyUI Manager to install its missing custom nodes, then restart ComfyUI when prompted. '
                'Required models and input images must also be available. Afterwards, return to ComfyUI Control.')


class WorkflowInstallDialog(QDialog):
    def __init__(self, directory, comfy_url, parent=None, *, server_state=lambda: 'stopped', start_server=None):
        super().__init__(parent)
        self.directory, self.comfy_url = Path(directory), comfy_url
        self.review = None
        self.job = None
        holder = self._worker_holder = {}
        self.destroyed.connect(lambda: holder.pop('job').cancel() if holder.get('job') is not None else None)
        self.operation = None
        self.setWindowTitle('Install bundled workflows')
        self.resize(640, 500)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        heading = QLabel('Install bundled workflows')
        heading.setStyleSheet('font-size: 17px; font-weight: 600;')
        layout.addWidget(heading)
        intro = QLabel('Choose the workflows to add to this ComfyUI installation. This copies workflow files only.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel('Destination'))
        self.destination = QLabel(str(self.directory / RELATIVE_TARGET))
        self.destination.setTextFormat(Qt.TextFormat.PlainText)
        self.destination.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)
        self.choices = {}
        for filename, label in WORKFLOWS:
            choice = QCheckBox(label)
            choice.setChecked(True)
            choice.setToolTip(filename)
            choice.toggled.connect(self._controls)
            layout.addWidget(choice)
            self.choices[filename] = choice
        self.replace = QCheckBox('Replace existing workflows (ask before replacing)')
        self.replace.setChecked(False)
        layout.addWidget(self.replace)
        title = QLabel('One-time setup in ComfyUI required')
        title.setStyleSheet('font-weight: 600;')
        layout.addWidget(title)
        notice = QLabel(SETUP_NOTICE)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.status = QLabel('Checking destination…')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setAccessibleName('Workflow installation results')
        self.results.setMaximumHeight(130)
        self.results.hide()
        layout.addWidget(self.results)
        self.open_webui = QPushButton('Start / open ComfyUI WebUI')
        self.open_webui.setToolTip('Checks ComfyUI, offers to start it if stopped, and waits for readiness before opening. ' + comfy_url)
        self.open_webui.clicked.connect(self._open_webui)
        self.open_webui.hide()
        layout.addWidget(self.open_webui)
        self.webui = WorkflowWebUI(comfy_url, state=server_state, start=start_server,
            confirm=self._confirm_start, open_url=lambda url: QDesktopServices.openUrl(url), parent=self)
        self.webui.status.connect(self.status.setText)
        self.webui.busy_changed.connect(self._webui_busy)
        layout.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel.clicked.connect(self.reject)
        self.refresh = self.buttons.addButton('Refresh', QDialogButtonBox.ButtonRole.ActionRole)
        self.refresh.clicked.connect(self._inspect)
        self.copy = self.buttons.addButton('Install selected', QDialogButtonBox.ButtonRole.ActionRole)
        self.copy.clicked.connect(self._install)
        layout.addWidget(self.buttons)
        self.poll = QTimer(self)
        self.poll.setInterval(50)
        self.poll.timeout.connect(self._poll)
        self.finished.connect(self._cleanup)
        self._inspect()

    def _controls(self):
        if not hasattr(self, 'copy'): return
        busy = self.job is not None or self.webui.busy
        self.open_webui.setEnabled(not busy)
        self.copy.setEnabled(not busy and self.review is not None and any(c.isChecked() for c in self.choices.values()))
        self.refresh.setEnabled(not busy)
        self.cancel.setEnabled(self.job is None or self.operation == 'inspect')
        self.replace.setEnabled(not busy)
        for choice in self.choices.values(): choice.setEnabled(not busy)

    def _request(self, operation, request):
        if self.job is not None: return
        self.operation = operation
        try:
            worker = Path(__file__).with_name('bundled_workflows.py')
            self.job = BackgroundProcess([sys.executable, '-I', str(worker), operation, str(self.directory)],
                                         request, timeout=10, limit=128 * 1024)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
        else:
            self._worker_holder['job'] = self.job
            self.status.setText('Checking destination…' if operation == 'inspect' else 'Installing selected workflows…')
            self.poll.start()
        self._controls()

    def _inspect(self):
        self.review = None
        self._request('inspect', {})

    def _poll(self):
        if self.job is None: return
        try:
            raw = self.job.poll()
            if raw is None: return
            data = json.loads(raw)
            valid = isinstance(data, dict)
            if valid and self.operation == 'inspect':
                valid = (isinstance(data.get('target'), str) and isinstance(data.get('root'), str)
                    and isinstance(data.get('root_identity'), list) and isinstance(data.get('files'), dict)
                    and all(isinstance(data['files'].get(name), dict) and data['files'][name].get('state')
                            in {'missing', 'present', 'same', 'error'} for name, _ in WORKFLOWS))
            elif valid:
                valid = (isinstance(data.get('results'), list) and all(isinstance(e, dict)
                    and e.get('name') in self.choices and e.get('status') in {'installed', 'skipped', 'error'}
                    and isinstance(e.get('message'), str) for e in data['results']))
            if not valid: raise ValueError('Invalid installer response. Refresh before retrying.')
        except (OSError, ValueError) as exc:
            self.poll.stop(); self.job = None; self._worker_holder.pop('job', None)
            self.review = None
            self.status.setText(str(exc) + ' Some files may have been copied; refresh before retrying.' if self.operation == 'install' else str(exc))
        else:
            self.poll.stop(); self.job = None; self._worker_holder.pop('job', None)
            if self.operation == 'inspect':
                self.review = data
                self.destination.setText(data['target'])
                for name, label in WORKFLOWS:
                    state = data['files'][name]['state']
                    self.choices[name].setText(label + {'missing': '', 'same': ' — up to date', 'present': ' — already exists', 'error': ' — check destination'}[state])
                self.status.setText('Existing files are skipped unless you choose replacement and confirm it.')
            else:
                entries = data['results']
                installed = sum(e['status'] == 'installed' for e in entries)
                skipped = sum(e['status'] == 'skipped' for e in entries)
                errors = sum(e['status'] == 'error' for e in entries)
                self.status.setText(f'{installed} installed · {skipped} skipped · {errors} failed. Open regular ComfyUI to finish node setup.')
                self.results.setPlainText('\n'.join(f'{e["name"]}: {e["message"]}' for e in entries))
                self.results.show()
                self.open_webui.show()
                self.resize(self.width(), min(max(self.height(), 620), self.screen().availableGeometry().height() - 60))
                self.cancel.setText('Close')
                self.review = None
        self._controls()

    def _install(self):
        if self.job is not None or self.review is None: return
        names = [name for name, choice in self.choices.items() if choice.isChecked()]
        if not names: return
        replace = [name for name in names if self.review['files'][name]['state'] == 'present'] if self.replace.isChecked() else []
        if replace:
            result = QMessageBox.question(self, 'Replace existing workflows?',
                'Replace these files in the displayed destination?\n\n' + '\n'.join(replace),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if result != QMessageBox.StandardButton.Yes: return
        self._request('install', dict(names=names, replace=replace, review=self.review))

    def _webui_busy(self, busy):
        self.open_webui.setText('Checking / waiting for ComfyUI…' if busy else 'Start / open ComfyUI WebUI')
        self._controls()

    def _confirm_start(self):
        return QMessageBox.question(self, 'Start ComfyUI server?',
            'ComfyUI is not running at the configured address. Start the selected ComfyUI server, '
            'wait until it is ready, and then open its WebUI?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def _open_webui(self):
        self.webui.open()

    def reject(self):
        if self.job is None or self.operation == 'inspect':
            self._cleanup()
            super().reject()

    def _cleanup(self):
        self.webui.cancel()
        self.poll.stop()
        if self.job is not None: self.job.cancel(); self.job = None
        self._worker_holder.pop('job', None)

    def closeEvent(self, event):
        if self.job is not None and self.operation == 'install': event.ignore()
        else: super().closeEvent(event)
