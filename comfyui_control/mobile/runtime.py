"""Qt bridge owning the embedded server's single background event-loop thread."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

from aiohttp import web
from PySide6.QtCore import QObject, Signal, Slot

from .server import MobileHTTP
from .service import MobileService
from .settings import MobileSettings, data_dir


class MobileRuntime(QObject):
    changed = Signal(str, str)
    stopped = Signal()

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
        self.stop_requested = threading.Event()
        self.stopped.connect(self._finished)

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def configure(self, settings, config, state="stopped"):
        if self.running:
            if self.settings == settings and not self.stop_requested.is_set():
                self.update_desktop(config, state)
                return
            self.pending = (replace(settings), replace(config), state)
            self.stop()
            return
        self.settings = replace(settings)
        if not settings.enabled:
            self._status("Disabled", "")
            return
        try:
            settings.validate()
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
        self.service = MobileService(data_dir(), settings, config.folder("output"), state)
        runner = web.AppRunner(MobileHTTP(self.service).app(), access_log=None, shutdown_timeout=1)
        await runner.setup()
        try:
            site = web.TCPSite(runner, settings.bind, settings.port)
            await site.start()
            await self.service.start()
            self._status("Listening", settings.url())
            if self.stop_requested.is_set():
                self.stop_event.set()
            await self.stop_event.wait()
        finally:
            await self.service.stop()
            await runner.cleanup()
        self._status("Disabled", "")

    def update_desktop(self, config, state):
        def update():
            if self.service:
                output = config.folder("output").resolve()
                if self.service.output_dir != output:
                    self.service.change_output(output)
                self.service.desktop_state = state
                self.service.broadcast()
        loop = self.loop
        if loop and loop.is_running():
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
