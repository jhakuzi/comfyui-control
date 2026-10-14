"""Asynchronous process ownership, shutdown, and safe Git updates."""
import codecs
import os
from pathlib import Path
import shlex
import shutil
import signal

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .config import Config


class Controller(QObject):
    output = Signal(str)
    changed = Signal(str)
    problem = Signal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.state = "stopped"
        self.process = None
        self._pid = 0
        self._after_stop = None
        self._resume = False
        self._closing = False
        self._steps = []
        self._step = ""
        self._captured = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_stop)

    def _state(self, value):
        self.state = value
        self.changed.emit(value)

    def _message(self, text):
        self.output.emit(f"\n[ComfyUI Control] {text}\n")

    def _error(self, text):
        self._message(text)
        self.problem.emit(text)

    def start(self):
        if self.state != "stopped" or self._closing:
            return
        try:
            self.config.validate()
        except (ValueError, OSError) as exc:
            self._error(str(exc))
            return
        self._state("starting")
        self._spawn(self.config.command(), "server")

    def _spawn(self, command, kind):
        self._kind = kind
        self._captured = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(self.config.directory))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("TERM", "dumb")
        env.insert("NO_COLOR", "1")
        env.insert("GIT_TERMINAL_PROMPT", "0")
        process.setProcessEnvironment(env)
        params = QProcess.UnixProcessParameters()
        params.flags = QProcess.UnixProcessFlag.CreateNewSession
        process.setUnixProcessParameters(params)
        process.readyReadStandardOutput.connect(self._read)
        process.started.connect(self._started)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        self._message("$ " + shlex.join(command))
        process.start(command[0], command[1:])

    def _started(self):
        self._pid = self.process.processId()
        if self.state == "stopping":
            self._signal(signal.SIGTERM)
        elif self._kind == "server":
            self._state("running")

    def _read(self):
        if self.process is None:
            return
        raw = bytes(self.process.readAllStandardOutput())
        text = self._decoder.decode(raw)
        if self._kind == "update":
            # Git metadata fits here; pip logs needn't be retained indefinitely.
            self._captured = (self._captured + text)[-1_000_000:]
        self.output.emit(text)

    def _signal(self, sig):
        if self._pid:
            try:
                os.killpg(self._pid, sig)
            except ProcessLookupError:
                pass

    def stop(self, after=None):
        if self.state not in ("starting", "running", "updating"):
            return
        self._after_stop = after
        self._state("stopping")
        self._message("Stopping process and its children…")
        self._signal(signal.SIGTERM)
        self._kill_timer.start(8000)

    def _force_stop(self):
        if self.process:
            self._message("Process did not stop within 8 seconds; forcing shutdown.")
            self._signal(signal.SIGKILL)

    def restart(self):
        if self.state in ("starting", "running"):
            self.stop("restart")
        elif self.state == "stopped":
            self.start()

    def _release(self):
        self._kill_timer.stop()
        self._read()
        self.output.emit(self._decoder.decode(b"", final=True))
        # A shell may exit before its background children. Clean up our group.
        self._signal(signal.SIGKILL)
        self._pid = 0
        old, self.process = self.process, None
        old.deleteLater()

    def _finished(self, code, exit_status):
        kind, step = self._kind, self._step
        stopping = self.state == "stopping"
        self._release()
        # Drain may have supplied trailing metadata.
        captured = self._captured
        if stopping:
            after, self._after_stop = self._after_stop, None
            self._state("stopped")
            if not self._closing:
                if after == "restart":
                    self.start()
                elif after == "update":
                    self._begin_update()
            return
        if kind == "server":
            self._state("stopped")
            self._message(f"Server exited (code {code}).")
            if code or exit_status == QProcess.ExitStatus.CrashExit:
                self.problem.emit("ComfyUI exited unexpectedly. Check the output above.")
            return
        if code or exit_status == QProcess.ExitStatus.CrashExit:
            self._update_failed(f"Update stopped at “{step}” (exit {code}). Check the output. The server remains stopped.")
            return
        if step == "Check repository":
            root = Path(captured.strip()).resolve()
            if root != self.config.directory.resolve():
                self._update_failed("The ComfyUI folder must be the root of its own Git checkout.")
                return
        elif step == "Check local changes" and captured.strip():
            self._update_failed("There are local changes or untracked files. Commit or move them before updating. Nothing was discarded.")
            return
        self._next_step()

    def _process_error(self, error):
        if error != QProcess.ProcessError.FailedToStart:
            return  # Crashes also emit finished; handle completion exactly once.
        detail = self.process.errorString()
        stopping = self.state == "stopping"
        self._release()
        self._after_stop = None
        self._resume = False
        self._state("stopped")
        if not stopping:
            self._error(f"Could not start process: {detail}")

    def update(self):
        if self.state not in ("stopped", "starting", "running"):
            return
        try:
            self.config.validate()
            if not shutil.which("git"):
                raise ValueError("Git is not installed. Install it with: sudo dnf install git")
            if self.config.install_requirements and not os.access(self.config.interpreter(), os.X_OK):
                raise ValueError("Set an explicit working ComfyUI Python executable before installing requirements.")
        except (ValueError, OSError) as exc:
            self._error(str(exc))
            return
        self._resume = self.state in ("starting", "running")
        if self._resume:
            self.stop("update")
        else:
            self._begin_update()

    def _begin_update(self):
        self._steps = [
            ("Check repository", ["git", "rev-parse", "--show-toplevel"]),
            ("Check local changes", ["git", "status", "--porcelain", "--untracked-files=normal"]),
            ("Pull ComfyUI", ["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"]),
        ]
        if self.config.install_requirements:
            self._steps.append(("Install requirements", [self.config.interpreter(), "-m", "pip", "install", "-r", "requirements.txt"]))
        self._state("updating")
        self._next_step()

    def _next_step(self):
        if self._steps:
            self._step, command = self._steps.pop(0)
            self._message(self._step)
            self._spawn(command, "update")
        else:
            resume, self._resume = self._resume, False
            self._state("stopped")
            self._message("Update complete.")
            if resume and not self._closing:
                self.start()

    def _update_failed(self, message):
        self._steps.clear()
        self._resume = False
        self._state("stopped")
        self._error(message)

    def shutdown(self):
        self._closing = True
        self._resume = False
        self._steps.clear()
        self._after_stop = None
        if self.state in ("running", "starting", "updating"):
            self.stop()
