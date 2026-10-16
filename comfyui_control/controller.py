"""Asynchronous process ownership, shutdown, and Git or Comfy CLI updates."""
import codecs
import os
from pathlib import Path
import shlex
import shutil
import signal
import math
import time
from dataclasses import replace

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .config import Config
from .diagnostics import CrashHistory


class Controller(QObject):
    output = Signal(str)
    changed = Signal(str)
    problem = Signal(str)
    crashed = Signal(object)
    recovery = Signal(str)

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
        self._cli_update = None
        self.history = CrashHistory()
        self.output.connect(self.history.append)
        self._attempts = 0
        self._snapshot = None
        self._identity = None
        self._deadline = None
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(250)
        self._recovery_timer.timeout.connect(self._recovery_tick)
        self._stable_timer = QTimer(self)
        self._stable_timer.setSingleShot(True)
        self._stable_timer.timeout.connect(self._stable)
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
        self._start(manual=True)

    def _launch_identity(self):
        return (str(self.config.directory), tuple(self.config.command()), self.config.python)

    def _start(self, manual):
        if self.process is not None or self.state not in {'stopped','crashed','restarting'} or self._closing:
            return
        self._cancel_recovery()
        if manual:
            self._attempts = 0
        try:
            self.config.validate()
        except (ValueError, OSError) as exc:
            self._error(str(exc))
            if not manual:
                self._state('crashed')
                self.recovery.emit('Launch configuration is no longer valid; recovery cancelled.')
            return
        if manual:
            self._snapshot = replace(self.config)
            self._identity = self._launch_identity()
        elif self._launch_identity() != self._identity:
            self._state('crashed')
            self.recovery.emit('Launch settings changed; automatic recovery cancelled.')
            return
        self._state("starting")
        self._spawn(self.config.command(), "server")

    def _spawn(self, command, kind):
        if self.process is not None:
            return
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
        if kind == "update" and self._step == "Update with Comfy CLI":
            # Comfy CLI may be installed globally/pipx, but requirements must
            # go into the selected ComfyUI environment, never the GUI's venv.
            for name in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME"):
                env.remove(name)
            for name, value in self._cli_update[1].items():
                env.insert(name, value)
            self._message("Comfy CLI environment: " + self._cli_update[1].get("VIRTUAL_ENV", self._cli_update[1].get("CONDA_PREFIX", "")))
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
        if kind == "update" and self._step == "Update with Comfy CLI":
            process.closeWriteChannel()  # Unexpected prompts get EOF, not a hung update.

    def _started(self):
        if self.sender() is not self.process:
            return
        self._pid = self.process.processId()
        if self.state == "stopping":
            self._signal(signal.SIGTERM)
        elif self._kind == "server":
            self._state("running")
            self._stable_timer.start(300000)

    def _read(self):
        if isinstance(self.sender(), QProcess) and self.sender() is not self.process:
            return
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
        self._cancel_recovery()
        if self.state in {'crashed','restarting'} and self.process is None:
            self._state('stopped')
            self.recovery.emit('Automatic recovery cancelled.')
            return
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
        elif self.state in {'stopped','crashed','restarting'}:
            self.start()

    def _release(self):
        self._kill_timer.stop()
        self._stable_timer.stop()
        self._read()
        self.output.emit(self._decoder.decode(b"", final=True))
        # A shell may exit before its background children. Clean up our group.
        self._signal(signal.SIGKILL)
        self._pid = 0
        old, self.process = self.process, None
        old.deleteLater()

    def _finished(self, code, exit_status):
        if self.sender() is not self.process:
            return
        kind, step = self._kind, self._step
        stopping = self.state == "stopping"
        self._release()
        # Drain may have supplied trailing metadata.
        captured = self._captured
        if stopping:
            self._message("Process and its children successfully stopped.")
            after, self._after_stop = self._after_stop, None
            self._state("stopped")
            if not self._closing:
                if after == "restart":
                    self.start()
                elif after == "update":
                    self._begin_update()
            return
        if kind == "server":
            self._message(f"Server exited (code {code}).")
            if code or exit_status == QProcess.ExitStatus.CrashExit:
                self._crash(code, exit_status.name)
                self.problem.emit("ComfyUI exited unexpectedly. Check the output above.")
            else:
                self._state('stopped')
                self.recovery.emit('')
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
            self._update_failed("There are local changes to tracked ComfyUI files. Commit or restore them before updating. Nothing was discarded.")
            return
        self._next_step()

    def _process_error(self, error):
        if self.sender() is not self.process:
            return
        if error != QProcess.ProcessError.FailedToStart:
            return  # Crashes also emit finished; handle completion exactly once.
        detail = self.process.errorString()
        stopping = self.state == "stopping"
        self._release()
        self._after_stop = None
        self._resume = False
        self._state("stopped")
        if not stopping:
            if self._kind == 'server' and self._attempts:
                self._message(f"Could not start process: {detail}")
                self._crash(-1, 'FailedToStart', detail)
            else:
                self._error(f"Could not start process: {detail}")

    def _stable(self):
        self._attempts = 0
        self.recovery.emit('Recovery counter reset after 5 minutes of stable runtime.')

    def _cancel_recovery(self):
        self._recovery_timer.stop()
        self._deadline = None

    def _crash(self, code, status, detail=''):
        self._state('crashed')
        try:
            entry = self.history.record(code,status,shlex.join(self._snapshot.command() if self._snapshot else self.config.command()),
                                        self._snapshot.directory if self._snapshot else self.config.directory,detail)
        except OSError:
            entry = dict(summary=f'ComfyUI crashed (exit {code}); diagnostics could not be saved.',exit_code=code)
        self.crashed.emit(entry)
        if self._closing or not self.config.auto_restart:
            self.recovery.emit('Automatic restart is disabled.')
            return
        if self._attempts >= self.config.restart_limit:
            self.recovery.emit(f'Recovery limit reached ({self._attempts} attempts). You can restart manually.')
            return
        try:
            unchanged = self._identity is not None and self._launch_identity() == self._identity
        except (ValueError,OSError):
            unchanged = False
        if not unchanged:
            self.recovery.emit('Launch settings changed; automatic recovery cancelled.')
            return
        self._attempts += 1
        delay = min(self.config.restart_backoff * 2**(self._attempts-1),60)
        self._deadline = time.monotonic()+delay
        self._state('restarting')
        self._recovery_timer.start()
        self._recovery_tick()

    def _recovery_tick(self):
        if self._closing or not self.config.auto_restart:
            self.stop()
            return
        if self._deadline is None or self.process is not None:
            self._cancel_recovery()
            return
        remaining = max(0,self._deadline-time.monotonic())
        if remaining:
            self.recovery.emit(f'Restart attempt {self._attempts}/{self.config.restart_limit} in {math.ceil(remaining)}s · Cancel to stay stopped.')
        else:
            self._start(manual=False)

    def set_config(self, config):
        if self.state == 'restarting':
            self.stop()
        self.config = config

    def update(self):
        if self.state == 'restarting':
            self.stop()
        if self.state not in ("stopped", "crashed", "starting", "running"):
            return
        try:
            self.config.validate()
            if not shutil.which("git"):
                raise ValueError("Git is not installed. Install it with: sudo dnf install git")
            if self.config.update_method not in ("git", "cli"):
                raise ValueError("Unknown update method. Choose Git or Comfy CLI.")
            self._cli_update = self.config.cli_update() if self.config.update_method == "cli" else None
            if self.config.update_method == "git" and self.config.install_requirements and not shutil.which(self.config.interpreter()):
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
        self._cancel_recovery()
        self._steps = [
            ("Check repository", ["git", "rev-parse", "--show-toplevel"]),
            # Local configuration and GPU crash dumps need not be committed.
            # Git itself rejects a pull that would overwrite untracked files.
            ("Check local changes", ["git", "status", "--porcelain", "--untracked-files=no"]),
        ]
        if self.config.update_method == "cli":
            self._steps.append(("Update with Comfy CLI", self._cli_update[0]))
        else:
            self._steps.append(("Pull ComfyUI", ["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"]))
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
        self._cancel_recovery()
        self._stable_timer.stop()
        if self.state in {'crashed','restarting'} and self.process is None:
            self._state('stopped')
        if self.state in ("running", "starting", "updating"):
            self.stop()
