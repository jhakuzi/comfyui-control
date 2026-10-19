"""Shared Qt Core hardware sampling worker; never requires a desktop session."""
from PySide6.QtCore import QObject, QRunnable, Signal


class SampleSignals(QObject):
    finished = Signal(object)


class Sample(QRunnable):
    def __init__(self, reader, pid):
        super().__init__()
        self.reader, self.pid = reader, pid
        self.signals = SampleSignals()

    def run(self):
        try:
            value = self.reader.sample(self.pid)
        except Exception:
            value = dict(cpu=None, ram_used=None, ram_total=None, process_memory=None, gpus=[])
        try:
            self.signals.finished.emit(value)
        except RuntimeError:
            pass
