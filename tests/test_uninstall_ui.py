from unittest.mock import patch
import os
from pathlib import Path
import subprocess
import sys
import pytest

from PySide6.QtWidgets import QDialog, QMessageBox

from comfyui_control.app import MainWindow, SettingsDialog
from comfyui_control.config import Config
from comfyui_control.uninstall_widgets import UninstallDialog
from test_uninstall import user_install
from comfyui_control import uninstall as un


def test_settings_uninstall_is_available_without_saving_launch_changes(app, user_install):
    _, comfy, settings = user_install
    before = (settings/'config.json').read_bytes()
    dialog = SettingsDialog(Config(comfy_dir=str(comfy)), launch_locked=True)
    assert dialog.uninstall_button.isEnabled()
    assert dialog.uninstall_button.text() == 'Uninstall app'
    dialog.uninstall_button.click()
    assert dialog.result() == SettingsDialog.UninstallRequested
    assert dialog.result_config is None and (settings/'config.json').read_bytes() == before


def test_uninstall_dialog_defaults_to_keep_comfy_and_never_deletes_during_confirmation(app, user_install):
    root, comfy, _ = user_install
    with patch('comfyui_control.uninstall_widgets.discover_installation', return_value=un.discover_installation()):
        dialog = UninstallDialog(Config(comfy_dir=str(comfy)))
    assert dialog.choice.currentData() is False
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.plan.comfy is None and root.exists() and comfy.exists()


def test_comfy_removal_requires_correct_typed_path_and_cancel_keeps_all_files(app, user_install):
    root, comfy, _ = user_install
    with patch('comfyui_control.uninstall_widgets.discover_installation', return_value=un.discover_installation()):
        dialog = UninstallDialog(Config(comfy_dir=str(comfy)))
    dialog.choice.setCurrentIndex(1)
    assert not dialog.remove.isEnabled()
    dialog.confirm.setText('wrong path')
    dialog._accept()
    assert dialog.plan is None and 'full folder path' in dialog.error.text()
    dialog.confirm.setText(str(comfy))
    dialog._accept()
    assert dialog.plan.comfy == comfy and root.exists() and comfy.exists()
    dialog.reject()
    assert root.exists() and comfy.exists()


def test_settings_routes_to_uninstall_and_rpm_source_installations_get_clear_message(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path/'config'))
    window = MainWindow(Config())
    with patch.object(SettingsDialog, 'exec', return_value=SettingsDialog.UninstallRequested), patch.object(window, '_uninstall') as uninstall:
        window._settings()
        uninstall.assert_called_once()
    with patch('comfyui_control.uninstall_widgets.discover_installation', side_effect=un.UninstallError('Use sudo dnf remove comfyui-control.')), \
         patch.object(QMessageBox, 'information') as message:
        window._uninstall()
        assert 'dnf remove' in message.call_args.args[2]
    assert window.uninstall_plan is None and not window._closing
    window.close()


@pytest.mark.skipif(os.getuid() == 0, reason='The actual desktop uninstaller intentionally refuses root.')
def test_real_desktop_shutdown_precedes_background_uninstallation(user_install):
    root, comfy, settings = user_install
    child_file = comfy.parent/'child.pid'
    (comfy/'main.py').write_text(
        'import subprocess,sys,time\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(6)"])\n'
        f'open({str(child_file)!r},"w").write(str(child.pid))\n'
        'time.sleep(6)\n')
    code = f'''
import os,socket,sys,time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox
from comfyui_control.app import MainWindow,desktop_main
from comfyui_control.config import Config
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.uninstall import Installation
from comfyui_control.uninstall_widgets import UninstallDialog
root,comfy,child_file=map(Path,{[str(root),str(comfy),str(child_file)]!r})
Config(comfy_dir=str(comfy),python=sys.executable,monitoring_enabled=False,close_behavior='tray').save()
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
MobileSettings(enabled=True,bind='127.0.0.1',port=port,comfy_url='http://127.0.0.1:9').save()
original=MainWindow.show
def confirm(dialog):
    dialog.choice.setCurrentIndex(1)
    dialog.confirm.setText(str(comfy))
    dialog._accept()
    assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    return dialog.result()
def show(self):
    original(self)
    self.closed.connect(lambda: QTimer.singleShot(0,self._fit_contents))
    QTimer.singleShot(10000,lambda: QApplication.instance().exit(2))
    self.controller.start()
    def ready():
        if child_file.exists() and self.mobile.status=='Listening':
            assert root.exists() and comfy.exists()
            self._uninstall()
        else:
            QTimer.singleShot(20,ready)
    QTimer.singleShot(20,ready)
def result(parent,title,text):
    assert title=='Uninstalled',(title,text)
    assert not root.exists() and not comfy.exists()
    print('UNINSTALLED_AFTER_SHUTDOWN',flush=True)
    return QMessageBox.StandardButton.Ok
with patch.object(MainWindow,'show',show), \
     patch.object(UninstallDialog,'exec',confirm), \
     patch('comfyui_control.uninstall_widgets.discover_installation',return_value=Installation('zip',root)), \
     patch.object(QMessageBox,'information',result), \
     patch.object(QMessageBox,'critical',side_effect=AssertionError('Uninstall failed')), \
     patch.object(QMessageBox,'question',side_effect=AssertionError('Unexpected extra confirmation')):
    assert desktop_main()==0
assert not (Path('/proc')/child_file.read_text().strip()).exists() or (Path('/proc')/child_file.read_text().strip()/'stat').read_text().split()[2]=='Z'
'''
    result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Traceback' not in result.stderr, result.stderr
    assert 'UNINSTALLED_AFTER_SHUTDOWN' in result.stdout
    assert not root.exists() and not comfy.exists() and (settings/'mobile/jobs.json').exists()
