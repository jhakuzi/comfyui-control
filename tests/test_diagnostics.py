import json
import os

from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from comfyui_control.diagnostics import CrashHistory, redact
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
