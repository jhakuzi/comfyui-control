"""Tray choices and lifecycle checks; the native desktop tray host is simulated."""
import json
from dataclasses import replace
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import patch
import urllib.request

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

from comfyui_control.app import MainWindow, SettingsDialog
from comfyui_control.config import Config
from comfyui_control.mobile.settings import MobileSettings


def wait(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Lifecycle operation did not finish'


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: True))
    # Offscreen Qt has no native tray. Exercise real Qt actions/dialogs while
    # avoiding a platform-native show call that this plugin cannot implement.
    monkeypatch.setattr(QSystemTrayIcon, 'show', lambda self: None)
    (tmp_path / 'main.py').touch()
    widget = MainWindow(Config(comfy_dir=str(tmp_path), python=sys.executable,
                               monitoring_enabled=False, auto_restart=True))
    widget.show()
    QTest.qWait(10)
    yield widget
    widget._closing = True
    widget.controller.shutdown()
    widget.mobile.stop()
    wait(lambda: widget.controller.process is None and not widget.mobile.running)
    widget.close()


@pytest.mark.parametrize('button,expected', [('Keep in tray', 'tray'), ('Quit', 'quit'), ('Cancel', 'cancel')])
def test_close_dialog_choices_and_safe_defaults(window, button, expected):
    def choose(dialog):
        assert dialog.defaultButton().text() == 'Keep in tray'
        assert dialog.escapeButton() == dialog.button(QMessageBox.StandardButton.Cancel)
        assert 'keep running' in dialog.informativeText()
        next(item for item in dialog.buttons() if item.text().replace('&', '') == button).click()
    with patch.object(QMessageBox, 'exec', choose):
        assert window._close_choice() == expected


def test_update_close_dialog_explains_cancellation(window):
    window.controller.state = 'updating'
    def choose(dialog):
        assert 'cancels the update' in dialog.informativeText()
        dialog.reject()  # Window-manager close/dismissal means Cancel.
    with patch.object(QMessageBox, 'exec', choose):
        assert window._close_choice() == 'cancel'
    window.controller.state = 'stopped'


def test_hide_cancel_restore_and_tray_menu_do_not_shutdown(window):
    window.controller.state = 'running'
    window._state_changed('running')
    assert 'Process running' in window.tray.toolTip()
    assert not window.tray.icon().isNull()
    with patch.object(window.controller, 'shutdown') as shutdown, patch.object(window.mobile, 'stop') as mobile_stop:
        with patch.object(window, '_close_choice', return_value='cancel'):
            assert not window.close() and window.isVisible()
        assert not window._closing
        with patch.object(window, '_close_choice', return_value='tray'):
            assert not window.close() and not window.isVisible()
        assert window.tray_watch.isActive() and not window._closing
        window.tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
        assert not window.isVisible()
        window.tray_open.trigger()
        assert window.isVisible() and not window.tray_watch.isActive()
        window.hide()
        window.setWindowState(Qt.WindowState.WindowMinimized)
        window.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        assert window.isVisible() and not window.isMinimized()
        window.hide()
        window.tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert window.isVisible()
        shutdown.assert_not_called()
        mobile_stop.assert_not_called()
    window.controller.state = 'stopped'


def test_disappearing_tray_host_restores_hidden_window(window, monkeypatch):
    with patch.object(window, '_close_choice', return_value='tray'):
        window.close()
    assert not window.isVisible()
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: False))
    window.tray_watch.timeout.emit()
    assert window.isVisible() and not window.tray_watch.isActive()
    with patch.object(window, '_close_choice') as choice:
        assert window.close()
        choice.assert_not_called()


def test_lost_host_while_dialog_open_never_hides_the_window(window, monkeypatch):
    def disappeared():
        monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: False))
        return 'tray'
    with patch.object(window, '_close_choice', side_effect=disappeared):
        assert not window.close()
    assert window.isVisible() and not window._closing


def test_idle_quit_from_hidden_tray_emits_application_exit(window):
    finished = QSignalSpy(window.closed)
    with patch.object(window, '_close_choice', return_value='tray'):
        window.close()
    with patch.object(window, '_close_choice') as choice, patch('comfyui_control.app.QMessageBox.question') as confirm:
        window.tray_quit.trigger()
        choice.assert_not_called()
        confirm.assert_not_called()
    assert finished.count() == 1
    assert window._closing and not window.tray_watch.isActive()


def test_cancel_quit_from_tray_preserves_hidden_running_state(window):
    window.controller.state = 'running'
    with patch.object(window, '_close_choice', return_value='tray'):
        window.close()
    with patch('comfyui_control.app.QMessageBox.question', return_value=QMessageBox.StandardButton.No), patch.object(window.controller, 'shutdown') as shutdown:
        window.tray_quit.trigger()
        shutdown.assert_not_called()
    assert not window.isVisible() and window.tray_watch.isActive()
    assert not window._closing and not window._tray_quit_requested
    window.controller.state = 'stopped'


def test_quit_choice_uses_existing_shutdown_without_second_dialog(window):
    window.controller.state = 'running'
    with patch.object(window, '_close_choice', return_value='quit'), patch.object(window.controller, 'shutdown') as shutdown, patch('comfyui_control.app.QMessageBox.question') as question:
        assert not window.close()
        shutdown.assert_called_once()
        question.assert_not_called()
    assert window._closing and not window.tray_quit.isEnabled()
    window.controller.state = 'stopped'


def test_hidden_server_and_mobile_keep_running_then_quit_cleans_up_children(window, tmp_path):
    child_file = tmp_path / 'child.pid'
    (tmp_path / 'main.py').write_text(
        'import subprocess, sys, time\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])\n'
        f'open({str(child_file)!r}, "w").write(str(child.pid))\n'
        'print("server ready", flush=True)\nwhile True: time.sleep(.1)\n')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    MobileSettings(enabled=True, require_auth=False, port=port, comfy_url='http://127.0.0.1:9').save()
    window._start_mobile()
    window.controller.start()
    wait(lambda: child_file.exists() and window.mobile.status == 'Listening')
    child = int(child_file.read_text())
    pid = window.controller._pid
    mobile_thread = window.mobile.thread
    finished = QSignalSpy(window.closed)
    with patch.object(window, '_close_choice', return_value='tray'):
        assert not window.close()
    QTest.qWait(30)
    assert not window.isVisible() and not window._closing
    assert window.controller.state == 'running' and window.controller._pid == pid
    assert window.mobile.thread is mobile_thread
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/session', timeout=3) as response:
        assert json.load(response)['authenticated'] is True
    window.tray_open.trigger()
    assert window.isVisible() and window.controller._pid == pid
    assert window.mobile.thread is mobile_thread
    with patch.object(window, '_close_choice', return_value='tray'):
        window.close()
    with patch('comfyui_control.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        window.tray_quit.trigger()
    wait(lambda: finished.count() == 1)
    assert window.controller.process is None and not window.mobile.running
    assert not window.controller._recovery_timer.isActive()
    assert 'Process and its children successfully stopped.' in window.log.toPlainText()
    child_stat = Path(f'/proc/{child}/stat')
    wait(lambda: not child_stat.exists() or child_stat.read_text().split()[2] == 'Z')


def test_real_application_event_loop_exits_after_quitting_hidden_window(tmp_path):
    # Run the actual main()/single-instance lock and event loop in a disposable
    # process. Closing a hidden QWidget alone need not emit lastWindowClosed.
    code = '''
from pathlib import Path
import os
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
import comfyui_control.app as desktop
from comfyui_control.config import Config
installation = Path(os.environ['XDG_CONFIG_HOME'])
installation.mkdir(parents=True, exist_ok=True)
(installation / 'main.py').touch()
Config(comfy_dir=str(installation), monitoring_enabled=False).save()
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
QSystemTrayIcon.show = lambda self: None
events = []
class InstrumentedWindow(desktop.MainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed.connect(lambda: events.append('closed'))
        QTimer.singleShot(0, self.close)
        QTimer.singleShot(50, self.quit_hidden)
        QTimer.singleShot(2000, lambda: QApplication.instance().exit(9))
    def _close_choice(self):
        return 'tray'
    def quit_hidden(self):
        if self.isVisible() or self._closing:
            QApplication.instance().exit(8)
            return
        events.append('hidden-and-running')
        self.tray_quit.trigger()
desktop.MainWindow = InstrumentedWindow
result = desktop.main()
assert result == 0 and events == ['hidden-and-running', 'closed'], (result, events)
print('Hidden tray application exited cleanly.')
'''
    import os
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=8,
                            env={**os.environ, 'XDG_CONFIG_HOME': str(tmp_path / 'settings'), 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Hidden tray application exited cleanly.' in result.stdout


@pytest.mark.parametrize('label,behavior', [('Keep in tray', 'tray'), ('Quit', 'quit')])
def test_close_choice_is_persisted_and_used_on_next_close(window, label, behavior):
    def choose(dialog):
        assert dialog.checkBox().isChecked()
        assert 'Settings → Close button action' in dialog.informativeText()
        next(button for button in dialog.buttons() if button.text() == label).click()
    with patch.object(QMessageBox, 'exec', choose):
        assert window._close_choice() == behavior
    assert Config.load().close_behavior == behavior
    assert window.controller.config.close_behavior == behavior
    with patch.object(window, '_close_choice') as prompt:
        window.close()
        prompt.assert_not_called()
    assert window.isVisible() is False
    assert window._closing == (behavior == 'quit')


@pytest.mark.parametrize('label', ['Keep in tray', 'Quit', 'Cancel'])
def test_cancel_or_unchecked_remember_does_not_change_close_preference(window, label):
    window.controller.config.save()
    original = window.controller.config
    def choose(dialog):
        if label != 'Cancel':
            dialog.checkBox().setChecked(False)
        next(button for button in dialog.buttons() if button.text() == label).click()
    with patch.object(QMessageBox, 'exec', choose):
        window._close_choice()
    assert window.controller.config == original
    assert Config.load().close_behavior == 'ask'


def test_remember_failure_still_honors_choice_but_explains_it_was_not_saved(window):
    def choose(dialog):
        next(button for button in dialog.buttons() if button.text() == 'Keep in tray').click()
    with patch.object(QMessageBox, 'exec', choose), patch.object(Config, 'save', side_effect=OSError('Disk full')), patch.object(QMessageBox, 'warning') as warning:
        assert window._close_choice() == 'tray'
    assert window.controller.config.close_behavior == 'ask'
    assert 'was not saved' in warning.call_args.args[-1]


def test_close_preference_can_change_while_running_without_touching_server(window):
    window.controller.state = 'running'
    current = window.controller.config
    def save(dialog):
        assert not dialog.launch_contents.isEnabled()
        assert dialog.close_behavior.isEnabled()
        dialog.close_behavior.setCurrentIndex(dialog.close_behavior.findData('quit'))
        dialog.folder.setText('/ignored-during-run')
        dialog._save()
        return dialog.result()
    with patch.object(SettingsDialog, 'exec', save), patch.object(window.controller, 'set_config') as configure, \
         patch.object(window.controller, 'start') as start, patch.object(window.controller, 'shutdown') as stop, \
         patch.object(window.mobile, 'update_desktop') as mobile:
        window._settings()
        configure.assert_not_called(); start.assert_not_called(); stop.assert_not_called(); mobile.assert_not_called()
    assert window.controller.config == replace(current, close_behavior='quit')
    assert Config.load().close_behavior == 'quit'
    window.controller.state = 'stopped'


def test_saved_quit_action_stops_active_server_without_repeating_question(window):
    window.controller.config = replace(window.controller.config, close_behavior='quit')
    window.controller.state = 'running'
    with patch.object(window.controller, 'shutdown') as shutdown, patch.object(QMessageBox, 'question') as question, patch.object(window, '_close_choice') as choice:
        window.close()
        shutdown.assert_called_once()
        question.assert_not_called()
        choice.assert_not_called()
    window.controller.state = 'stopped'


def test_saved_tray_action_cannot_hide_running_app_without_a_tray_host(window, monkeypatch):
    window.controller.config = replace(window.controller.config, close_behavior='tray')
    window.controller.state = 'running'
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: False))
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No), patch.object(window.controller, 'shutdown') as shutdown:
        window.close()
        shutdown.assert_not_called()
    assert window.isVisible() and not window._closing
    window.controller.state = 'stopped'
