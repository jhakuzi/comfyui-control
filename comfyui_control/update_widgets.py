"""Choose the updater and ComfyUI environment before an update starts."""
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from .config import expand


class UpdateDialog(QDialog):
    def __init__(self, config, running=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update ComfyUI")
        self.resize(560, 260)
        self.original_config = config
        self.result_config = None
        layout = QVBoxLayout(self)
        folder = QLabel(str(config.directory))
        folder.setTextFormat(Qt.TextFormat.PlainText)
        folder.setWordWrap(True)
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(folder)
        form = QFormLayout()
        self.method = QComboBox()
        self.method.addItem("Git — git pull --ff-only", "git")
        self.method.addItem("Comfy CLI — comfy update", "cli")
        self.method.setCurrentIndex(self.method.findData(config.update_method))
        form.addRow("Update using", self.method)
        self.python = QLineEdit(config.python)
        self.python.setPlaceholderText(f"Auto: {config.interpreter()}")
        python_row = QWidget()
        row = QHBoxLayout(python_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.python, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_python)
        row.addWidget(browse)
        form.addRow("ComfyUI Python", python_row)
        self.requirements = QCheckBox("Git: also install requirements.txt")
        self.requirements.setChecked(config.install_requirements)
        form.addRow(self.requirements)
        layout.addLayout(form)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        lifecycle = QLabel(
            "Local changes or untracked files will stop the update. "
            + ("The running server will stop first and restart only after success." if running else "The server will stay stopped after updating.")
        )
        lifecycle.setWordWrap(True)
        layout.addWidget(lifecycle)
        layout.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Update ComfyUI")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.method.currentIndexChanged.connect(self._method_changed)
        self.requirements.toggled.connect(self._method_changed)
        self._method_changed()

    def _browse_python(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose ComfyUI environment's bin/python", str(expand(self.python.text() or self.original_config.interpreter())))
        if path:
            self.python.setText(path)

    def _method_changed(self):
        cli = self.method.currentData() == "cli"
        self.requirements.setEnabled(not cli)
        self.python.parentWidget().setEnabled(cli or self.requirements.isChecked())
        self.description.setText(
            "Runs comfy update in the selected ComfyUI Python environment, including requirements. "
            "Select that environment's bin/python above. Package changes may affect GPU dependencies."
            if cli else
            "Pulls ComfyUI code with git pull --ff-only. "
            + ("Requirements will also be installed using the selected Python; this may change GPU dependencies." if self.requirements.isChecked() else "Your Python packages will be left unchanged.")
        )

    def _accept(self):
        config = replace(
            self.original_config, update_method=self.method.currentData(),
            python=self.python.text().strip(), install_requirements=self.requirements.isChecked(),
        )
        try:
            config.validate()
            if config.update_method == "cli":
                config.cli_update()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check update settings", str(exc))
            return
        self.result_config = config
        self.accept()
