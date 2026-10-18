"""Native Qt Widgets interface. The output pane is a read-only log viewer."""
from dataclasses import replace
from pathlib import Path
import re
import shlex
import shutil
import sys

from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, QProcess, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStyleFactory, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)

from .config import Config, OutputScriptError, config_path, expand, installed_version
from .controller import Controller
from .launch_script import create_launch_script, prepare_script_update
from .script_flags import inspect_script
from .flag_widgets import LaunchFlags, LaunchScriptDialog
from .setup import InstallDialog, WelcomeDialog
from .update_widgets import UpdateDialog
from . import __version__
from .mobile.runtime import MobileRuntime
from .mobile.settings import MobileSettings
from .mobile_widgets import MobileDialog
from .monitor_widgets import MonitorPanel
from .recovery_widgets import RecoverySettings, CrashDialog
from .network_output_widgets import NetworkFields, NetworkOutput


def application_icon():
    icon = QIcon(str(Path(__file__).with_name("assets") / "comfyui-control.png"))
    return icon if not icon.isNull() else QIcon.fromTheme("utilities-terminal")


def apply_application_style(name):
    """Keep Qt's startup style as the platform default; never load plugin paths."""
    app = QApplication.instance()
    default = app.property("comfyuiDefaultStyle")
    if default is None:
        default = app.style().objectName()
        app.setProperty("comfyuiDefaultStyle", default)
    available = {key.casefold(): key for key in QStyleFactory.keys()}
    requested = available.get(name.casefold()) if name else default
    found = requested is not None
    requested = requested or default
    if app.style().objectName().casefold() != requested.casefold():
        style = QStyleFactory.create(requested)
        if style is None:
            return False
        app.setStyle(style)
    return found


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None, *, launch_locked=False):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        available = self.screen().availableGeometry()
        self.resize(min(820, max(400, available.width() - 60)), min(740, max(350, available.height() - 80)))
        self.original_config = config
        self.result_config = None
        self.script_changes = ()
        self.script_backup = None
        self.output_script_warning = ''
        self.setup_mount_requested = False
        self.launch_locked = launch_locked
        layout = QVBoxLayout(self)
        appearance = QFormLayout()
        self.application_style = QComboBox()
        self.application_style.addItem("System default", "")
        for key in sorted(QStyleFactory.keys(), key=str.casefold):
            self.application_style.addItem(key, key)
        selected = next((index for index in range(self.application_style.count())
                         if self.application_style.itemData(index).casefold() == config.application_style.casefold()), -1)
        if selected < 0:
            self.application_style.addItem(f"{config.application_style} (unavailable)", config.application_style)
            selected = self.application_style.count() - 1
            self.application_style.model().item(selected).setEnabled(False)
        self.application_style.setCurrentIndex(selected)
        appearance.addRow("Application style", self.application_style)
        self.close_behavior = QComboBox()
        for label, value in (('Ask me', 'ask'), ('Keep running in tray', 'tray'), ('Quit application', 'quit')):
            self.close_behavior.addItem(label, value)
        self.close_behavior.setCurrentIndex(self.close_behavior.findData(config.close_behavior))
        self.close_behavior.setToolTip('Choose what the window’s X button does. Keep in tray leaves ComfyUI and the Mobile WebUI running. Quit stops both and cancels active updates.')
        appearance.addRow('Close button action', self.close_behavior)
        layout.addLayout(appearance)
        if launch_locked:
            note = QLabel("Stop ComfyUI to change launch settings." if config.comfy_dir else "Select a ComfyUI installation to change launch settings.")
            note.setWordWrap(True)
            layout.addWidget(note)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.folder = QLineEdit(config.comfy_dir)
        self.python = QLineEdit(config.python)
        self.python.setPlaceholderText("Environment folder, bin/python, or blank for auto-detection")
        self.script = QLineEdit(config.script)
        self.mode = QComboBox()
        self.mode.addItem("Python — launch main.py", "python")
        self.mode.addItem("Existing Bash launch script", "script")
        self.mode.setCurrentIndex(1 if config.mode == "script" else 0)
        self.launch_options = LaunchFlags(config.directory, config.arguments)
        self.arguments = self.launch_options.extra_arguments
        self.output_dir = QLineEdit(config.output_dir)
        self.output_dir.setPlaceholderText("Default: ComfyUI/output")
        self.output_dir.setToolTip('ComfyUI will save to this folder on the next start or restart. Simple launch scripts are updated automatically with a backup when you save.')
        self.models_dir = QLineEdit(config.models_dir)
        self.models_dir.setPlaceholderText("Default: ComfyUI/models")
        form.addRow("ComfyUI folder", self._path_row(self.folder, directory=True))
        form.addRow("Launch method", self.mode)
        form.addRow("ComfyUI Python", self._path_row(self.python))
        form.addRow("Launch script", self._path_row(self.script, scripts=True))
        self.flags_toggle = QToolButton()
        self.flags_toggle.setCheckable(True)
        self.flags_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.flags_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.flags_toggle.toggled.connect(self._toggle_flags)
        form.addRow(self.flags_toggle)
        self.flags_contents = QWidget()
        flags_layout = QVBoxLayout(self.flags_contents)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.addWidget(self.launch_options)
        self.note = QLabel()
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        flags_layout.addWidget(self.note)
        form.addRow(self.flags_contents)
        self.flags_contents.hide()
        self.edit_script = QPushButton("Edit script file")
        self.edit_script.clicked.connect(self._edit_script)
        form.addRow(self.edit_script)
        self.output_row = self._path_row(self.output_dir, directory=True)
        form.addRow("Output folder", self.output_row)
        self.network_fields = NetworkFields(config)
        self.network_fields.setup_requested.connect(self._save_and_setup_mount)
        self.network_fields.toggled.connect(lambda enabled: self.output_row.setEnabled(not enabled))
        self.output_row.setEnabled(not config.nfs_enabled)
        form.addRow(self.network_fields)
        form.addRow("Models folder", self._path_row(self.models_dir, directory=True))
        self.update_method = QComboBox()
        self.update_method.addItem("Git — fast-forward pull", "git")
        self.update_method.addItem("Comfy CLI — comfy update", "cli")
        self.update_method.setCurrentIndex(self.update_method.findData(config.update_method))
        form.addRow("Update method", self.update_method)
        self.comfy_cli = QLineEdit(config.comfy_cli)
        self.comfy_cli.setPlaceholderText("Auto: ComfyUI environment's comfy, then PATH")
        form.addRow("Comfy CLI executable", self._path_row(self.comfy_cli, title="Choose Comfy CLI executable"))
        self.requirements = QCheckBox("Git: install requirements.txt after updating")
        self.requirements.setChecked(config.install_requirements)
        self.requirements.setToolTip("Runs pip in the ComfyUI Python selected above. May change installed packages, including GPU dependencies.")
        form.addRow(self.requirements)
        update_note = QLabel("Comfy CLI installs requirements in the selected ComfyUI environment. Enter its folder or bin/python above. Neither method updates custom nodes.")
        update_note.setWordWrap(True)
        form.addRow(update_note)
        self.monitoring = QCheckBox('Show system and generation monitoring')
        self.monitoring.setChecked(config.monitoring_enabled)
        form.addRow(self.monitoring)
        self.recovery_settings = RecoverySettings(config)
        form.addRow('Crash recovery', self.recovery_settings)
        self.launch_contents = QWidget()
        self.launch_contents.setLayout(form)
        self.launch_contents.setEnabled(not launch_locked)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.launch_contents)
        layout.addWidget(area)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.script.textChanged.connect(self._mode_changed)
        self.update_method.currentIndexChanged.connect(self._update_mode_changed)
        self._mode_changed()
        self._update_mode_changed()

    def _toggle_flags(self, expanded):
        if expanded:
            self._mode_changed()  # Re-read a script that may have been edited externally.
        self.flags_contents.setVisible(expanded)
        self.flags_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _path_row(self, field, directory=False, scripts=False, title=None):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)
        button = QPushButton("Browse")
        button.clicked.connect(lambda: self._browse(field, directory, scripts, title))
        layout.addWidget(button)
        return row

    def _browse(self, field, directory, scripts, title=None):
        start = str(expand(field.text() or self.folder.text()))
        if directory:
            path = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, title or ("Choose launch script" if scripts else "Choose Python executable"), start, "Shell scripts (*.sh);;All files (*)" if scripts else "All files (*)", options=QFileDialog.Option.DontResolveSymlinks)
        if path:
            field.setText(path)
            if scripts:
                self.flags_toggle.setChecked(True)

    def _mode_changed(self):
        script_mode = self.mode.currentData() == "script"
        self.script.parentWidget().setEnabled(script_mode)
        self.edit_script.setEnabled(script_mode)
        managed = script_mode and self.original_config.managed_script and self.script.text().strip() == self.original_config.script
        self.flags_toggle.setText("Edit script flags" if managed else "Script flags and additional arguments" if script_mode else "Edit launch flags")
        arguments = self.launch_options.argument_string(validate=False)
        previous = self.launch_options
        self.launch_options = LaunchFlags(expand(self.folder.text()), arguments)
        self.flags_contents.layout().replaceWidget(previous, self.launch_options)
        previous.hide()
        previous.deleteLater()
        self.arguments = self.launch_options.extra_arguments
        inspection = None
        if script_mode and not managed and self.script.text().strip():
            inspection = inspect_script(expand(self.script.text()))
            self.launch_options.show_script_arguments(inspection.arguments)
        self.note.setText(
            'Checkbox selections replace the default flags when the app starts this generated script. '
            'Uncheck a flag to remove it on the next start.'
            if managed else
            'Checked, locked options are read from the script; change them with “Edit script file”. '
            'App-added arguments remain editable and require the script to forward "$@".'
            if script_mode else
            "Arguments are passed directly to main.py. They are saved here and take effect on the next start."
        )
        if inspection and inspection.message:
            self.note.setText(self.note.text() + "\n" + inspection.message)

    def _update_mode_changed(self):
        cli = self.update_method.currentData() == "cli"
        self.comfy_cli.parentWidget().setEnabled(cli)
        self.requirements.setEnabled(not cli)

    def _edit_script(self):
        path = expand(self.script.text())
        if not self.script.text().strip() or not path.is_file():
            QMessageBox.warning(self, "Select a script", "Choose an existing launch script first.")
            return
        editor = shutil.which("kwrite") or shutil.which("kate")
        if not editor:
            QMessageBox.information(self, "Text editor unavailable", f"Open {path} in your text editor, or install KWrite or Kate.")
            return
        ok, _ = QProcess.startDetached(editor, [str(path)])
        if not ok:
            QMessageBox.warning(self, "Editor unavailable", "Could not open the launch script in the text editor.")

    def _save(self):
        if self.launch_locked:
            config = replace(self.original_config, application_style=self.application_style.currentData(),
                             close_behavior=self.close_behavior.currentData())
            try:
                config.save()
            except OSError as exc:
                QMessageBox.warning(self, "Could not save settings", str(exc))
                return
            self.result_config = config
            self.accept()
            return
        try:
            arguments = self.launch_options.argument_string()
        except ValueError as exc:
            QMessageBox.warning(self, "Check launch flags", str(exc))
            return
        config = replace(self.original_config,
            comfy_dir=self.folder.text().strip(), python=self.python.text().strip(),
            mode=self.mode.currentData(), script=self.script.text().strip(),
            arguments=arguments,
            output_dir=self.output_dir.text().strip(), models_dir=self.models_dir.text().strip(),
            install_requirements=self.requirements.isChecked(),
            update_method=self.update_method.currentData(), comfy_cli=self.comfy_cli.text().strip(),
            managed_script=(self.original_config.managed_script and
                            self.mode.currentData() == "script" and
                            self.script.text().strip() == self.original_config.script),
            monitoring_enabled=self.monitoring.isChecked(),
            auto_restart=self.recovery_settings.enabled.isChecked(),
            restart_limit=self.recovery_settings.limit.value(),
            restart_backoff=self.recovery_settings.backoff.value(),
            application_style=self.application_style.currentData(),
            close_behavior=self.close_behavior.currentData(),
            **self.network_fields.values(),
        )
        update, pending, applied = None, None, False
        try:
            try:
                config.validate()
            except OutputScriptError as exc:
                pending = exc
            if config.routes_output and config.mode == 'script' and not config.managed_script:
                try:
                    update = prepare_script_update(expand(config.script))
                except (ValueError, OSError, UnicodeError) as exc:
                    if pending is None:
                        raise ValueError('Could not safely update the launch script: ' + str(exc)) from exc
                    if not self._output_script_problem(config, pending, str(exc)):
                        return
                    self.output_script_warning = str(pending)
                else:
                    pending = None
            if update:
                self.script_backup = update.apply()
                applied = True
            if pending is None:
                config.validate()
            config.save()
        except (ValueError, OSError) as exc:
            message = str(exc)
            if applied:
                try:
                    update.rollback()
                    message += '\n\nThe launch-script update was rolled back because settings could not be saved.'
                except (ValueError, OSError) as rollback_error:
                    message += '\n\nThe script update could not be rolled back: ' + str(rollback_error)
                message += '\nOriginal script backup: ' + str(self.script_backup)
                self.script_backup = None
            QMessageBox.warning(self, "Could not save configuration", message)
            return
        if update:
            self.script_changes = update.changes
        self.result_config = config
        self.accept()

    def _save_and_setup_mount(self):
        self.setup_mount_requested = True
        self._save()
        if self.result_config is None:
            self.setup_mount_requested = False

    def _output_script_problem(self, config, problem, edit_error):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle('Launch script needs an update')
        box.setText(problem.summary)
        explanation = ('This launch-script check runs before any NAS connection attempt. '
                       'You can save these settings and set up the NAS mount now, but fix the script before starting ComfyUI.'
                       if config.nfs_enabled else
                       'You can save these settings, but fix the script before starting ComfyUI with the selected output folder.')
        box.setInformativeText('Automatic update was not possible: ' + edit_error + '\n\n' + explanation)
        box.setDetailedText(str(problem) + '\n\nFor a simple launch, append "$@" after your existing flags, '
                            'for example: exec python main.py "$@". Keep your current Python path, environment setup and flags. '
                            'For a multiline command, add a backslash before the newline preceding "$@". '
                            'Alternatively, use Create launch script or select Python — launch main.py in Settings.')
        save = box.addButton('Save settings for mount setup' if config.nfs_enabled else 'Save settings', QMessageBox.ButtonRole.AcceptRole)
        edit = box.addButton('Edit script file', QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked == edit:
            self._edit_script()
        return clicked == save


class LogView(QPlainTextEdit):
    """Stream text incrementally, removing ANSI sequences across read boundaries."""
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setStyleSheet("QPlainTextEdit { background: #171b20; color: #d6dde5; border: 1px solid #424b57; border-radius: 5px; padding: 10px; }")
        self._escape = ""
        self._pending_cr = False

    def append_output(self, text):
        text = self._escape + text
        self._escape = ""
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*?(?:\x07|\x1b\\)", "", text)
        # Hold an incomplete CSI/OSC escape until the next read.
        match = re.search(r"\x1b(?:\[[0-?]*[ -/]*|\][^\x07]*|)$", text)
        if match:
            self._escape, text = text[match.start():], text[:match.start()]
            if len(self._escape) > 8192:
                self._escape = ""
        text = re.sub(r"\x1b[@-_]", "", text)
        # Render progress carriage returns as separate log lines, not control text.
        if self._pending_cr and text.startswith("\n"):
            text = text[1:]
        self._pending_cr = text.endswith("\r")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        scroll = self.verticalScrollBar()
        follow = scroll.value() >= scroll.maximum() - 4
        old_value = scroll.value()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        scroll.setValue(scroll.maximum() if follow else old_value)


class MainWindow(QMainWindow):
    closed = Signal()

    def __init__(self, config, first_run=False, load_error=""):
        super().__init__()
        style_available = apply_application_style(config.application_style)
        self.setWindowTitle(f"ComfyUI Control {__version__}")
        self.setWindowIcon(application_icon())
        self.resize(920, 740)
        self.setMinimumSize(580, 400)
        self._closing = False
        self._tray_quit_requested = False
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_menu = QMenu(self)
        self.tray_open = self.tray_menu.addAction("Show window")
        self.tray_open.triggered.connect(self._restore_window)
        self.tray_menu.addSeparator()
        self.tray_quit = self.tray_menu.addAction("Quit")
        self.tray_quit.triggered.connect(self._quit_from_tray)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray_watch = QTimer(self)
        self.tray_watch.setInterval(3000)
        self.tray_watch.timeout.connect(self._check_tray)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.controller = Controller(config, self)
        self.network_output = NetworkOutput(self)
        self.controller.output_selector = self.network_output.select
        self.mobile = MobileRuntime(self)
        self.mobile.stopped.connect(self._mobile_stopped)
        body = QWidget()
        self.setCentralWidget(body)
        body.installEventFilter(self)
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        header = QGridLayout()
        header.setColumnStretch(0, 1)
        header.setHorizontalSpacing(10)
        header.setVerticalSpacing(8)
        self.comfy_title = QLabel("ComfyUI")
        self.comfy_title.setTextFormat(Qt.TextFormat.PlainText)
        self.comfy_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(self.comfy_title, 0, 0)
        self.setup_button = QPushButton("Set up ComfyUI")
        self.setup_button.clicked.connect(self._first_setup)
        header.addWidget(self.setup_button, 0, 1)
        self.status = QLabel("●  Stopped")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status, 2, 2)
        self.path_label = QLabel(config.comfy_dir or "No installation selected")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        header.addWidget(self.path_label, 1, 0)
        self.create_script_button = QPushButton("Create launch script")
        self.create_script_button.setToolTip("Create a Bash script using your Python environment and selected launch flags.")
        self.create_script_button.clicked.connect(self._create_script)
        header.addWidget(self.create_script_button, 1, 1)
        self.change_folder = QPushButton("Change folder")
        self.change_folder.clicked.connect(self._choose_folder)
        header.addWidget(self.change_folder, 1, 2)
        for button in (self.setup_button, self.create_script_button, self.change_folder):
            button.setMinimumHeight(30)
        self.status.setMinimumHeight(30)
        status_width = max(self.status.fontMetrics().horizontalAdvance("●  Process running") + 8, self.change_folder.sizeHint().width())
        self.status.setFixedWidth(status_width)
        self.change_folder.setFixedWidth(status_width)
        header.setColumnMinimumWidth(2, status_width)
        mobile_row = QHBoxLayout()
        mobile_row.setSpacing(12)
        self.mobile_button = QPushButton(QIcon.fromTheme("smartphone"), "Mobile WebUI")
        self.mobile_button.clicked.connect(self._mobile_settings)
        self.mobile_status = QLabel("Disabled")
        self.mobile_status.setWordWrap(True)
        self.mobile_status.setTextFormat(Qt.TextFormat.PlainText)
        mobile_row.addWidget(self.mobile_button)
        mobile_row.addWidget(self.mobile_status, 1)
        header.addLayout(mobile_row, 2, 0, 1, 2)
        self.crash_log = QPushButton('View crash log')
        self.crash_log.setFixedWidth(status_width)
        self.crash_log.setMinimumHeight(30)
        self.crash_log.clicked.connect(lambda: CrashDialog(self.controller.history, self).exec())
        self.crash_log.setVisible(bool(self.controller.history.entries))
        header.addWidget(self.crash_log, 0, 2)
        layout.addLayout(header)
        self.network_row = QWidget()
        network_layout = QHBoxLayout(self.network_row)
        network_layout.setContentsMargins(0, 0, 0, 0)
        self.network_status = QLabel()
        self.network_status.setTextFormat(Qt.TextFormat.PlainText)
        self.network_status.setWordWrap(True)
        self.network_retry = QPushButton('Retry network')
        self.network_retry.clicked.connect(self.network_output.retry)
        self.network_setup = QPushButton('Set up mount')
        self.network_setup.clicked.connect(self._setup_network_mount)
        self.network_remove = QPushButton('Remove mount')
        self.network_remove.clicked.connect(self._remove_network_mount)
        network_layout.addWidget(self.network_status, 1)
        network_layout.addWidget(self.network_retry)
        network_layout.addWidget(self.network_setup)
        network_layout.addWidget(self.network_remove)
        self.network_row.setVisible(config.nfs_enabled)
        layout.addWidget(self.network_row)
        self.monitor = MonitorPanel(self.controller, config, self)
        self.monitor.expanded_changed.connect(self._monitor_expanded)
        self.monitor.observation_changed.connect(self._observe_generation)
        self.mobile.execution.connect(self.monitor.execution)
        self.mobile.monitoring_requested.connect(self.monitor.set_mobile_demand)
        self.monitor.hardware_sampled.connect(self.mobile.publish_hardware)
        layout.addWidget(self.monitor)
        self.crash_notice = QWidget()
        crash_row=QHBoxLayout(self.crash_notice)
        crash_row.setContentsMargins(0, 0, 0, 0)
        self.crash_summary=QLabel()
        self._crash_message = ''
        self.crash_summary.setWordWrap(True)
        self.crash_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.cancel_recovery=QPushButton('Cancel recovery')
        self.cancel_recovery.clicked.connect(self.controller.stop)
        crash_row.addWidget(self.crash_summary,1)
        crash_row.addWidget(self.cancel_recovery)
        layout.addWidget(self.crash_notice)
        self.crash_notice.hide()
        self.cancel_recovery.hide()
        self.controller.crashed.connect(self._crashed)
        self.controller.recovery.connect(self._recovery)
        self.mobile.changed.connect(lambda status, url: self.mobile_status.setText(status))
        self.log = LogView()
        layout.addWidget(self.log, 1)
        controls = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        self.start_stop = self._button("Start", "media-playback-start", self._start_stop)
        self.restart = self._button("Restart", "view-refresh", self.controller.restart)
        self.update = self._button("Update", "system-software-update", self._update)
        self.update.setToolTip("Choose Git or Comfy CLI and review the Python environment before updating.")
        self.update_method = QComboBox()
        self.update_method.addItem("Git", "git")
        self.update_method.addItem("Comfy CLI", "cli")
        self.update_method.setCurrentIndex(self.update_method.findData(config.update_method))
        self.update_method.setAccessibleName("ComfyUI update method")
        self.update_method.setToolTip("Git: fast-forward pull, optional requirements. Comfy CLI: comfy update, including requirements.")
        self.update_method.setMinimumHeight(36)
        self.update_method.currentIndexChanged.connect(self._update_method_changed)
        update_row = QHBoxLayout()
        update_row.addWidget(self.update, 1)
        update_row.addWidget(self.update_method)
        left.addWidget(self.start_stop)
        left.addWidget(self.restart)
        left.addLayout(update_row)
        self.output_button = self._button("Open output folder", "folder-open", lambda: self._open_folder("output"))
        self.models_button = self._button("Open models folder", "folder-open", lambda: self._open_folder("models"))
        self.config_button = self._button("Settings", "configure", self._settings)
        right.addWidget(self.output_button)
        right.addWidget(self.models_button)
        right.addWidget(self.config_button)
        controls.addLayout(left, 1)
        controls.addSpacing(20)
        controls.addLayout(right, 1)
        layout.addLayout(controls)
        self.controller.output.connect(self.log.append_output)
        self.controller.changed.connect(self._state_changed)
        self.controller.problem.connect(self._problem)
        self._state_changed("stopped")
        self.log.append_output("Ready. Select your ComfyUI installation and launch settings, then press Start.\nThis panel shows server output; it does not accept terminal commands.\n")
        if not style_available:
            self.log.append_output(f"\nSaved application style {config.application_style!r} is unavailable; using the system default.\n")
        if load_error:
            self.log.append_output(f"\nConfiguration could not be loaded: {load_error}\nYour existing file was left untouched.\n")
        if first_run:
            QTimer.singleShot(0, self._first_setup)
        self.network_output.changed.connect(self._network_changed)
        self.network_output.notification.connect(self._network_notice)
        QTimer.singleShot(0, lambda: None if self._closing else self.network_output.configure(self.controller.config))
        QTimer.singleShot(0, self._start_mobile)

    def _network_changed(self):
        if self._closing:
            return
        if self.controller.state in {'stopped', 'crashed'} and self.controller.process is None:
            self.controller.config = self.network_output.select(self.controller.config)
            self.mobile.update_desktop(self.controller.config, self.controller.state)
        self._state_changed(self.controller.state)

    def _remove_network_mount(self):
        in_use = self.controller.process is not None or self.controller.state not in {'stopped', 'crashed'}
        self.network_output.remove(self, in_use=in_use)

    def _setup_network_mount(self):
        in_use = self.controller.process is not None or self.controller.state not in {'stopped', 'crashed'}
        self.network_output.setup(self, in_use=in_use)

    def _network_status(self):
        config = self.controller.config
        self.network_row.setVisible(config.nfs_enabled)
        status = self.network_output.status(config)
        self.mobile.update_output_status(status)
        self.network_status.setText('\n'.join(filter(None, (status.get('connection'), status.get('message')))))
        self.network_status.setStyleSheet('color: #e7b86a;' if status.get('level') in {'warning', 'error'} else '')
        self.network_retry.setEnabled(not self._closing and self.network_output.job is None and not self.network_output.setup_open)
        # Explicit setup can replace an in-progress startup probe.
        self.network_setup.setEnabled(not self._closing and not self.network_output.setup_open and
                                      not self.network_output.removing and
                                      self.controller.process is None and self.controller.state in {'stopped', 'crashed'} and
                                      (self.network_output.job is None or self.network_output.operation == 'probe'))
        self.network_remove.setEnabled(self.network_setup.isEnabled() and self.controller.process is None and
                                       self.controller.state in {'stopped', 'crashed'})

    def _network_notice(self, message):
        if self._closing:
            return
        text = message + '\n' + self.network_output.status(self.controller.config).get('message', '')
        self.log.append_output('\n[ComfyUI Control] ' + text + '\n')
        if self.tray.isVisible():
            self.tray.showMessage('Network output', text, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def _start_mobile(self):
        if self._closing:
            return
        try:
            settings = MobileSettings.load()
            self.mobile.configure(settings, self.controller.config, self.controller.state)
        except (ValueError, OSError) as exc:
            self.mobile_status.setText("Check mobile settings")
            self.log.append_output(f"\nMobile WebUI did not start: {exc}\n")

    def _mobile_settings(self):
        MobileDialog(self.mobile, self.controller.config, self).exec()

    def _observe_generation(self, enabled):
        self.mobile.configure(self.mobile.settings, self.controller.config, self.controller.state, observe=enabled)

    def _monitor_expanded(self, expanded):
        config = replace(self.controller.config, monitor_expanded=expanded)
        try:
            config.save()
            self.controller.config = config
        except OSError as exc:
            self.log.append_output(f'\nCould not save monitoring preference: {exc}\n')

    def _crashed(self, entry):
        self._crash_message = entry['summary']
        self.crash_summary.setText(self._crash_message)
        self.crash_notice.show()
        self.crash_log.setVisible(True)

    def _recovery(self, text):
        self.crash_summary.setText('\n'.join(filter(None, [self._crash_message, text])))
        self.cancel_recovery.setVisible(self.controller.state == 'restarting')
        self.crash_notice.setVisible(bool(self.crash_summary.text()) or self.controller.state == 'restarting')

    def _mobile_stopped(self):
        if self._closing:
            QTimer.singleShot(20, self.close)

    def _button(self, text, icon, callback):
        button = QPushButton(QIcon.fromTheme(icon), text)
        button.setMinimumHeight(36)
        button.clicked.connect(callback)
        return button

    def _first_setup(self):
        choice = WelcomeDialog(self)
        if choice.exec() != QDialog.DialogCode.Accepted:
            return
        if choice.choice == "existing" and self._choose_folder():
            self._settings()
        elif choice.choice == "install":
            dialog = InstallDialog(self, application_style=self.controller.config.application_style,
                                   close_behavior=self.controller.config.close_behavior)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._set_config(dialog.result_config)
                self.log.append_output(f"\nComfy CLI setup complete: {dialog.result_config.comfy_dir}\n")
                self._settings()

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select ComfyUI folder (containing main.py)", str(self.controller.config.directory))
        if not path:
            return False
        # A new installation should get its own interpreter, script, and folders.
        previous = self.controller.config
        config = Config(comfy_dir=path, monitoring_enabled=previous.monitoring_enabled,
                        monitor_expanded=previous.monitor_expanded, auto_restart=previous.auto_restart,
                        restart_limit=previous.restart_limit, restart_backoff=previous.restart_backoff,
                        application_style=previous.application_style, close_behavior=previous.close_behavior)
        try:
            config.validate()
            config.save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check ComfyUI folder", str(exc))
            return False
        self._set_config(config)
        self.log.append_output(f"\nSelected ComfyUI folder: {path}\nLaunch settings reset for this installation. Choose an existing script in Settings if needed.\n")
        return True

    def _set_config(self, config):
        self.controller.set_config(config)
        self.network_output.configure(config)
        config = self.controller.config
        self.monitor.configure(config)
        self.mobile.update_desktop(config, self.controller.state)
        blocked = self.update_method.blockSignals(True)
        self.update_method.setCurrentIndex(self.update_method.findData(config.update_method))
        self.update_method.blockSignals(blocked)
        self.path_label.setText(config.comfy_dir or "No installation selected")
        self.path_label.setToolTip(str(config.directory))
        self._state_changed(self.controller.state)

    def _update_method_changed(self):
        config = replace(self.controller.config, update_method=self.update_method.currentData())
        try:
            config.save()
        except OSError as exc:
            self._set_config(self.controller.config)
            QMessageBox.warning(self, "Could not save update method", str(exc))
            return
        self._set_config(config)

    def _create_script(self):
        config = self.controller.config
        if not config.comfy_dir.strip() or not (config.directory / "main.py").is_file():
            QMessageBox.warning(self, "Choose ComfyUI folder", "Choose the ComfyUI folder containing main.py first.")
            return
        dialog = LaunchScriptDialog(config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            arguments = dialog.options.argument_string()
        except ValueError as exc:
            QMessageBox.warning(self, "Check launch flags", str(exc))
            return
        # Keep personal scripts outside the Git checkout so updates stay clean.
        default = config_path().parent / "launch-comfyui.sh"
        path, _ = QFileDialog.getSaveFileName(
            self, "Create a new launch script", str(default),
            "Shell scripts (*.sh);;All files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(".sh")
        try:
            interpreter = config.interpreter()
            if not config.python and not any(candidate.is_file() for candidate in config.local_interpreters()):
                interpreter = str(config.directory / "comfy-env" / "bin" / "python")
            create_launch_script(config.directory, destination, shlex.split(arguments), python=interpreter)
        except FileExistsError:
            QMessageBox.warning(self, "Script already exists", "Choose a new filename. Existing launch scripts are not overwritten.")
            return
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not create script", str(exc))
            return
        updated = replace(
            config, mode="script", script=str(destination), arguments=arguments, managed_script=True,
            python=interpreter,
        )
        try:
            updated.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save launch settings", f"The script was created at {destination}, but could not be selected:\n{exc}")
            return
        self._set_config(updated)
        self.log.append_output(
            f"\nCreated and selected launch script: {destination}\n"
            "Uses your selected Python environment, the HIP allocator, and your selected flags.\n"
            "Use Settings to change the flag checkboxes before the next start.\n"
        )

    def _settings(self):
        current = self.controller.config
        locked = self.controller.state not in {'stopped', 'crashed'} or not (current.directory / 'main.py').is_file() or not current.comfy_dir
        dialog = SettingsDialog(current, self, launch_locked=locked)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.result_config
            if replace(config, application_style=current.application_style, close_behavior=current.close_behavior) == current:
                self.controller.config = config
            else:
                self._set_config(config)
            if dialog.script_changes:
                self.log.append_output('\n[ComfyUI Control] Updated launch script: ' + config.script + '\n' +
                                       '\n'.join(dialog.script_changes) + '\nOriginal backup: ' + str(dialog.script_backup) +
                                       '\nChanges apply on the next ComfyUI start or restart.\n')
            if dialog.output_script_warning:
                self.log.append_output('\n[ComfyUI Control] Saved output settings for setup; launch script still needs attention.\n' +
                                       dialog.output_script_warning + '\n')
            if not apply_application_style(config.application_style):
                QMessageBox.information(self, "Style unavailable", "This style could not be loaded. Choose System default or another available style.")
            if dialog.setup_mount_requested:
                QTimer.singleShot(0, lambda: None if self._closing else self._setup_network_mount())

    def _start_stop(self):
        if self.controller.state in {'stopped','crashed'}:
            self.controller.start()
        else:
            self.controller.stop()

    def _state_changed(self, state):
        self.mobile.update_desktop(self.controller.config, state)
        self._network_status()
        labels = {"stopped": "Stopped", "starting": "Starting…", "running": "Process running", "stopping": "Stopping…", "updating": "Updating…", 'crashed':'Crashed', 'restarting':'Restarting…'}
        self.status.setText("●  " + labels[state])
        self.tray.setToolTip("ComfyUI Control — " + ("Closing…" if self._closing else labels[state]))
        self.tray_open.setEnabled(not self._closing)
        self.tray_quit.setEnabled(not self._closing)
        color = {"stopped": "#8795a5", "running": "#48a878", 'crashed':'#d36c6c'}.get(state, "#d69c42")
        self.status.setStyleSheet(f"color: {color};")
        active = state in ("starting", "running")
        idle = state in {'stopped','crashed'}
        configured = bool(self.controller.config.comfy_dir.strip()) and (self.controller.config.directory / "main.py").is_file()
        self.start_stop.setText("Stop" if active else "Start")
        self.start_stop.setIcon(QIcon.fromTheme("media-playback-stop" if active else "media-playback-start"))
        mount_busy = self.network_output.removing
        self.start_stop.setEnabled(((idle and configured) or active) and not self._closing and not mount_busy)
        self.restart.setEnabled(((idle and configured) or active) and not self._closing and not mount_busy)
        self.update.setEnabled(((idle and configured) or active) and not self._closing and not mount_busy)
        self.update_method.setEnabled(((idle and configured) or active) and not self._closing and not mount_busy)
        self.config_button.setEnabled(not self._closing and not mount_busy)
        if state == 'stopped':
            version = installed_version(self.controller.config.directory) if self.controller.config.comfy_dir else ''
            self.comfy_title.setText(f"ComfyUI - {version}" if version else "ComfyUI")
        self.change_folder.setEnabled(idle and not self._closing and not mount_busy)
        self.create_script_button.setEnabled(idle and configured and not self._closing and not mount_busy)
        self.setup_button.setEnabled(idle and not self._closing and not mount_busy)
        self.output_button.setEnabled(configured and not self._closing and not mount_busy)
        self.models_button.setEnabled(configured and not self._closing)
        self.cancel_recovery.setVisible(state == 'restarting')
        self.crash_notice.setVisible(bool(self.crash_summary.text()) or state == 'restarting')
        if self._closing and idle:
            QTimer.singleShot(0, self.close)

    def _problem(self, message):
        if not self._closing and self.controller.state not in {'crashed','restarting'}:
            QMessageBox.warning(self, "ComfyUI Control", message)

    def _update(self):
        dialog = UpdateDialog(self.controller.config, running=self.controller.state in ("starting", "running"), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dialog.result_config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save update settings", str(exc))
            return
        self._set_config(dialog.result_config)
        self.controller.update()

    def _open_folder(self, kind):
        path = self.controller.config.folder(kind)
        if kind == 'output' and self.controller.config.session_network_output:
            # The file manager handles network access in its own process.
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                QMessageBox.warning(self, 'Could not open folder', 'Could not open network output in the file manager.')
            return
        if not path.is_dir():
            QMessageBox.information(self, "Folder unavailable", f"Folder does not exist:\n{path}\n\nSet a custom folder in Settings if needed.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Could not open folder", f"Could not open {path} in the file manager.")

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.centralWidget():
            self._fit_contents()
        return result

    def eventFilter(self, watched, event):
        if watched is self.centralWidget() and event.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, self._fit_contents)
        return super().eventFilter(watched, event)

    def _fit_contents(self):
        # Wrapped labels can change their minimum after the inner layout runs.
        # Recheck the central layout too, including its current-width height.
        body = self.centralWidget()
        self.setMinimumHeight(max(400, body.minimumSizeHint().height(), body.heightForWidth(body.width())))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'monitor'):
            self.monitor._activity()

    def _restore_window(self):
        if self._closing:
            return
        self.tray_watch.stop()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_window()

    def _check_tray(self):
        # The tray host may disappear (for example when Plasma restarts).
        # Check only while hidden, so the app never becomes inaccessible.
        if self.isVisible():
            self.tray_watch.stop()
        elif not QSystemTrayIcon.isSystemTrayAvailable():
            self._restore_window()

    def _close_choice(self):
        choice = QMessageBox(self)
        choice.setWindowTitle("Close ComfyUI Control")
        choice.setIcon(QMessageBox.Icon.Question)
        choice.setText("Keep ComfyUI Control running in the tray, or quit?")
        warning = "ComfyUI and the Mobile WebUI keep running in the tray. Quitting stops both."
        if self.controller.state == 'updating':
            warning += " Quitting also cancels the update. If packages are being installed, rerun the update before starting ComfyUI."
        remember = QCheckBox('Remember this choice')
        remember.setChecked(True)
        choice.setCheckBox(remember)
        choice.setInformativeText(warning + '\nChange this later in Settings → Close button action.')
        keep = choice.addButton("Keep in tray", QMessageBox.ButtonRole.AcceptRole)
        quit_button = choice.addButton("Quit", QMessageBox.ButtonRole.DestructiveRole)
        cancel = choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.setDefaultButton(keep)
        choice.setEscapeButton(cancel)
        choice.exec()
        clicked = choice.clickedButton()
        result = 'tray' if clicked == keep else 'quit' if clicked == quit_button else 'cancel'
        if result in ('tray', 'quit') and remember.isChecked():
            config = replace(self.controller.config, close_behavior=result)
            try:
                config.save()
            except OSError as exc:
                QMessageBox.warning(self, 'Could not remember close action', str(exc) + '\nYour choice will be used this time, but was not saved.')
            else:
                self.controller.config = config
        choice.deleteLater()
        return result

    def _quit_from_tray(self):
        self._tray_quit_requested = True
        self.close()
        if not self._closing:
            self._tray_quit_requested = False

    def closeEvent(self, event):
        quit_confirmed = not self._tray_quit_requested and self.controller.config.close_behavior == 'quit'
        if not self._closing and not self._tray_quit_requested and QSystemTrayIcon.isSystemTrayAvailable():
            choice = self._close_choice() if self.controller.config.close_behavior == 'ask' else self.controller.config.close_behavior
            if choice == 'tray':
                if QSystemTrayIcon.isSystemTrayAvailable():
                    self.tray.show()
                    self.hide()
                    self.tray_watch.start()
                event.ignore()
                return
            if choice != 'quit':
                event.ignore()
                return
            quit_confirmed = True
        if self.controller.state in {'stopped','crashed','restarting'} and self.controller.process is None:
            self._closing = True
            self.network_output.stop()
            self.controller.shutdown()
            self.monitor.stop()
            if self.mobile.running:
                self._closing = True
                self.mobile.stop()
                QTimer.singleShot(30, self.close)
                event.ignore()
                return
            event.accept()
            self.monitor.stop()
            self.tray_watch.stop()
            self.tray.hide()
            self.closed.emit()
            return
        if not self._closing:
            question = "Stop ComfyUI and close the window?" if self.controller.state != "updating" else "Cancel the update and close? If packages are being installed, rerun the update before starting ComfyUI."
            if not quit_confirmed and QMessageBox.question(self, "Close ComfyUI Control", question, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing = True
            self.tray_watch.stop()
            self.network_output.stop()
            self.monitor.stop()
            self.mobile.stop()
            self.controller.shutdown()
            self._state_changed(self.controller.state)
        event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ComfyUI Control")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("comfyui-control")
    app.setWindowIcon(application_icon())
    if sys.platform != "linux":
        QMessageBox.critical(None, "Linux required", "ComfyUI Control currently supports Linux only.")
        return 1
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        QMessageBox.critical(None, "Cannot save settings", str(exc))
        return 1
    lock = QLockFile(str(path.parent / "control.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, "Already open", "ComfyUI Control is already running for this user.")
        return 1
    load_error = ""
    try:
        config = Config.load(path)
    except (ValueError, OSError) as exc:
        config, load_error = Config(), str(exc)
    configured = bool(config.comfy_dir.strip()) and (config.directory / "main.py").is_file()
    window = MainWindow(config, first_run=not configured, load_error=load_error)
    window.closed.connect(app.quit)
    window.show()
    result = app.exec()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    lock.unlock()
    return result


if __name__ == "__main__":
    sys.exit(main())
