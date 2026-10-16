"""Native Qt Widgets interface. The output pane is a read-only log viewer."""
from dataclasses import replace
from pathlib import Path
import re
import shlex
import shutil
import sys

from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from .config import Config, config_path, expand
from .controller import Controller
from .launch_script import create_launch_script
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


def application_icon():
    icon = QIcon(str(Path(__file__).with_name("assets") / "comfyui-control.png"))
    return icon if not icon.isNull() else QIcon.fromTheme("utilities-terminal")


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ComfyUI launch configuration")
        self.resize(680, 520)
        self.original_config = config
        self.result_config = None
        layout = QVBoxLayout(self)
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
        self.edit_script = QPushButton("Edit script file…")
        self.edit_script.clicked.connect(self._edit_script)
        form.addRow(self.edit_script)
        form.addRow("Output folder", self._path_row(self.output_dir, directory=True))
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
        contents = QWidget()
        contents.setLayout(form)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(contents)
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
        button = QPushButton("Browse…")
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
            'Checked, locked options are read from the script; change them with “Edit script file…”. '
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
        )
        try:
            config.validate()
            config.save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check configuration", str(exc))
            return
        self.result_config = config
        self.accept()


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
    def __init__(self, config, first_run=False, load_error=""):
        super().__init__()
        self.setWindowTitle(f"ComfyUI Control {__version__}")
        self.setWindowIcon(application_icon())
        self.resize(800, 570)
        self.setMinimumSize(580, 400)
        self._closing = False
        self.controller = Controller(config, self)
        self.mobile = MobileRuntime(self)
        self.mobile.stopped.connect(self._mobile_stopped)
        body = QWidget()
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        header = QGridLayout()
        header.setColumnStretch(0, 1)
        header.setHorizontalSpacing(10)
        header.setVerticalSpacing(8)
        title = QLabel("ComfyUI")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title, 0, 0)
        self.setup_button = QPushButton("Set up ComfyUI…")
        self.setup_button.clicked.connect(self._first_setup)
        header.addWidget(self.setup_button, 0, 1)
        self.status = QLabel("●  Stopped")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status, 0, 2)
        self.path_label = QLabel(config.comfy_dir or "No installation selected")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        header.addWidget(self.path_label, 1, 0)
        self.create_script_button = QPushButton("Create launch script…")
        self.create_script_button.setToolTip("Create a Bash script using your Python environment and selected launch flags.")
        self.create_script_button.clicked.connect(self._create_script)
        header.addWidget(self.create_script_button, 1, 1)
        self.change_folder = QPushButton("Change folder…")
        self.change_folder.clicked.connect(self._choose_folder)
        header.addWidget(self.change_folder, 1, 2)
        for button in (self.setup_button, self.create_script_button, self.change_folder):
            button.setMinimumHeight(30)
        self.status.setMinimumHeight(30)
        status_width = max(self.status.fontMetrics().horizontalAdvance("●  Process running") + 8, self.change_folder.sizeHint().width())
        self.status.setFixedWidth(status_width)
        self.change_folder.setFixedWidth(status_width)
        header.setColumnMinimumWidth(2, status_width)
        layout.addLayout(header)
        mobile_row = QHBoxLayout()
        self.mobile_button = QPushButton(QIcon.fromTheme("smartphone"), "Mobile WebUI…")
        self.mobile_button.clicked.connect(self._mobile_settings)
        self.mobile_status = QLabel("Disabled")
        self.mobile_status.setWordWrap(True)
        self.mobile_status.setTextFormat(Qt.TextFormat.PlainText)
        mobile_row.addWidget(self.mobile_button)
        mobile_row.addWidget(self.mobile_status, 1)
        layout.addLayout(mobile_row)
        self.monitor = MonitorPanel(self.controller, config, self)
        self.monitor.expanded_changed.connect(self._monitor_expanded)
        self.monitor.observation_changed.connect(self._observe_generation)
        self.mobile.execution.connect(self.monitor.execution)
        layout.addWidget(self.monitor)
        crash_row=QHBoxLayout()
        self.crash_summary=QLabel()
        self._crash_message = ''
        self.crash_summary.setWordWrap(True)
        self.crash_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.crash_log=QPushButton('View crash log…')
        self.crash_log.clicked.connect(lambda: CrashDialog(self.controller.history,self).exec())
        self.cancel_recovery=QPushButton('Cancel recovery')
        self.cancel_recovery.clicked.connect(self.controller.stop)
        crash_row.addWidget(self.crash_summary,1)
        crash_row.addWidget(self.crash_log)
        crash_row.addWidget(self.cancel_recovery)
        layout.addLayout(crash_row)
        self.crash_log.setVisible(bool(self.controller.history.entries))
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
        self.config_button = self._button("Edit launch configuration…", "configure", self._settings)
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
        if load_error:
            self.log.append_output(f"\nConfiguration could not be loaded: {load_error}\nYour existing file was left untouched.\n")
        if first_run:
            QTimer.singleShot(0, self._first_setup)
        QTimer.singleShot(0, self._start_mobile)

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
        self.crash_log.setVisible(True)

    def _recovery(self, text):
        self.crash_summary.setText('\n'.join(filter(None, [self._crash_message, text])))
        self.cancel_recovery.setVisible(self.controller.state == 'restarting')

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
            dialog = InstallDialog(self)
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
                        restart_limit=previous.restart_limit, restart_backoff=previous.restart_backoff)
        try:
            config.validate()
            config.save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check ComfyUI folder", str(exc))
            return False
        self._set_config(config)
        self.log.append_output(f"\nSelected ComfyUI folder: {path}\nLaunch settings reset for this installation. Choose an existing script in Edit launch configuration if needed.\n")
        return True

    def _set_config(self, config):
        self.controller.set_config(config)
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
            "Use Edit launch configuration to change the flag checkboxes before the next start.\n"
        )

    def _settings(self):
        dialog = SettingsDialog(self.controller.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_config(dialog.result_config)

    def _start_stop(self):
        if self.controller.state in {'stopped','crashed'}:
            self.controller.start()
        else:
            self.controller.stop()

    def _state_changed(self, state):
        self.mobile.update_desktop(self.controller.config, state)
        labels = {"stopped": "Stopped", "starting": "Starting…", "running": "Process running", "stopping": "Stopping…", "updating": "Updating…", 'crashed':'Crashed', 'restarting':'Restarting…'}
        self.status.setText("●  " + labels[state])
        color = {"stopped": "#8795a5", "running": "#48a878", 'crashed':'#d36c6c'}.get(state, "#d69c42")
        self.status.setStyleSheet(f"color: {color};")
        active = state in ("starting", "running")
        idle = state in {'stopped','crashed'}
        configured = bool(self.controller.config.comfy_dir.strip()) and (self.controller.config.directory / "main.py").is_file()
        self.start_stop.setText("Stop" if active else "Start")
        self.start_stop.setIcon(QIcon.fromTheme("media-playback-stop" if active else "media-playback-start"))
        self.start_stop.setEnabled(((idle and configured) or active) and not self._closing)
        self.restart.setEnabled(((idle and configured) or active) and not self._closing)
        self.update.setEnabled(((idle and configured) or active) and not self._closing)
        self.update_method.setEnabled(((idle and configured) or active) and not self._closing)
        self.config_button.setEnabled(idle and configured and not self._closing)
        self.change_folder.setEnabled(idle and not self._closing)
        self.create_script_button.setEnabled(idle and configured and not self._closing)
        self.setup_button.setEnabled(idle and not self._closing)
        self.output_button.setEnabled(configured and not self._closing)
        self.models_button.setEnabled(configured and not self._closing)
        self.cancel_recovery.setVisible(state == 'restarting')
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
        if not path.is_dir():
            QMessageBox.information(self, "Folder unavailable", f"Folder does not exist:\n{path}\n\nSet a custom folder in Edit launch configuration if needed.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Could not open folder", f"Could not open {path} in the file manager.")

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.centralWidget():
            # Keep the expanded metrics and controls readable at larger font
            # sizes instead of letting the log overlap their minimum heights.
            self.setMinimumHeight(max(400, self.centralWidget().minimumSizeHint().height()))
        return result

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'monitor'):
            self.monitor._activity()

    def closeEvent(self, event):
        if self.controller.state in {'stopped','crashed','restarting'} and self.controller.process is None:
            self._closing = True
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
            return
        if not self._closing:
            question = "Stop ComfyUI and close the window?" if self.controller.state != "updating" else "Cancel the update and close? If packages are being installed, rerun the update before starting ComfyUI."
            if QMessageBox.question(self, "Close ComfyUI Control", question, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing = True
            self.monitor.stop()
            self.mobile.stop()
            self.controller.shutdown()
            self._state_changed(self.controller.state)
        event.ignore()


def main():
    app = QApplication(sys.argv)
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
    window.show()
    result = app.exec()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    lock.unlock()
    return result


if __name__ == "__main__":
    sys.exit(main())
