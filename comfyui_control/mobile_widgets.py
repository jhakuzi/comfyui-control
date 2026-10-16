"""Desktop connection settings and a locally generated, secret-free QR code."""
from dataclasses import replace
import asyncio
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QFileDialog,
    QScrollArea, QWidget, QComboBox,
)

from .mobile.server import qr_svg
from .mobile.settings import MobileSettings, password_hash, lan_address
from .mobile.settings import data_dir, save_json
from .mobile.workflows import Presets, suggested_mappings
from .mobile.client import ComfyClient
from .mobile.workflow_sources import queued_workflow, import_graph, saved_workflows, saved_workflow_graph


class WorkflowSignals(QObject):
    finished = Signal(object, str)


class WorkflowFetch(QRunnable):
    def __init__(self, url, editor=None, catalog=False, saved=None):
        super().__init__()
        self.url, self.editor = url, editor
        self.catalog, self.saved = catalog, saved
        self.signals = WorkflowSignals()

    def run(self):
        async def fetch():
            import aiohttp
            async with aiohttp.ClientSession() as session:
                client = ComfyClient(session, self.url)
                operation = saved_workflows(client) if self.catalog else saved_workflow_graph(client, self.saved) if self.saved else import_graph(client, self.editor) if self.editor is not None else queued_workflow(client)
                return await asyncio.wait_for(operation, 10)
        try:
            graph = asyncio.run(fetch())
        except Exception as exc:
            self.signals.finished.emit(None, str(exc) or "ComfyUI did not respond. Start it and check its API URL.")
        else:
            self.signals.finished.emit(graph, "")


class MobileDialog(QDialog):
    def __init__(self, runtime, config, parent=None):
        super().__init__(parent)
        self.runtime, self.config = runtime, config
        self.worker = None
        self.import_name = ""
        self.import_source = None
        self.loading_catalog = False
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
        network_row = QHBoxLayout()
        network_row.addWidget(self.bind, 1)
        self.detect = QPushButton("Use LAN / VPN")
        self.detect.clicked.connect(self._detect)
        network_row.addWidget(self.detect)
        form.addRow("Listen on IP", network_row)
        self.detected = QLabel("Detected address: " + lan_address())
        self.detected.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.detected)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.settings.port)
        form.addRow("Listen on port", self.port)
        self.advertised = QLineEdit(self.settings.advertised)
        self.advertised.setPlaceholderText("LAN/VPN hostname or IP; blank: detect. HTTPS proxy origin is also accepted.")
        form.addRow("Phone hostname / URL", self.advertised)
        self.comfy_url = QLineEdit(self.settings.comfy_url)
        form.addRow("ComfyUI API URL", self.comfy_url)
        self.auth = QCheckBox("Use a password (optional)")
        self.auth.setChecked(self.settings.require_auth)
        form.addRow(self.auth)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("New password, at least 10 characters; blank keeps existing password")
        form.addRow("Mobile password", self.password)
        self.password.setEnabled(self.auth.isChecked())
        self.auth.toggled.connect(self.password.setEnabled)
        self.default_preset = QComboBox()
        self.default_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.default_preset.setMinimumContentsLength(14)
        self._refresh_presets(self.settings.default_preset)
        form.addRow("Default workflow", self.default_preset)
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
        workflow_note = QLabel("Choose a workflow on this PC and save it as the phone's default. Your previous phone selection and unsent edits are kept.")
        workflow_note.setWordWrap(True)
        layout.addWidget(workflow_note)
        self.import_button = QPushButton("Choose workflow file from this computer…")
        self.import_button.clicked.connect(self._import)
        layout.addWidget(self.import_button)
        self.queued_button = QPushButton("Use latest queued workflow from ComfyUI")
        self.queued_button.clicked.connect(lambda: self._fetch_workflow("ComfyUI — latest queued workflow"))
        layout.addWidget(self.queued_button)
        self.catalog_button = QPushButton("Browse workflows saved in ComfyUI…")
        self.catalog_button.clicked.connect(lambda: self._fetch_workflow("", catalog=True))
        layout.addWidget(self.catalog_button)
        self.workflow_status = QLabel()
        self.workflow_status.setWordWrap(True)
        self.workflow_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.workflow_status)
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

    def _refresh_presets(self, selected):
        self.default_preset.clear()
        self.default_preset.addItem("Choose a default…", "")
        for item in Presets(data_dir() / "presets").list():
            self.default_preset.addItem(item["name"], item["id"])
        index = self.default_preset.findData(selected)
        self.default_preset.setCurrentIndex(max(index, 0))

    def _detect(self):
        self.bind.setText("0.0.0.0")
        self.advertised.clear()
        self.detected.setText("Detected address: " + lan_address())
        self._preview()

    def _import(self):
        folder = self.config.directory / "user" / "default" / "workflows"
        path, _ = QFileDialog.getOpenFileName(self, "Choose ComfyUI workflow", str(folder if folder.is_dir() else self.config.directory), "JSON files (*.json)")
        if not path:
            return
        try:
            source = Path(path)
            if source.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Workflow import is limited to 4 MB.")
            value = json.loads(source.read_text())
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                self._fetch_workflow(source.stem[:100], value)
                return
            self._save_workflow(source.stem[:100], value)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot import workflow", str(exc))
            return

    def _save_workflow(self, name, graph, source=None):
        store = Presets(data_dir() / "presets")
        preset = store.create(name, graph)
        preset = store.map(preset["id"], suggested_mappings(preset["graph"]))
        if source:
            preset["comfy_source"] = source
            save_json(store.path(preset["id"]), preset)
        self._refresh_presets(preset["id"])
        self.workflow_status.setText("Workflow copied. Apply to save the default, then use Open in browser to map its controls once under Advanced & workflows. The phone will use the same saved mapping.")

    def _fetch_workflow(self, name, editor=None, catalog=False, saved=None):
        if self.worker:
            return
        try:
            replace(self.settings, comfy_url=self.comfy_url.text().strip()).validate(require_password=False)
        except ValueError as exc:
            self.workflow_status.setText(str(exc))
            return
        self.import_name = name
        self.import_source = saved
        self.loading_catalog = catalog
        self.import_button.setEnabled(False)
        self.queued_button.setEnabled(False)
        self.catalog_button.setEnabled(False)
        self.workflow_status.setText("Reading saved ComfyUI workflows…" if catalog else "Reading workflow from ComfyUI…")
        self.worker = WorkflowFetch(self.comfy_url.text().strip(), editor, catalog, saved)
        self.worker.signals.finished.connect(self._workflow_loaded)
        QThreadPool.globalInstance().start(self.worker)

    @Slot(object, str)
    def _workflow_loaded(self, graph, error):
        self.worker = None
        self.import_button.setEnabled(True)
        self.queued_button.setEnabled(True)
        self.catalog_button.setEnabled(True)
        if error:
            self.workflow_status.setText(error)
            return
        if self.loading_catalog:
            from PySide6.QtWidgets import QInputDialog
            if not graph:
                self.workflow_status.setText("No saved JSON workflows found. Save one in ComfyUI's Workflows menu first.")
                return
            name, accepted = QInputDialog.getItem(self, "Saved ComfyUI workflows", "Workflow", graph, 0, False)
            if accepted:
                self._fetch_workflow(Path(name).stem[:100], saved=name)
            return
        try:
            self._save_workflow(self.import_name, graph, self.import_source)
        except (ValueError, OSError) as exc:
            self.workflow_status.setText(str(exc))

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
                default_preset=self.default_preset.currentData() or "",
            )
            settings.save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check mobile settings", str(exc))
            return
        self.settings = settings
        self.password.clear()
        self.runtime.configure(settings, self.config, getattr(self.parent().controller, "state", "stopped") if self.parent() else "stopped")
