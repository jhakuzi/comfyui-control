import json
import os
import time

import pytest

from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from comfyui_control.diagnostics import CrashHistory, local_timestamp, redact
from comfyui_control.recovery_widgets import CrashDialog, RecoverySettings
from comfyui_control.config import Config


def test_redaction_handles_split_output_and_private_bounded_history(tmp_path):
    history=CrashHistory(tmp_path/'history.json')
    history.append('x'*50000+'\nAPI_TO')
    history.append('KEN=very-secret\nAuthorization: Bearer auth-secret\n')
    history.append('https://user:pass@example.invalid/\n--password "two words"\n')
    for i in range(8): history.record(i,'NormalExit','python --api-key=command-secret',tmp_path)
    text=history.path.read_text()
    for value in ('very-secret','auth-secret','user:pass','two words','command-secret'):
        assert value not in text
    assert '[redacted]' in text and len(history.recent)<=32768
    assert len(history.entries)==5 and history.path.stat().st_size<=256000
    assert history.path.stat().st_mode & 0o777==0o600
    loaded=CrashHistory(history.path)
    assert loaded.entries[0]['exit_code']==3
    assert 'Folder:' in loaded.text() and 'Command:' in loaded.text()
    assert redact('GPU 45% temperature 50°C')=='GPU 45% temperature 50°C'


def test_corrupt_and_oversize_history_ignored(tmp_path):
    path=tmp_path/'history.json'
    path.write_text('{bad json')
    assert not CrashHistory(path).entries
    path.write_text('x'*256001)
    assert not CrashHistory(path).entries
    path.write_text(json.dumps([{},None,{'diagnostic':'okay'}]))
    assert len(CrashHistory(path).entries)==1


def test_unicode_and_control_character_logs_stay_byte_bounded(tmp_path):
    history=CrashHistory(tmp_path/'history.json')
    history.append('🙂'*32768)
    assert len(history.recent.encode('utf-8'))<=32768
    history.append('\x00'*32768)
    for i in range(6): history.record(i,'NormalExit','python main.py',tmp_path)
    assert history.path.stat().st_size<=256000
    assert CrashHistory(history.path).entries[-1]['exit_code']==5


def test_diagnostics_copy_export_and_recovery_safe_defaults(app,tmp_path,monkeypatch):
    history=CrashHistory(tmp_path/'history.json')
    history.append('TOKEN=hide-me\nuseful failure')
    history.record(7,'NormalExit','python main.py',tmp_path)
    dialog=CrashDialog(history)
    assert 'useful failure' in dialog.text.toPlainText()
    assert 'hide-me' not in dialog.text.toPlainText()
    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Copy diagnostics').click()
    assert QApplication.clipboard().text()==dialog.text.toPlainText()
    export=tmp_path/'export.txt'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:(str(export),''))
    dialog._export()
    assert export.read_text()==dialog.text.toPlainText()
    assert export.stat().st_mode & 0o777==0o600
    preferences=RecoverySettings(Config())
    assert not preferences.enabled.isChecked() and not preferences.limit.isEnabled()
    preferences.enabled.setChecked(True)
    assert preferences.limit.isEnabled() and preferences.backoff.isEnabled()


@pytest.mark.parametrize('stamp,expected', [
    ('2026-10-18T12:34:56+00:00', '2026-10-18 14:34:56 CEST (UTC+02:00)'),
    ('2026-01-18T12:34:56+00:00', '2026-01-18 13:34:56 CET (UTC+01:00)'),
    ('2026-10-25T00:30:00Z', '2026-10-25 02:30:00 CEST (UTC+02:00)'),
    ('2026-10-25T01:30:00Z', '2026-10-25 02:30:00 CET (UTC+01:00)'),
])
def test_crash_view_uses_system_timezone_for_old_entries_without_changing_storage(app, tmp_path, monkeypatch, stamp, expected):
    original_tz = os.environ.get('TZ')
    monkeypatch.setenv('TZ', 'Europe/Berlin')
    time.tzset()
    try:
        history = CrashHistory(tmp_path / 'history.json')
        history.entries = [dict(timestamp=stamp, exit_code=7, diagnostic=stamp + '\nOriginal failure\nTOKEN=hide-me')]
        history.save()
        stored = history.path.read_bytes()
        assert local_timestamp(stamp) == expected
        dialog = CrashDialog(history)
        assert expected in dialog.entries.currentText()
        assert dialog.text.toPlainText().startswith('Local time: ' + expected)
        assert 'Recorded timestamp: ' + stamp in dialog.text.toPlainText()
        assert 'hide-me' not in dialog.text.toPlainText()
        assert history.path.read_bytes() == stored
        assert history.text().startswith(stamp + '\n')
    finally:
        if original_tz is None:
            monkeypatch.delenv('TZ', raising=False)
        else:
            monkeypatch.setenv('TZ', original_tz)
        time.tzset()


def test_unknown_or_legacy_timestamp_is_not_given_an_invented_timezone():
    assert local_timestamp(None) == 'Unknown time'
    assert local_timestamp('bad timestamp') == 'bad timestamp'
    assert local_timestamp('2026-10-18T12:00:00') == '2026-10-18T12:00:00 (timezone unknown)'
