"""Bounded disposable workers, without waiting on a stuck network filesystem."""
import asyncio
import json
import subprocess
import tempfile
import threading
import time


class BackgroundProcess:
    abandoned = []
    slots = threading.BoundedSemaphore(4)
    lock = threading.Lock()

    def __init__(self, command, data=None, timeout=12, limit=101 * 1024 * 1024):
        with self.lock:
            for job in list(self.abandoned):
                if job.process.poll() is not None:
                    job._release_slot()
                    self.abandoned.remove(job)
        if not self.slots.acquire(blocking=False):
            raise OSError('Network operations are busy or still blocked. Wait for the server to recover before retrying.')
        self.slot_held = True
        self.limit = limit
        self.deadline = time.monotonic() + timeout
        self.output = self.input = None
        try:
            self.output = tempfile.TemporaryFile(dir='/tmp')
            self.input = tempfile.TemporaryFile(dir='/tmp')
            self.input.write(json.dumps(data).encode())
            self.input.seek(0)
            self.process = subprocess.Popen(command, stdin=self.input, stdout=self.output,
                                            stderr=subprocess.STDOUT, start_new_session=True)
        except (OSError, ValueError, TypeError):
            if self.input:
                self.input.close()
            if self.output:
                self.output.close()
            self._release_slot()
            raise

    def _release_slot(self):
        if self.slot_held:
            self.slot_held = False
            self.slots.release()

    def poll(self):
        code = self.process.poll()
        if code is None:
            if time.monotonic() >= self.deadline:
                self.cancel()
                raise TimeoutError('The network operation timed out.')
            return None
        self.output.seek(0)
        data = self.output.read(self.limit + 1)
        self.input.close(); self.output.close()
        self._release_slot()
        if len(data) > self.limit:
            raise ValueError('Network response is too large.')
        if code:
            try:
                error = json.loads(data)
                if error.get('missing'):
                    raise FileNotFoundError(error['error'])
                message = error.get('error', 'Network operation failed.')
            except (ValueError, AttributeError):
                message = data.decode(errors='replace')[-2000:] or 'Network operation failed or authorization was cancelled.'
            raise OSError(message)
        return data

    def cancel(self):
        if self.process.poll() is None:
            try:
                self.process.kill()
            except (PermissionError, ProcessLookupError):
                pass
            with self.lock:
                if self not in self.abandoned:
                    self.abandoned.append(self)
        else:
            self._release_slot()
        self.input.close(); self.output.close()


async def run_background(command, data=None, timeout=8):
    job = BackgroundProcess(command, data, timeout)
    try:
        while True:
            # Large completed image spools are local, but reading them still
            # belongs off the HTTP event loop. Pending polls remain trivial.
            result = job.poll() if job.process.poll() is None else await asyncio.to_thread(job.poll)
            if result is not None:
                return result
            await asyncio.sleep(.05)
    except BaseException:
        job.cancel()
        raise
