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
    MobileSettings(advertised='phone-vpn.example').save()
    runtime = MobileRuntime()
    dialog = MobileDialog(runtime, Config())
    dialog.bind.setText('0.0.0.0')
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
    assert saved.advertised == 'phone-vpn.example'
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


def test_desktop_image_sharing_is_optional_and_saved_without_launching_comfy(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    runtime = MobileRuntime()
    dialog = MobileDialog(runtime, Config())
    assert not dialog.share_images.isChecked()
    dialog.share_images.setChecked(True)
    with patch.object(runtime, 'configure') as configure:
        dialog._apply()
        assert configure.call_args.args[0].share_image_settings
    assert MobileSettings.load().share_image_settings
    dialog.close()
    reopened = MobileDialog(runtime, Config())
    assert reopened.share_images.isChecked()
    reopened.share_images.setChecked(False)
    with patch.object(runtime, 'configure'):
        reopened._apply()
    assert not MobileSettings.load().share_image_settings
    reopened.close()


def test_mobile_dialog_scrolls_only_when_content_needs_it(app,tmp_path,monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    dialog=MobileDialog(MobileRuntime(),Config())
    dialog.setFont(QFont('Sans Serif',10))
    dialog.show()
    QTest.qWait(40)
    area=dialog.findChild(QScrollArea)
    scroll=area.verticalScrollBar()
    assert scroll.maximum()==0
    assert not dialog.workflow_status.isVisible()
    bottom=dialog.catalog_button.mapTo(area.viewport(),QPoint(0,dialog.catalog_button.height()))
    assert bottom.y()<=area.viewport().height()
    dialog.resize(570,450)
    dialog._workflow_message('Could not read the workflow. Please check the ComfyUI API URL.')
    QTest.qWait(40)
    assert scroll.maximum()>0 and dialog.workflow_status.isVisible()
    scroll.setValue(scroll.maximum())
    bottom=dialog.workflow_status.mapTo(area.viewport(),QPoint(0,dialog.workflow_status.height()))
    assert 0<bottom.y()<=area.viewport().height()
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


def test_lan_detection_optional_password_and_default_workflow(app,tmp_path,monkeypatch):
    from comfyui_control.mobile.workflows import Presets
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    monkeypatch.setattr('comfyui_control.mobile.settings.lan_address',lambda:'192.168.1.42')
    monkeypatch.setattr('comfyui_control.mobile_widgets.lan_address',lambda:'192.168.1.42')
    runtime=MobileRuntime()
    dialog=MobileDialog(runtime,Config())
    assert dialog.bind.text()=='0.0.0.0'
    assert dialog.current_url=='http://192.168.1.42:8189/'
    assert not dialog.auth.isChecked() and not dialog.password.isEnabled()
    dialog.bind.setText('127.0.0.1')
    dialog.settings=replace(dialog.settings,advertised='old-vpn.example')
    dialog.detect.click()
    assert dialog.bind.text()=='0.0.0.0' and dialog.settings.advertised==''
    dialog._save_workflow('Saved on PC',{'custom-id':{'class_type':'CustomLoader','inputs':{'unet_name':'flux.gguf'}}},source='nested/Flux.json')
    chosen=dialog.default_preset.currentData()
    assert chosen and Presets(tmp_path/'comfyui-control/mobile/presets').get(chosen)['name']=='Saved on PC'
    assert Presets(tmp_path/'comfyui-control/mobile/presets').get(chosen)['comfy_source']=='nested/Flux.json'
    dialog.enabled.setChecked(True)
    with patch.object(runtime,'configure') as configure:
        dialog._apply()
        configure.assert_called_once()
    saved=MobileSettings.load()
    assert saved.enabled and not saved.require_auth and saved.default_preset==chosen
    assert saved.url()=='http://192.168.1.42:8189/'
    # A configured password remains available when protection is toggled off/on.
    dialog.auth.setChecked(True)
    assert dialog.password.isEnabled()
    dialog.password.setText('optional password test')
    with patch.object(runtime,'configure'):
        dialog._apply()
    assert MobileSettings.load().require_auth
    dialog.auth.setChecked(False)
    with patch.object(runtime,'configure'):
        dialog._apply()
    saved=MobileSettings.load()
    assert not saved.require_auth and check_password('optional password test',saved.password)
    dialog.close()


def test_desktop_queued_workflow_fetch_keeps_qt_responsive(app,tmp_path,monkeypatch):
    import asyncio
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    graph={'loader':{'class_type':'AnyQuantizedLoader','inputs':{'unet_name':'model.gguf'}}}
    async def endpoint(request):
        await asyncio.sleep(.05)
        if request.path=='/queue':
            return web.json_response({'queue_pending':[[1,'queued-id',graph,{},[]]],'queue_running':[]})
        return web.json_response({})
    async def scenario():
        upstream=web.Application()
        upstream.router.add_get('/queue',endpoint)
        upstream.router.add_get('/history',endpoint)
        server=TestServer(upstream)
        await server.start_server()
        dialog=MobileDialog(MobileRuntime(),Config())
        dialog.comfy_url.setText(str(server.make_url('/')))
        dialog._fetch_workflow('From active ComfyUI')
        ticks=0
        end=time.monotonic()+5
        while dialog.worker and time.monotonic()<end:
            app.processEvents()
            ticks+=1
            await asyncio.sleep(.01)
        app.processEvents()
        assert dialog.worker is None and ticks>1
        assert dialog.default_preset.currentData()
        assert 'Workflow ready' in dialog.workflow_status.text()
        dialog.close()
        await server.close()
    asyncio.run(scenario())


def test_default_picker_scans_local_workflows_and_imports_without_comfy(app,tmp_path,monkeypatch):
    import json
    from PySide6.QtWidgets import QLabel
    from comfyui_control.mobile.workflows import Presets
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    install=tmp_path/'ComfyUI'
    root=install/'user/default/workflows'
    (root/'portraits').mkdir(parents=True)
    graph={'custom-id':{'class_type':'ModelLoader','inputs':{'unet_name':'flux.gguf'}}}
    source=root/'portraits/Flux.json'
    source.write_text(json.dumps(graph))
    (root/'readme.txt').write_text('not a workflow')
    dialog=MobileDialog(MobileRuntime(),Config(comfy_dir=str(install)))
    def drain(predicate):
        end=time.monotonic()+5
        while predicate() and time.monotonic()<end:
            app.processEvents()
            time.sleep(.01)
        app.processEvents()
        assert not predicate()
    drain(lambda: dialog.scan_worker is not None)
    index=dialog.default_preset.findData('local:portraits/Flux.json')
    assert index>0
    assert all('HTTPS is needed for service workers' not in label.text() for label in dialog.findChildren(QLabel))
    dialog.default_preset.setCurrentIndex(index)
    dialog.default_preset.activated.emit(index)
    assert not dialog.apply_button.isEnabled()
    drain(lambda: dialog.worker is not None)
    selected=dialog.default_preset.currentData()
    assert selected and not selected.startswith('local:')
    store=Presets(tmp_path/'config/comfyui-control/mobile/presets')
    assert store.get(selected)['graph']==graph and json.loads(source.read_text())==graph
    with patch.object(dialog.runtime,'configure'):
        dialog._apply()
    assert MobileSettings.load().default_preset==selected
    # Repeat selection preserves the preset and any input mappings, rather than duplicating it.
    index=dialog.default_preset.findData('local:portraits/Flux.json')
    dialog.default_preset.setCurrentIndex(index)
    dialog.default_preset.activated.emit(index)
    drain(lambda: dialog.worker is not None)
    assert dialog.default_preset.currentData()==selected and len(store.list())==1
    (root/'New.json').write_text(json.dumps(graph))
    dialog._scan_workflows()
    drain(lambda: dialog.scan_worker is not None)
    assert dialog.default_preset.findData('local:New.json')>0
    assert dialog.default_preset.currentData()==selected
    dialog.close()
