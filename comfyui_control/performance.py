"""Sampling measurements from actual event/log observation times, never model-load time."""
import re
import time


class GenerationPerformance:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_average = None
        self.source = None
        self.last_event = None
        self._buffer = ''
        self.reset()

    def reset(self, prompt=None, started=None):
        self.prompt, self.started, self.ended = prompt, started, None
        self.status = 'running' if prompt else 'idle'
        self.node, self.value, self.total = None, None, None
        self.stage = 0
        self.last_time = self.last_value = self.current = None
        self.seconds, self.iterations = 0., 0
        self.stage_seconds, self.stage_iterations, self.samples = 0., 0, 0
        self.ambiguous = False
        self.elapsed_override = None
        self.pending_stage = True

    def segment(self, node=None):
        self.node = node
        self.stage += 1
        self.last_time = self.last_value = self.current = None
        self.value = self.total = None
        self.stage_seconds, self.stage_iterations, self.samples = 0., 0, 0
        self.pending_stage = False

    def progress(self, value, total, now, node=None):
        if type(value) not in (int, float) or type(total) not in (int, float) or not 0 <= value <= total or total <= 0:
            return
        if self.status != 'running':
            self.reset('observed', None)
        if self.pending_stage or self.stage == 0 or node is not None and node != self.node or self.last_value is not None and (value < self.last_value or total != self.total):
            self.segment(node)
        if self.last_value is not None and value > self.last_value and now > self.last_time:
            seconds, iterations = now - self.last_time, value - self.last_value
            self.current = seconds / iterations
            self.seconds += seconds
            self.iterations += iterations
            self.stage_seconds += seconds
            self.stage_iterations += iterations
            self.samples += 1
        if self.last_value is None or value != self.last_value:
            self.last_time, self.last_value = now, value
        self.value, self.total = value, total

    def finish(self, status, now=None):
        self.status = status
        self.ended = self.clock() if now is None else now
        self.current = None
        if status == 'complete' and self.iterations and not self.ambiguous:
            self.last_average = self.seconds / self.iterations

    def event(self, kind, data, now=None):
        now = self.clock() if now is None else now
        prompt = data.get('prompt_id')
        if kind == 'execution_start':
            if prompt != self.prompt or self.status != 'running':
                self.reset(prompt, now)
            self.source, self.last_event = 'events', now
        elif kind in {'progress', 'progress_state', 'executing', 'execution_success', 'execution_error', 'execution_interrupted'}:
            if prompt and prompt != self.prompt:
                self.reset(prompt, None)  # Joined after execution began: start time is unknown.
            self.source, self.last_event = 'events', now
            if kind == 'progress':
                self.progress(data.get('value'), data.get('max'), now, data.get('node', self.node))
            elif kind == 'progress_state':
                active = [(key, node) for key, node in data.get('nodes', {}).items()
                          if node.get('state') == 'running' and node.get('max', 0) > 0]
                if len(active) == 1:
                    key, node = active[0]
                    self.progress(node.get('value'), node.get('max'), now, key)
                elif len(active) > 1:
                    self.ambiguous = True
                    self.current = None
            elif kind == 'executing' and data.get('node') is not None and data['node'] != self.node:
                self.node = data['node']
                self.pending_stage = True
                self.current = self.last_time = self.last_value = None
                self.value = self.total = None
                self.stage_seconds, self.stage_iterations, self.samples = 0., 0, 0
            elif kind in {'execution_success', 'execution_error', 'execution_interrupted'}:
                self.finish({'execution_success':'complete','execution_error':'failed','execution_interrupted':'cancelled'}[kind], now)

    def output(self, text):
        now = self.clock()
        # Other ComfyUI browser clients receive their own private progress
        # events. Their sampler's CLI reports are a read-only fallback for the
        # process we own; don't compete with fresh WebSocket measurements.
        if self.last_event is not None and now - self.last_event < 3:
            self._buffer = ''
            return
        self._buffer = (self._buffer + text)[-65536:]
        lines = re.split(r'[\r\n]', self._buffer)
        self._buffer = lines.pop()
        pending = None
        for line in lines:
            if not re.search(r'(?:s/(?:it|steps)|(?:it|steps)/s)', line):
                progress_line = ''
            else:
                progress_line = line
            match = re.search(r'(?:Node ([\w.-]+):.*?)?\d+%.*?\|\s*(\d+)/(\d+)\s*\[', progress_line)
            if match:
                self.source = 'process output'
                sample = (int(match[2]), int(match[3]), match[1])
                if pending and (sample[0] < pending[0] or sample[1:] != pending[1:]):
                    self.progress(pending[0], pending[1], now, pending[2])
                # Several terminal updates can arrive in one read. Only the
                # latest count has an observation time; don't attribute the
                # whole interval to the first iteration in that batch.
                pending = sample
            elapsed = re.search(r'Prompt executed in ([\d.]+) seconds', line)
            interrupted = re.search(r'Processing interrupted|Interrupting prompt', line, re.I)
            if pending and (elapsed or interrupted):
                self.progress(pending[0], pending[1], now, pending[2])
                pending = None
            if elapsed:
                self.elapsed_override = float(elapsed[1])
                self.finish('complete', now)
            if interrupted:
                self.finish('cancelled', now)
        if pending:
            self.progress(pending[0], pending[1], now, pending[2])

    def disconnect(self):
        # A socket gap cannot be treated as a measured sampling interval.
        self.last_time = self.last_value = self.current = None
        self.stage_seconds, self.stage_iterations, self.samples = 0., 0, 0

    def snapshot(self):
        elapsed = self.elapsed_override
        if elapsed is None and self.started is not None:
            elapsed = max(0, (self.ended if self.ended is not None else self.clock()) - self.started)
        average = self.seconds / self.iterations if self.iterations and not self.ambiguous else None
        eta = None
        if self.status == 'running' and self.samples >= 2 and self.stage_iterations and not self.ambiguous:
            eta = max(0, self.total - self.value) * self.stage_seconds / self.stage_iterations
        return dict(status=self.status, current=self.current if not self.ambiguous else None,
                    average=average, elapsed=elapsed, value=self.value, total=self.total,
                    remaining=eta, last_average=self.last_average, stage=self.stage, source=self.source)
