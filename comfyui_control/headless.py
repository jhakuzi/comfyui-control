"""Foreground SSH runtime using the same owned processes and mobile backend."""
from dataclasses import replace
import signal
import sys

from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, QObject, QThreadPool, QTimer, Signal

from . import __version__
from .config import Config, config_path
from .controller import Controller
from .hardware import HardwareReader
from .hardware_worker import Sample
from .mobile.runtime import MobileRuntime
from .mobile.settings import MobileSettings
from .network_output_widgets import NetworkOutput


class TerminalSession(QObject):
    finished = Signal(int)

    def __init__(self, config, mobile_settings, *, start_server, start_webui, parent=None):
        super().__init__(parent)
        self.controller = Controller(config, self)
        self.network = NetworkOutput(self)
        self.controller.output_selector = self.network.select
        self.mobile = MobileRuntime(self)
        self.settings = replace(mobile_settings, enabled=start_webui)
        self.start_server = start_server
        self.start_webui = start_webui
        self.pending_start = start_server
        self.initializing = True
        self._closing = False
        self.exit_code = 0
        self.last_failure = False
        self.stop_signal = None
        self.reader = HardwareReader()
        self.sample = None
        self.hardware_timer = QTimer(self)
        self.hardware_timer.setInterval(1000)
        self.hardware_timer.timeout.connect(self._sample_hardware)
        self.controller.output.connect(self._output)
        self.controller.problem.connect(self._problem)
        self.controller.recovery.connect(lambda text: self._message(text) if text else None)
        self.controller.changed.connect(self._state_changed)
        self.network.changed.connect(self._network_changed)
        self.network.notification.connect(self._message)
        self.mobile.changed.connect(self._mobile_changed)
        self.mobile.monitoring_requested.connect(self._hardware_demand)
        # Returning to Python regularly also makes Unix signals responsive while
        # Qt is idle; handlers merely record a request for this timer to process.
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def _output(self, text):
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except BrokenPipeError:
            self.stop_signal = signal.SIGHUP

    def _message(self, text):
        self._output(f'\n[ComfyUI Control] {text}\n')

    def _problem(self, text):
        self.last_failure = True
        self._message(text)
        QTimer.singleShot(0, self._check_controller)

    def start(self):
        self.timer.start()
        self._message(f'{__version__} — terminal mode. Press Ctrl+C to stop.')
        self.network.configure(self.controller.config)
        if self.start_webui:
            self.mobile.configure(self.settings, self.controller.config, self.controller.state)
        self.initializing = False
        if self.pending_start and self.controller.config.nfs_enabled and self.controller.config.nfs_auto_connect:
            self._message('Checking network output before starting ComfyUI.')
        # configure() schedules an automatic NFS probe first. Do not launch in
        # its synchronous changed signal before that queued check has started.
        QTimer.singleShot(0, self._maybe_start)

    def _network_changed(self):
        if self._closing:
            return
        if self.controller.process is None and self.controller.state in {'stopped', 'crashed'}:
            self.controller.config = self.network.select(self.controller.config)
        self.mobile.update_desktop(self.controller.config, self.controller.state)
        self.mobile.update_output_status(self.network.status(self.controller.config))
        if not self.initializing:
            self._maybe_start()

    def _maybe_start(self):
        if self._closing or self.stop_signal or self.initializing or not self.pending_start or self.network.job:
            return
        self.pending_start = False
        self.controller.start()
        self.mobile.update_desktop(self.controller.config, self.controller.state)
        status = self.network.status(self.controller.config)
        self.mobile.update_output_status(status)
        if status.get('message'):
            self._message(status['message'])
        QTimer.singleShot(0, self._check_controller)

    def _state_changed(self, state):
        if state == 'running':
            self.last_failure = False
        self.mobile.update_desktop(self.controller.config, state)
        QTimer.singleShot(0, self._check_controller)

    def _check_controller(self):
        # A crash passes through 'crashed' before scheduling saved recovery.
        # Check on the next event-loop turn so that existing recovery can run.
        if (not self._closing and self.start_server and not self.pending_start and
                self.controller.process is None and self.controller.state in {'stopped', 'crashed'}):
            failed = self.last_failure or self.controller.state == 'crashed'
            self.shutdown(1 if failed else 0)

    def _mobile_changed(self, status, url):
        if self._closing:
            return
        self._message('Mobile WebUI: ' + status + (f' · {url}' if url else ''))
        if status == 'Listening':
            # NFS may have finished while the HTTP thread was initializing.
            self.mobile.update_desktop(self.controller.config, self.controller.state)
            self.mobile.update_output_status(self.network.status(self.controller.config))
        if status.startswith(('Not started:', 'Could not start Mobile WebUI:')):
            self.shutdown(1)

    def _hardware_demand(self, enabled):
        if enabled and not self._closing:
            if not self.hardware_timer.isActive():
                self.reader.reset()
                self.hardware_timer.start()
                self._sample_hardware()
        else:
            self.hardware_timer.stop()

    def _sample_hardware(self):
        if self.sample or self._closing or not self.hardware_timer.isActive():
            return
        self.sample = Sample(self.reader, self.controller._pid)
        self.sample.signals.finished.connect(self._hardware_ready)
        QThreadPool.globalInstance().start(self.sample)

    def _hardware_ready(self, value):
        self.sample = None
        if not self._closing:
            self.mobile.publish_hardware(value)

    def shutdown(self, exit_code=0):
        if self._closing:
            return
        self._closing = True
        self.exit_code = exit_code
        self.pending_start = False
        self.hardware_timer.stop()
        self.network.stop()
        self._message('Stopping terminal session.')
        self.mobile.stop()
        self.controller.shutdown()

    def _tick(self):
        if self.stop_signal and not self._closing:
            self._message(f'Received {signal.Signals(self.stop_signal).name}.')
            self.shutdown()
        if self._closing and self.controller.process is None and not self.mobile.running and self.sample is None:
            self.timer.stop()
            self._message('ComfyUI Control stopped.')
            self.finished.emit(self.exit_code)


def run(*, start_server, start_webui):
    if sys.platform != 'linux':
        print('ComfyUI Control currently supports Linux only.', file=sys.stderr)
        return 1
    path = config_path()
    app = QCoreApplication([sys.argv[0]])
    app.setApplicationName('ComfyUI Control')
    app.setApplicationVersion(__version__)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(path.parent / 'control.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            print('ComfyUI Control is already running for this user. Quit the desktop or terminal instance first.', file=sys.stderr)
            return 1
        config = Config.load(path)
        if not config.comfy_dir.strip() or not (config.directory / 'main.py').is_file():
            raise ValueError('Choose and configure your ComfyUI installation in the desktop app first, using this same Linux account.')
        if start_server:
            config.validate()
        settings = replace(MobileSettings.load(), enabled=start_webui) if start_webui else MobileSettings()
        if start_webui:
            settings.validate()
    except (OSError, ValueError) as exc:
        print(f'Could not start ComfyUI Control: {exc}', file=sys.stderr)
        return 1
    session = TerminalSession(config, settings, start_server=start_server, start_webui=start_webui)
    session.finished.connect(app.exit)
    handlers = {}
    def request_stop(signum, _frame):
        session.stop_signal = signum
    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, request_stop)
        QTimer.singleShot(0, session.start)
        return app.exec()
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        session.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        lock.unlock()
