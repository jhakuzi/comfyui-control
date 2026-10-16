"""Compact Qt monitoring, with at most one background hardware sample in flight."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout, QWidget

from .hardware import HardwareReader
from .performance import GenerationPerformance


def scalar(value, suffix='', digits=1):
    return '--' if value is None else f'{value:.{digits}f}{suffix}'


def memory(used, total=None):
    if used is None:
        return '--'
    text = f'{used / 1024**3:.1f}'
    return text + (f' / {total / 1024**3:.1f} GiB' if total else ' GiB')


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


class MonitorPanel(QWidget):
    expanded_changed = Signal(bool)
    observation_changed = Signal(bool)

    def __init__(self, controller, config, parent=None, reader=None):
        super().__init__(parent)
        self.controller, self.config = controller, config
        self.reader = reader or HardwareReader()
        self.performance = GenerationPerformance()
        self.worker = None
        self.enabled = config.monitoring_enabled
        self.last_observing = False
        self.metrics = dict(cpu=None, ram_used=None, ram_total=None, process_memory=None, gpus=[])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(config.monitor_expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setSizePolicy(self.sizePolicy())
        layout.addWidget(self.toggle)
        self.details = QWidget()
        form = QFormLayout(self.details)
        form.setContentsMargins(8, 2, 0, 0)
        self.hardware = QLabel()
        self.hardware.setTextFormat(Qt.TextFormat.PlainText)
        self.hardware.setWordWrap(True)
        self.utilization = QProgressBar()
        self.utilization.setRange(0, 100)
        self.utilization.setFixedHeight(5)
        self.utilization.setTextVisible(False)
        self.timing = QLabel()
        self.timing.setTextFormat(Qt.TextFormat.PlainText)
        self.timing.setWordWrap(True)
        form.addRow('Hardware', self.hardware)
        form.addRow('', self.utilization)
        form.addRow('Generation', self.timing)
        layout.addWidget(self.details)
        self.toggle.toggled.connect(self._expanded)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        controller.changed.connect(self.state_changed)
        controller.output.connect(self.performance.output)
        self._expanded(config.monitor_expanded, save=False)
        self.setVisible(self.enabled)

    def configure(self, config):
        self.config, self.enabled = config, config.monitoring_enabled
        self.setVisible(self.enabled)
        self._activity()

    def _expanded(self, expanded, save=True):
        self.details.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if save:
            self.expanded_changed.emit(expanded)
        self._activity()
        self.render()

    def state_changed(self, state):
        if state in {'stopped', 'crashed', 'restarting'} and self.performance.status == 'running':
            self.performance.finish('interrupted')
        self._activity()
        self.render()

    def showEvent(self, event):
        super().showEvent(event)
        self._activity()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._activity()

    def _activity(self):
        active = self.enabled and self.isVisible() and not self.window().isMinimized() and (self.toggle.isChecked() or self.controller.state in {'starting','running'})
        observing = active and self.controller.state in {'starting','running'}
        if observing != self.last_observing:
            if not observing:
                self.performance.disconnect()
            self.last_observing = observing
            self.observation_changed.emit(observing)
        if active and not self.timer.isActive():
            self.reader.reset()
            self.timer.start()
            self.tick()
        elif not active:
            self.timer.stop()

    def tick(self):
        self.render()
        if self.worker or not self.timer.isActive():
            return
        pid = self.controller._pid if getattr(self.controller, '_kind', '') == 'server' else 0
        self.worker = Sample(self.reader, pid)
        self.worker.signals.finished.connect(self._sampled)
        QThreadPool.globalInstance().start(self.worker)

    def _sampled(self, value):
        self.worker = None
        self.metrics = value
        self.render()

    def execution(self, kind, data, when):
        if kind == 'disconnected':
            self.performance.disconnect()
        else:
            self.performance.event(kind, data, when)
        self.render()

    def render(self):
        stats = self.performance.snapshot()
        gpus = self.metrics['gpus']
        brief = ['System && generation']  # QToolButton treats a single & as a mnemonic.
        primary = max(gpus, key=lambda g: (g['utilization'] if g['utilization'] is not None else -1, g['vram_used'] or 0)) if gpus else None
        for gpu in [primary] if primary else []:
            brief.append(f"GPU {scalar(gpu['utilization'], '%', 0)} · VRAM {memory(gpu['vram_used'], gpu['vram_total'])}")
        if not gpus:
            brief.append('GPU -- · VRAM --')
        brief.append(scalar(stats['current'], ' s/it'))
        self.toggle.setText('  |  '.join(brief))
        self.toggle.setToolTip('Hardware metrics are read without root. Sampling uses observed progress intervals, excluding model loading. Expand for details.')
        lines = []
        for gpu in gpus:
            lines.append(f"{gpu['name']}: {scalar(gpu['utilization'], '%', 0)} · VRAM {memory(gpu['vram_used'], gpu['vram_total'])} · {scalar(gpu['temperature'], ' °C')} · {scalar(gpu['power'], ' W')}")
        lines.extend([f"CPU {scalar(self.metrics['cpu'], '%', 0)} · RAM {memory(self.metrics['ram_used'], self.metrics['ram_total'])}",
                      f"ComfyUI process-group RSS {memory(self.metrics['process_memory'])}"])
        self.hardware.setText('\n'.join(lines))
        self.hardware.setToolTip('Process-group RSS includes owned children; shared pages can be counted more than once. -- means unavailable.')
        uses = [g['utilization'] for g in gpus if g['utilization'] is not None]
        self.utilization.setVisible(bool(uses) and self.toggle.isChecked())
        if uses:
            self.utilization.setValue(round(max(uses)))
        self.timing.setText(f"Current {scalar(stats['current'], ' s/it')} · Average {scalar(stats['average'], ' s/it')}\n"
            f"Elapsed {scalar(stats['elapsed'], ' s')} · Iterations {scalar(stats['value'], digits=0)} / {scalar(stats['total'], digits=0)} · Stage {stats['stage'] or '--'}\n"
            f"Sampling ETA {scalar(stats['remaining'], ' s')} · Last completed {scalar(stats['last_average'], ' s/it')}")

    def stop(self):
        self.enabled = False
        self._activity()
