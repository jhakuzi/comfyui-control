from dataclasses import replace
import socket
import time
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from comfyui_control.app import MainWindow, SettingsDialog
from comfyui_control.config import Config
from comfyui_control.mobile.runtime import MobileRuntime
from comfyui_control.mobile.settings import MobileSettings, check_password, password_hash
from comfyui_control.mobile_widgets import MobileDialog


def test_mobile_dialog_url_qr_and_password_storage(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    runtime = MobileRuntime()
    dialog = MobileDialog(runtime, Config())
    dialog.bind.setText('0.0.0.0')
    dialog.advertised.setText('phone-vpn.example')
    dialog.port.setValue(18301)
    dialog._preview()
    first = dialog.qr.pixmap().cacheKey()
    assert dialog.current_url == 'http://phone-vpn.example:18301/'
    dialog.port.setValue(18302)
    dialog._preview()
    assert dialog.current_url == 'http://phone-vpn.example:18302/'
    assert dialog.qr.pixmap().cacheKey() != first
    dialog.password.setText('a private test password')
    with patch.object(runtime, 'configure') as configure:
        dialog._apply()
        configure.assert_called_once()
    saved = MobileSettings.load()
    assert check_password('a private test password', saved.password)
    assert saved.password not in dialog.current_url
    assert 'a private test password' not in (tmp_path/'comfyui-control/mobile/settings.json').read_text()
    dialog.close()


def test_launch_settings_keep_mobile_preferences(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path/'config'))
    settings = MobileSettings(advertised='my-vpn.example', password=password_hash('private test password'))
    settings.save()
    (tmp_path/'main.py').touch()
    dialog = SettingsDialog(Config(comfy_dir=str(tmp_path)))
    dialog.arguments.setPlainText('--cpu')
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert MobileSettings.load() == settings
    dialog.close()


def test_automatic_mobile_start_and_window_shutdown(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    MobileSettings(enabled=True, port=port, require_auth=False).save()
    window = MainWindow(Config())
    window.show()
    end = time.monotonic() + 5
    while window.mobile.status != 'Listening' and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert window.mobile.status == 'Listening'
    with patch.object(window.controller, 'start') as start, patch.object(window.controller, 'restart') as restart:
        dialog = MobileDialog(window.mobile, window.controller.config, window)
        dialog.show()
        app.processEvents()
        dialog.close()
        start.assert_not_called()
        restart.assert_not_called()
    window.close()
    end = time.monotonic() + 5
    while window.mobile.running and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert not window.mobile.running
    assert window.controller.state == 'stopped'
