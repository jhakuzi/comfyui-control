import time
from PySide6.QtWidgets import QDialog
from PySide6.QtTest import QTest
from comfyui_control.app import MainWindow, SettingsDialog
from comfyui_control.config import Config
from comfyui_control.monitor_widgets import MonitorPanel
from comfyui_control.controller import Controller


def test_monitor_pauses_when_hidden_and_retains_expanded_preference(app,tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    class Reader:
        calls=0
        def reset(self): pass
        def sample(self,pid):
            self.calls+=1
            return dict(cpu=25,ram_used=1024**3,ram_total=8*1024**3,process_memory=None,gpus=[])
    reader=Reader()
    controller=Controller(Config())
    panel=MonitorPanel(controller,controller.config,reader=reader)
    panel.show()
    assert not panel.timer.isActive()
    panel.toggle.setChecked(True)
    end=time.monotonic()+3
    while panel.worker and time.monotonic()<end: QTest.qWait(10)
    assert reader.calls and 'CPU 25%' in panel.hardware.text()
    panel.hide()
    assert not panel.timer.isActive()
    count=reader.calls
    QTest.qWait(80)
    assert reader.calls==count
    panel.close()
    window=MainWindow(Config())
    window.show()
    window.monitor.toggle.setChecked(True)
    assert Config.load().monitor_expanded
    window.close()


def test_launch_settings_preserve_monitor_and_recovery_preferences(app,tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    (tmp_path/'main.py').touch()
    original=Config(comfy_dir=str(tmp_path),monitor_expanded=True,auto_restart=True,restart_limit=7)
    dialog=SettingsDialog(original)
    dialog._save()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert dialog.result_config.monitor_expanded and dialog.result_config.auto_restart
    assert dialog.result_config.restart_limit==7
    dialog.close()
