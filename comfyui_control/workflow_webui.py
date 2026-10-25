"""Asynchronous ComfyUI readiness and explicit start-before-browser flow."""
import json
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest


class WorkflowWebUI(QObject):
    status = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, url, *, state, start, confirm, open_url, parent=None,
                 wait_seconds=120, retry_ms=750, request_ms=2000):
        super().__init__(parent)
        self.url = QUrl(url)
        self.state, self.start, self.confirm, self.open_url = state, start, confirm, open_url
        self.wait_seconds, self.retry_ms, self.request_ms = wait_seconds, retry_ms, request_ms
        alive = self._alive = {'value': True}
        self.destroyed.connect(lambda: alive.update(value=False))
        self.manager = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._probe)
        self.reply = None
        self.busy = False
        self.waiting = False
        self.epoch = 0
        self.deadline = 0

    def open(self):
        if self.busy: return
        if self.url.scheme() not in ('http', 'https') or not self.url.host():
            self.status.emit('Check the ComfyUI address in Mobile WebUI settings.')
            return
        self.epoch += 1
        self.waiting = False
        self.initial_state = self.state()
        self.busy = True
        self.busy_changed.emit(True)
        self.status.emit('Checking whether ComfyUI is ready…')
        self._probe()

    def _probe(self):
        if not self.busy: return
        if self.waiting:
            if self.state() not in {'starting', 'running', 'restarting'}:
                self._finish('ComfyUI did not start or has stopped. Check the desktop output, then try again.')
                return
            if time.monotonic() >= self.deadline:
                self._finish('ComfyUI is not ready yet. Check the desktop output and ComfyUI address, then try again.')
                return
        url = QUrl(self.url)
        url.setPath(url.path().rstrip('/') + '/system_stats')
        url.setQuery(None); url.setFragment(None)
        request = QNetworkRequest(url)
        request.setTransferTimeout(self.request_ms)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self.reply = self.manager.get(request)
        reply.setReadBufferSize(65537)
        epoch = self.epoch
        alive = self._alive
        reply.finished.connect(lambda: self._checked(reply, epoch) if alive['value'] else None)

    def _checked(self, reply, epoch):
        if epoch != self.epoch or not self.busy:
            reply.deleteLater()
            return
        self.reply = None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        reply.deleteLater()
        current_state = self.state()
        if current_state == 'unavailable':
            self._finish('The selected installation or operation changed. Check the desktop app, then try again.')
            return
        if (self.waiting or self.initial_state in {'starting', 'running', 'restarting'}) and current_state not in {'starting', 'running', 'restarting'}:
            self._finish('ComfyUI did not start or has stopped. Check the desktop output, then try again.')
            return
        ready = False
        if status == 200 and len(raw) <= 65536:
            try:
                data = json.loads(raw)
                ready = isinstance(data, dict) and isinstance(data.get('system'), dict) and isinstance(data.get('devices'), list)
            except (ValueError, TypeError): pass
        if ready:
            self._finish('ComfyUI is ready. Opening its WebUI…')
            if not self.open_url(self.url):
                self.status.emit('Could not open the browser. Open the regular ComfyUI address manually.')
            return
        if status is not None and status < 500:
            self._finish('The address responded, but ComfyUI readiness could not be verified. Check its address in Mobile WebUI settings.')
            return
        if not self.waiting:
            state = self.state()
            if state in {'stopped', 'crashed'}:
                if self.start is None:
                    self._finish('Start ComfyUI from the desktop app, then try again.')
                    return
                if not self.confirm():
                    self._finish('ComfyUI was not started.')
                    return
                if epoch != self.epoch or not self.busy: return
                if self.start() is False or self.state() not in {'starting', 'running', 'restarting'}:
                    self._finish('ComfyUI could not be started. Check the desktop output and launch settings.')
                    return
            elif state not in {'starting', 'running', 'restarting'}:
                self._finish('Wait for the current ComfyUI operation to finish, then try again.')
                return
            self.waiting = True
            self.deadline = time.monotonic() + self.wait_seconds
            self.status.emit('Waiting for ComfyUI to become ready, then opening its WebUI…')
        self.timer.start(self.retry_ms)

    def _finish(self, message):
        self.cancel()
        self.status.emit(message)

    def cancel(self):
        self.epoch += 1
        self.timer.stop()
        reply, self.reply = self.reply, None
        self.busy = False
        if reply is not None: reply.abort()
        self.busy_changed.emit(False)
