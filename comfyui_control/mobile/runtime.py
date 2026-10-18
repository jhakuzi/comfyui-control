"""Qt bridge owning the embedded server's single background event-loop thread."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time

from aiohttp import web
from PySide6.QtCore import QObject, Signal, Slot

from .server import MobileHTTP
from .service import MobileService
from .settings import MobileSettings, data_dir


class MobileRuntime(QObject):
    changed = Signal(str, str)
    stopped = Signal()
    execution = Signal(str, object, float)
    monitoring_requested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.loop = None
        self.stop_event = None
        self.service = None
        self.settings = MobileSettings()
        self.status = "Disabled"
        self.url = ""
        self.pending = None
        self.observing = False
        self.stop_requested = threading.Event()
        self.stopped.connect(self._finished)

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def configure(self, settings, config, state="stopped", observe=None):
        if observe is not None:
            self.observing = observe
        if self.running:
            if self.settings == settings and (settings.enabled or self.observing) and not self.stop_requested.is_set():
                self.update_desktop(config, state)
                return
            self.pending = (replace(settings), replace(config), state)
            self.stop()
            return
        self.settings = replace(settings)
        if not settings.enabled and not self.observing:
            self._status("Disabled", "")
            return
        try:
            settings.validate(require_password=settings.enabled)
        except ValueError as exc:
            self._status("Not started: " + str(exc), "")
            return
        self.stop_requested.clear()
        self._status("Starting…", "")
        self.thread = threading.Thread(target=self._run, args=(replace(settings), replace(config), state), name="comfyui-mobile", daemon=True)
        self.thread.start()

    def _status(self, status, url):
        self.status, self.url = status, url
        try:
            self.changed.emit(status, url)
        except RuntimeError:
            pass

    def _run(self, settings, config, state):
        try:
            asyncio.run(self._serve(settings, config, state))
        except Exception as exc:
            self._status("Could not start Mobile WebUI: " + str(exc), "")
        finally:
            self.loop = self.stop_event = self.service = None
            try:
                self.stopped.emit()
            except RuntimeError:
                pass

    async def _serve(self, settings, config, state):
        self.loop = asyncio.get_running_loop()
        self.loop.set_default_executor(ThreadPoolExecutor(max_workers=2, thread_name_prefix="comfy-mobile-io"))
        self.stop_event = asyncio.Event()
        self.service = MobileService(data_dir(), settings, config.folder("output"), state, self._execution, self._monitoring,
                                     network_output=config.session_network_output)
        runner = None
        if settings.enabled:
            runner = web.AppRunner(MobileHTTP(self.service).app(), access_log=None, shutdown_timeout=1)
            await runner.setup()
        try:
            if runner:
                site = web.TCPSite(runner, settings.bind, settings.port)
                await site.start()
            await self.service.start()
            self._status("Listening" if runner else "Disabled", settings.url() if runner else "")
            if self.stop_requested.is_set():
                self.stop_event.set()
            await self.stop_event.wait()
        finally:
            await self.service.stop()
            if runner:
                await runner.cleanup()
        self._status("Disabled", "")

    def _execution(self, kind, data, when):
        if self.observing:
            try:
                self.execution.emit(kind, data, when)
            except RuntimeError:
                pass

    def _monitoring(self, enabled):
        try:
            self.monitoring_requested.emit(enabled)
        except RuntimeError:
            pass

    def update_desktop(self, config, state):
        def update():
            if self.service:
                output = config.folder("output")
                if not config.session_network_output:
                    output = output.resolve()
                if self.service.output_dir != output or self.service.network_output != config.session_network_output:
                    self.service.change_output(output, network_output=config.session_network_output)
                self.service.desktop_state = state
                self.service.broadcast()
        loop = self.loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(update)
            except RuntimeError:
                pass

    def publish_hardware(self, metrics):
        # Reuse the Qt sampler; never run another nvidia-smi/ROCm reader here.
        gpus = metrics.get('gpus', [])
        primary = max(gpus, key=lambda g: (g.get('utilization') if g.get('utilization') is not None else -1, g.get('vram_used') or 0)) if gpus else {}
        sample = {key: primary.get(key) for key in ('utilization', 'vram_used')}
        loop = self.loop
        if loop and loop.is_running():
            def update():
                if self.service:
                    self.service.update_hardware(sample)
            try:
                loop.call_soon_threadsafe(update)
            except RuntimeError:
                pass

    def stop(self):
        self.pending = None if getattr(self.parent(), "_closing", False) else self.pending
        self.stop_requested.set()
        loop, event = self.loop, self.stop_event
        if loop and event and loop.is_running():
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass

    @Slot()
    def _finished(self):
        if self.pending:
            pending, self.pending = self.pending, None
            # Signal is emitted just before the Python thread returns.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(20, lambda: self.configure(*pending))
