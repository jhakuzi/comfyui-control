"""Guided, interactive Comfy CLI installation in the user's terminal."""
from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import shutil
import tempfile

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from .config import Config, config_path, expand


PYTHON_COMMANDS = {
    "Fedora": "python3 --version\n# Only if prerequisites are missing:\nsudo dnf install python3 python3-pip git",
    "Ubuntu / Debian": "python3 --version\n# Only if prerequisites are missing:\nsudo apt update\nsudo apt install python3 python3-pip python3-venv git -y",
    "Arch Linux": "python3 --version\n# Only if prerequisites are missing:\nsudo pacman -S python python-pip git",
}


@dataclass(frozen=True)
class InstallPlan:
    directory: Path
    python: str
    gpu: str = ""

    @property
    def environment(self):
        return self.directory.parent / (self.directory.name + "-env")

    def validate(self):
        if not self.directory.is_absolute() or self.directory == Path("/"):
            raise ValueError("Choose a new, absolute ComfyUI installation path.")
        if self.directory.exists() or self.directory.is_symlink():
            raise ValueError("The installation folder already exists. Select an existing installation or choose a new folder name.")
        if self.environment.exists() or self.environment.is_symlink():
            raise ValueError("The companion environment folder already exists. Choose another installation folder name.")
        if not self.python.strip() or not shutil.which(self.python):
            raise ValueError("Select an installed Python 3 executable. Use the package commands above if Python is missing.")
        if self.gpu not in ("", "--nvidia", "--amd", "--cpu"):
            raise ValueError("Unknown GPU installation option.")

    def commands(self):
        return "\n".join((
            shlex.join([self.python, "-m", "venv", str(self.environment)]),
            "source " + shlex.quote(str(self.environment / "bin" / "activate")),
            "python -m pip install comfy-cli",
            shlex.join(["comfy", "--workspace", str(self.directory), "install", *([self.gpu] if self.gpu else [])]),
        ))

    def script(self, result_path: Path):
        gpu = " " + self.gpu if self.gpu else ""
        return (
            "#!/usr/bin/env bash\nset -e\n\n"
            f"COMFYUI_DIR={shlex.quote(str(self.directory))}\n"
            f"COMFY_ENV={shlex.quote(str(self.environment))}\n"
            f"SETUP_PYTHON={shlex.quote(self.python)}\n"
            f"SETUP_RESULT={shlex.quote(str(result_path))}\n\n"
            '"$SETUP_PYTHON" -c \'import sys; print(sys.version); '
            'sys.exit(0 if sys.version_info[0] == 3 else "Select a Python 3 executable and retry.")\'\n'
            'command -v git >/dev/null || { echo "Install Git with your distribution package manager first." >&2; exit 1; }\n'
            'if [[ -e "$COMFYUI_DIR" || -L "$COMFYUI_DIR" || -e "$COMFY_ENV" || -L "$COMFY_ENV" ]]; then\n'
            '  echo "Installation or environment folder already exists. Choose a new location." >&2\n'
            '  exit 1\nfi\n'
            'mkdir -p -- "$(dirname -- "$COMFYUI_DIR")"\n'
            '"$SETUP_PYTHON" -m venv "$COMFY_ENV"\n'
            'source "$COMFY_ENV/bin/activate"\n'
            '"$COMFY_ENV/bin/python" -m pip install comfy-cli\n'
            f'"$COMFY_ENV/bin/comfy" --workspace "$COMFYUI_DIR" install{gpu}\n'
            '"$COMFY_ENV/bin/python" - "$COMFYUI_DIR" "$COMFY_ENV/bin/python" "$SETUP_RESULT" <<\'PY\'\n'
            'import json, sys\nfrom pathlib import Path\n'
            'directory, python, result = sys.argv[1:]\n'
            'if not (Path(directory) / "main.py").is_file():\n'
            '    raise SystemExit("ComfyUI main.py was not found. Check the installation output.")\n'
            'Path(result).write_text(json.dumps({"directory": directory, "python": python}), encoding="utf-8")\n'
            'PY\n'
            'echo "ComfyUI installed. Return to ComfyUI Control and choose Use this installation."\n'
        )


def terminal_command(script: Path):
    if terminal := shutil.which("konsole"):
        return [terminal, "--noclose", "-e", "/bin/bash", str(script)]
    if terminal := shutil.which("gnome-terminal"):
        return [terminal, "--", "/bin/bash", str(script)]
    if terminal := shutil.which("xterm"):
        return [terminal, "-hold", "-e", "/bin/bash", str(script)]
    raise ValueError("Install a terminal first, for example: sudo dnf install konsole. You can also copy the setup script and run it in your terminal.")


class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle("Set up ComfyUI")
        self.resize(460, 220)
        layout = QVBoxLayout(self)
        title = QLabel("Where is your ComfyUI installation?")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)
        description = QLabel("Choose an existing folder containing main.py, or install a new copy with Comfy CLI.")
        description.setWordWrap(True)
        layout.addWidget(description)
        existing = QPushButton("Choose existing installation…")
        install = QPushButton("Install with Comfy CLI…")
        existing.clicked.connect(lambda: self._choose("existing"))
        install.clicked.connect(lambda: self._choose("install"))
        layout.addWidget(existing)
        layout.addWidget(install)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, choice):
        self.choice = choice
        self.accept()


class InstallDialog(QDialog):
    def __init__(self, parent=None, *, application_style=""):
        super().__init__(parent)
        self.application_style = application_style
        self.setWindowTitle("Install ComfyUI with Comfy CLI")
        self.resize(670, 700)
        self.result_config = None
        self.plan = None
        self.result_path = None
        self.script_path = None
        layout = QVBoxLayout(self)
        introduction = QLabel("1. Use your installed Python 3 and Git; install missing prerequisites if needed.\n2. Choose the new ComfyUI location below.\n3. Open the setup terminal and answer Comfy CLI's prompts.")
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        self.distro = QComboBox()
        self.distro.addItems(PYTHON_COMMANDS)
        layout.addWidget(self.distro)
        self.package_commands = QPlainTextEdit()
        self.package_commands.setReadOnly(True)
        self.package_commands.setMaximumHeight(120)
        layout.addWidget(self.package_commands)
        note = QLabel("Your existing Python 3 is used, including Python 3.14. Run package-manager commands only for missing prerequisites. You can select another installed interpreter below.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.python = QLineEdit(shutil.which("python3") or "python3")
        self.location = QLineEdit(str(Path.home() / "ComfyUI"))
        self.location.setPlaceholderText("New ComfyUI installation folder")
        self.gpu = QComboBox()
        for label, value in (("Choose in the terminal", ""), ("NVIDIA", "--nvidia"), ("AMD / ROCm", "--amd"), ("CPU", "--cpu")):
            self.gpu.addItem(label, value)
        form.addRow("Python executable", self._row(self.python, self._browse_python))
        form.addRow("New installation folder", self._row(self.location, self._browse_parent))
        form.addRow("Hardware", self.gpu)
        layout.addLayout(form)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.commands = QPlainTextEdit()
        self.commands.setReadOnly(True)
        layout.addWidget(self.commands, 1)
        row = QHBoxLayout()
        self.open_terminal = QPushButton("Install ComfyUI")
        self.copy_commands = QPushButton("Copy setup commands")
        self.open_terminal.clicked.connect(self._open_terminal)
        self.copy_commands.clicked.connect(lambda: QApplication.clipboard().setText(self.commands.toPlainText()))
        row.addWidget(self.open_terminal)
        row.addWidget(self.copy_commands)
        layout.addLayout(row)
        self.status = QLabel("Installation output and prompts appear in the terminal. If you run copied commands manually, select the completed folder with Choose existing installation.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_installation = buttons.addButton("Use this installation", QDialogButtonBox.ButtonRole.AcceptRole)
        self.use_installation.setEnabled(False)
        self.use_installation.clicked.connect(self._use_installation)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.distro.currentTextChanged.connect(self._update_distro)
        self.location.textChanged.connect(self._preview)
        self.python.textChanged.connect(self._preview)
        self.gpu.currentIndexChanged.connect(self._preview)
        self._update_distro()
        self._preview()
        self.poll = QTimer(self)
        self.poll.setInterval(1000)
        self.poll.timeout.connect(self._check_result)

    def _row(self, field, callback):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return row

    def _browse_python(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select installed Python 3 executable", "/usr/bin")
        if path:
            self.python.setText(path)

    def _browse_parent(self):
        path = QFileDialog.getExistingDirectory(self, "Choose parent folder for the new ComfyUI installation", str(expand(self.location.text()).parent))
        if path:
            self.location.setText(str(Path(path) / "ComfyUI"))

    def _update_distro(self):
        self.package_commands.setPlainText(PYTHON_COMMANDS[self.distro.currentText()])

    def _current_plan(self):
        if not self.location.text().strip():
            raise ValueError("Choose a new ComfyUI installation location.")
        return InstallPlan(expand(self.location.text().strip()), self.python.text().strip(), self.gpu.currentData())

    def _preview(self):
        try:
            plan = self._current_plan()
        except ValueError:
            self.commands.clear()
            self.details.setText("Choose an installation location to preview setup.")
            return
        self.details.setText(f"A separate environment will be created at {plan.environment}. The app's environment is kept separate.")
        self.commands.setPlainText(plan.commands())

    def _open_terminal(self):
        try:
            plan = self._current_plan()
            plan.validate()
            config_path().parent.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="setup-", dir=config_path().parent))
            result = folder / "result.json"
            script = folder / "install.sh"
            script.write_text(plan.script(result), encoding="utf-8")
            command = terminal_command(script)
            ok, _ = QProcess.startDetached(command[0], command[1:])
            if not ok:
                raise ValueError("Could not open the setup terminal.")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not start setup", str(exc))
            return
        self.plan, self.result_path, self.script_path = plan, result, script
        self.open_terminal.setEnabled(False)
        self.location.parentWidget().setEnabled(False)
        self.python.parentWidget().setEnabled(False)
        self.gpu.setEnabled(False)
        self.status.setText("Setup is running in the terminal. If it fails, check the terminal output; cancel this dialog to retry at a new location.")
        self.poll.start()

    def _check_result(self):
        if self.result_path and self.result_path.is_file():
            try:
                data = json.loads(self.result_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not all(isinstance(data.get(key), str) for key in ("directory", "python")):
                    return
                config = Config(comfy_dir=data["directory"], python=data["python"], arguments="--cpu" if self.plan.gpu == "--cpu" else "", update_method="cli", application_style=self.application_style)
                if config.directory != self.plan.directory or config.interpreter() != str(self.plan.environment / "bin" / "python"):
                    return
                config.validate()
            except (ValueError, OSError, KeyError, TypeError):
                return
            self.result_config = config
            self.use_installation.setEnabled(True)
            self.status.setText("ComfyUI installed successfully. Choose Use this installation to save its location and Python environment.")
            self.poll.stop()

    def _use_installation(self):
        if not self.result_config:
            return
        try:
            self.result_config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save installation", str(exc))
            return
        self.accept()
