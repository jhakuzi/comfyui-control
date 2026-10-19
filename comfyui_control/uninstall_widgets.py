"""Confirmation and progress for the shared per-user uninstaller."""
import os
from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QMessageBox, QProgressBar, QVBoxLayout

from .uninstall import UninstallError, discover_installation, execute_plan, prepare_plan


class UninstallDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Uninstall ComfyUI Control')
        self.resize(620, 420)
        self.config = config
        self.plan = None
        self.installation = discover_installation(current_only=True)
        layout = QVBoxLayout(self)
        self.choice = QComboBox()
        self.choice.addItem('Only uninstall ComfyUI Control — keep ComfyUI', False)
        self.choice.addItem('Uninstall the app and remove ComfyUI', True)
        layout.addWidget(self.choice)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.confirm_label = QLabel('To permanently remove ComfyUI, type its full folder path below:')
        self.confirm = QLineEdit()
        self.confirm.setAccessibleName('Confirm ComfyUI folder path')
        layout.addWidget(self.confirm_label)
        layout.addWidget(self.confirm)
        note = QLabel('Uninstalling stops this app’s ComfyUI server and Mobile WebUI. '
                      'App settings/history, external Python environments, external model/output folders and NAS files are kept. '
                      'Source checkouts and shared pip dependencies are kept.')
        note.setWordWrap(True)
        layout.addWidget(note)
        if config.nfs_server:
            note = QLabel('NFS mount definitions are kept. To remove this app’s managed definition too, cancel and use Remove mount in the main window first.')
            note.setWordWrap(True)
            layout.addWidget(note)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.remove = buttons.addButton('Uninstall', QDialogButtonBox.ButtonRole.DestructiveRole)
        self.remove.clicked.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        layout.addWidget(buttons)
        self.choice.currentIndexChanged.connect(self._preview)
        self.confirm.textChanged.connect(self._preview)
        self._preview()

    def _preview(self):
        both = self.choice.currentData()
        self.confirm.setVisible(both)
        self.confirm_label.setVisible(both)
        self.summary.setText('Remove app: ' + self.installation.description +
            ('\n\nPERMANENTLY DELETE: ' + (str(self.config.directory) if self.config.comfy_dir else '(no configured ComfyUI folder)') +
             '\nThis includes models, workflows, custom nodes and output images physically stored inside that folder.' if both else '\n\nYour ComfyUI installation will be kept.'))
        self.error.clear()
        self.remove.setEnabled(not both or bool(self.config.comfy_dir.strip()) and bool(self.confirm.text().strip()))

    def _accept(self):
        try:
            plan = prepare_plan(self.installation, self.config.comfy_dir if self.choice.currentData() else None,
                                allow_pid=os.getpid(), check_server=False)
            if plan.comfy and self.confirm.text().strip() != str(plan.comfy):
                raise UninstallError('Type the actual full folder path: ' + str(plan.comfy))
        except (UninstallError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.plan = plan
        self.accept()


class UninstallWorker(QThread):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.error = ''
        self.message = ''

    def run(self):
        try:
            self.message = execute_plan(self.plan, allow_pid=os.getpid())
        except Exception as exc:
            self.error = str(exc)


class UninstallProgress(QDialog):
    def __init__(self, plan):
        super().__init__()
        self.setWindowTitle('Uninstalling ComfyUI Control')
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Removing the confirmed files. Please wait.'))
        bar = QProgressBar()
        bar.setRange(0, 0)
        layout.addWidget(bar)
        self.worker = UninstallWorker(plan, self)
        self.worker.finished.connect(self.accept)

    def reject(self):
        if not self.worker.isRunning():
            super().reject()


def run_uninstall(plan):
    # Run after the desktop and its owned server/mobile threads have shut down.
    progress = UninstallProgress(plan)
    progress.worker.start()
    progress.exec()
    progress.worker.wait()
    if progress.worker.error:
        QMessageBox.critical(None, 'Uninstall stopped', progress.worker.error +
                             '\n\nSome confirmed files may already have been removed. App settings were kept.')
        return 1
    QMessageBox.information(None, 'Uninstalled', progress.worker.message)
    return 0
