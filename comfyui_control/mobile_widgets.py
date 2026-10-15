"""Desktop connection settings and a locally generated, secret-free QR code."""
from dataclasses import replace
import json

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QFileDialog,
    QScrollArea, QWidget,
)

from .mobile.server import qr_svg
from .mobile.settings import MobileSettings, password_hash
from .mobile.settings import data_dir
from .mobile.workflows import Presets


class MobileDialog(QDialog):
    def __init__(self, runtime, config, parent=None):
        super().__init__(parent)
        self.runtime, self.config = runtime, config
        self.setWindowTitle("Mobile WebUI")
        self.resize(570, 700)
        try:
            self.settings = MobileSettings.load()
        except (ValueError, OSError):
            self.settings = MobileSettings()
        outer = QVBoxLayout(self)
        contents = QWidget()
        layout = QVBoxLayout(contents)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(contents)
        outer.addWidget(area, 1)
        intro = QLabel("Generate from your phone using saved API workflows. ComfyUI stays managed by this desktop app.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.enabled = QCheckBox("Enable the integrated Mobile WebUI")
        self.enabled.setChecked(self.settings.enabled)
        form.addRow(self.enabled)
        self.bind = QLineEdit(self.settings.bind)
        self.bind.setPlaceholderText("127.0.0.1 (this computer), 0.0.0.0 (LAN/VPN), or interface IP")
        form.addRow("Listen on IP", self.bind)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.settings.port)
        form.addRow("Listen on port", self.port)
        self.advertised = QLineEdit(self.settings.advertised)
        self.advertised.setPlaceholderText("LAN/VPN hostname or IP; blank: detect. HTTPS proxy origin is also accepted.")
        form.addRow("Phone hostname / URL", self.advertised)
        self.comfy_url = QLineEdit(self.settings.comfy_url)
        form.addRow("ComfyUI API URL", self.comfy_url)
        self.auth = QCheckBox("Require a password (mandatory beyond localhost)")
        self.auth.setChecked(self.settings.require_auth)
        form.addRow(self.auth)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("New password, at least 10 characters; blank keeps existing password")
        form.addRow("Mobile password", self.password)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.url = QLabel()
        self.url.setWordWrap(True)
        self.url.setTextFormat(Qt.TextFormat.PlainText)
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.url)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr, 1)
        actions = QHBoxLayout()
        self.open = QPushButton("Open in browser")
        self.copy = QPushButton("Copy URL")
        self.open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.current_url)))
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.current_url))
        actions.addWidget(self.open)
        actions.addWidget(self.copy)
        layout.addLayout(actions)
        note = QLabel("Use 0.0.0.0 or your VPN interface to reach this server from a phone. Set the phone hostname explicitly for VPN use. Allow the chosen port through your firewall if needed; no router or firewall rules are changed by this app. HTTPS is needed for service workers; ordinary web use works over HTTP on a trusted LAN/VPN.")
        note.setWordWrap(True)
        layout.addWidget(note)
        import_button = QPushButton("Import API workflow from this computer…")
        import_button.clicked.connect(self._import)
        layout.addWidget(import_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._preview)
        for field in (self.bind, self.advertised):
            field.textChanged.connect(lambda: self.timer.start())
        self.port.valueChanged.connect(lambda: self.timer.start())
        runtime.changed.connect(self._status)
        self._preview()
        self._status(runtime.status, runtime.url)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import ComfyUI API workflow", "", "JSON files (*.json)")
        if not path:
            return
        try:
            from pathlib import Path
            source = Path(path)
            if source.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Workflow import is limited to 4 MB.")
            Presets(data_dir() / "presets").create(source.stem[:100], json.loads(source.read_text()))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot import workflow", str(exc))
            return
        QMessageBox.information(self, "Workflow imported", "Open or reload the Mobile WebUI, select this preset, and choose its input mappings under Advanced & workflows.")

    def _preview(self):
        try:
            settings = replace(self.settings, bind=self.bind.text().strip(), port=self.port.value(), advertised=self.advertised.text().strip())
            self.current_url = settings.url()
            self.url.setText(self.current_url)
            renderer = QSvgRenderer(qr_svg(self.current_url))
            pixmap = QPixmap(240, 240)
            pixmap.fill(Qt.GlobalColor.white)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            self.qr.setPixmap(pixmap)
            self.copy.setEnabled(True)
            self.open.setEnabled(self.runtime.status == "Listening" and self.runtime.url == self.current_url)
        except ValueError as exc:
            self.current_url = ""
            self.url.setText(str(exc))
            self.qr.clear()
            self.open.setEnabled(False)
            self.copy.setEnabled(False)

    def _status(self, status, url):
        self.status.setText("Server: " + status + (" · " + url if url else ""))
        self._preview()

    def _apply(self):
        try:
            settings = MobileSettings(
                enabled=self.enabled.isChecked(), bind=self.bind.text().strip(), port=self.port.value(),
                advertised=self.advertised.text().strip(), comfy_url=self.comfy_url.text().strip(),
                require_auth=self.auth.isChecked(),
                password=password_hash(self.password.text()) if self.password.text() else self.settings.password,
            )
            settings.save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check mobile settings", str(exc))
            return
        self.settings = settings
        self.password.clear()
        self.runtime.configure(settings, self.config, getattr(self.parent().controller, "state", "stopped") if self.parent() else "stopped")
