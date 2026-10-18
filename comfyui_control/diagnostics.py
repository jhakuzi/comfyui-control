"""Bounded private crash history with conservative credential redaction."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from .config import config_path


def local_timestamp(value):
    """Display stored aware timestamps in the OS timezone, including its DST."""
    if not isinstance(value, str) or not value:
        return 'Unknown time'
    try:
        when = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
        if when.tzinfo is None:
            return value + ' (timezone unknown)'
        local = when.astimezone()
        offset = local.strftime('%z')
        return local.strftime('%Y-%m-%d %H:%M:%S %Z') + f' (UTC{offset[:3]}:{offset[3:]})'
    except (ValueError, OverflowError, OSError):
        return value


def redact(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    text = re.sub(r'(?i)(https?://)[^\s/@:]+:[^\s/@]+@', r'\1[redacted]@', text)
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+', r'\1[redacted]', text)
    pattern = r'''(?ix)((?<![\w.-])(?:--)?[\w.-]{0,128}(?:password|passwd|token|api[-_]?key|secret)[\w.-]{0,128}["']?\s*(?:[:=]|\s)\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;]+)'''
    return re.sub(pattern, r'\1[redacted]', text)


class CrashHistory:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_path().parent/'crashes.json'
        self.recent = ''
        try:
            entries = json.loads(self.path.read_text()) if self.path.stat().st_size <= 256000 else []
            self.entries = [entry for entry in entries[-5:] if isinstance(entry,dict) and isinstance(entry.get('diagnostic'),str)] if isinstance(entries,list) else []
        except (OSError, ValueError):
            self.entries = []

    def append(self, text):
        # Keep a small raw tail only in memory so patterns spanning QProcess
        # chunks can be redacted together before anything is written/exported.
        self.recent = (self.recent + text).encode('utf-8',errors='replace')[-32768:].decode('utf-8',errors='ignore')

    def record(self, code, status, command, directory, detail=''):
        timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        summary = f'ComfyUI exited unexpectedly (code {code}, {status}).'
        entry = dict(timestamp=timestamp,exit_code=code,exit_status=status,summary=summary,
            diagnostic=redact(f'{timestamp}\n{summary}\n{detail[:1024]}\nFolder: {str(directory)[:1024]}\nCommand: {command[:2048]}\n\nRecent output:\n{self.recent}'))
        self.entries = (self.entries + [entry])[-5:]
        self.save()
        return entry

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        data = json.dumps(self.entries,ensure_ascii=False)
        while len(data.encode('utf-8')) > 256000 and len(self.entries) > 1:
            self.entries.pop(0)
            data = json.dumps(self.entries,ensure_ascii=False)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent,prefix='.crash-')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as output:
                output.write(data)
            os.replace(temporary,self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def text(self, index=-1, *, local_time=False):
        if not self.entries:
            return 'No crash diagnostics have been recorded.'
        entry = self.entries[index]
        text = str(entry.get('diagnostic',''))
        timestamp = entry.get('timestamp')
        if local_time and isinstance(timestamp, str) and text.startswith(timestamp + '\n'):
            text = 'Local time: ' + local_timestamp(timestamp) + '\nRecorded timestamp: ' + timestamp + text[len(timestamp):]
        return redact(text)[:40000]
