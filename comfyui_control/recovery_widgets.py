"""Native settings and a redacted, user-initiated crash diagnostics viewer."""
import os

from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget)


class RecoverySettings(QWidget):
    def __init__(self, config):
        super().__init__()
        form = QFormLayout(self)
        form.setContentsMargins(0,0,0,0)
        self.enabled = QCheckBox('Automatically restart ComfyUI after a crash')
        self.enabled.setChecked(config.auto_restart)
        self.limit = QSpinBox()
        self.limit.setRange(1,20)
        self.limit.setValue(config.restart_limit)
        self.backoff = QSpinBox()
        self.backoff.setRange(1,60)
        self.backoff.setSuffix(' s')
        self.backoff.setValue(config.restart_backoff)
        form.addRow(self.enabled)
        form.addRow('Maximum restart attempts',self.limit)
        form.addRow('Initial retry delay',self.backoff)
        note=QLabel('Retry delays double up to 60 seconds. The counter resets after 5 minutes of stable runtime. Intentional stops are never restarted.')
        note.setWordWrap(True)
        form.addRow(note)
        self.enabled.toggled.connect(self.limit.setEnabled)
        self.enabled.toggled.connect(self.backoff.setEnabled)
        self.limit.setEnabled(config.auto_restart)
        self.backoff.setEnabled(config.auto_restart)


class CrashDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle('ComfyUI crash diagnostics')
        self.resize(760,520)
        layout=QVBoxLayout(self)
        self.entries=QComboBox()
        for entry in history.entries:
            self.entries.addItem(f"{entry.get('timestamp','Unknown time')} · exit {entry.get('exit_code','--')}")
        layout.addWidget(self.entries)
        self.text=QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text,1)
        note=QLabel('Common credential patterns are redacted. Review before sharing: local paths, prompts or other sensitive output may remain.')
        note.setWordWrap(True)
        layout.addWidget(note)
        actions=QHBoxLayout()
        copy=QPushButton('Copy diagnostics')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        export=QPushButton('Export diagnostics…')
        export.clicked.connect(self._export)
        actions.addWidget(copy); actions.addWidget(export)
        layout.addLayout(actions)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.entries.currentIndexChanged.connect(self._selected)
        self.entries.setCurrentIndex(self.entries.count()-1)
        self._selected(self.entries.currentIndex())

    def _selected(self,index):
        self.text.setPlainText(self.history.text(index) if self.history.entries else 'No crash diagnostics recorded.')

    def _export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export crash diagnostics','comfyui-crash.txt','Text files (*.txt)')
        if not path: return
        try:
            with open(path,'w',encoding='utf-8',opener=lambda name,flags:os.open(name,flags,0o600)) as output:
                os.chmod(path,0o600)
                output.write(self.text.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self,'Could not export diagnostics',str(exc))
