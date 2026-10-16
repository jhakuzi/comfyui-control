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


def test_crash_summary_keeps_exit_code_and_cancels_pending_recovery(app,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'settings'))
    (tmp_path/'main.py').touch()
    config=Config(comfy_dir=str(tmp_path),monitor_expanded=True,auto_restart=True,restart_limit=7)
    window=MainWindow(config)
    window.show()
    window._crashed(dict(summary='ComfyUI crashed (exit 7).'))
    window.controller._state('restarting')
    window._recovery('Restart attempt 1/7 in 2s')
    assert 'exit 7' in window.crash_summary.text() and '1/7' in window.crash_summary.text()
    assert window.cancel_recovery.isVisible()
    window.cancel_recovery.click()
    assert window.controller.state=='stopped'
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:str(tmp_path))
    assert window._choose_folder()
    assert window.controller.config.monitor_expanded and window.controller.config.auto_restart
    assert window.controller.config.restart_limit==7
    window.close()


def test_minimized_monitor_stops_polling_and_observation(app,tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    window=MainWindow(Config(monitor_expanded=True))
    window.show()
    assert window.monitor.timer.isActive()
    window.showMinimized()
    QTest.qWait(30)
    assert not window.monitor.timer.isActive()
    assert not window.monitor.last_observing
    window.showNormal()
    QTest.qWait(30)
    assert window.monitor.timer.isActive()
    window.close()


def test_monitor_text_remains_visible_when_wrapped_or_font_scaled(app,tmp_path,monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    metrics=dict(cpu=3,ram_used=8*1024**3,ram_total=32*1024**3,process_memory=2*1024**3,
        gpus=[dict(name='NVIDIA GPU with a long device name requiring more room at larger font sizes',
            utilization=80,vram_used=1024**3,vram_total=16*1024**3,temperature=55)])
    class Reader:
        def reset(self): pass
        def sample(self,pid): return metrics
    monkeypatch.setattr('comfyui_control.monitor_widgets.HardwareReader',Reader)
    window=MainWindow(Config(monitor_expanded=True))
    window.show()
    deadline=time.monotonic()+2
    while not window.monitor.metrics['gpus'] and time.monotonic()<deadline:
        QTest.qWait(10)
    for points,width in ((10,850),(14,850),(14,580),(10,580)):
        window.setFont(QFont('Sans Serif',points))
        window.resize(width,400)
        QTest.qWait(40)
        monitor=window.monitor
        assert monitor.metrics['gpus']
        for label in (monitor.hardware,monitor.timing):
            assert label.height()>=label.heightForWidth(label.contentsRect().width())
        form=monitor.details.layout()
        assert form.itemAtPosition(0,0).widget().y()==monitor.hardware.y()
        assert form.itemAtPosition(2,0).widget().y()==monitor.timing.y()
        assert monitor.utilization.y()>monitor.hardware.geometry().bottom()
        assert monitor.timing.y()>monitor.utilization.geometry().bottom()
        assert not monitor.geometry().intersects(window.log.geometry())
        assert window.config_button.mapTo(window,QPoint(0,window.config_button.height())).y()<=window.height()
        assert monitor.timing.text()=='Current -- · Average --'
        assert ' W' not in monitor.hardware.text()
    height=monitor.height()
    monitor.toggle.setChecked(False)
    QTest.qWait(40)
    assert monitor.height()<height and not monitor.details.isVisible()
    window.close()
