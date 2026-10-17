import asyncio
import time

from aiohttp.test_utils import TestServer
from PySide6.QtTest import QTest

from comfyui_control.config import Config
from comfyui_control.controller import Controller
from comfyui_control.monitor_widgets import MonitorPanel
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until


def test_mobile_reuses_hidden_sampler_and_releases_demand(app,tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    class Reader:
        calls=0
        def reset(self): pass
        def sample(self,pid):
            self.calls+=1
            return dict(cpu=None,ram_used=None,ram_total=None,process_memory=None,gpus=[])
    reader=Reader()
    controller=Controller(Config(monitoring_enabled=False))
    panel=MonitorPanel(controller,controller.config,reader=reader)
    samples=[]
    panel.hardware_sampled.connect(samples.append)
    panel.set_mobile_demand(True)
    panel.showMinimized()
    end=time.monotonic()+2
    while not samples and time.monotonic()<end: QTest.qWait(10)
    assert samples and reader.calls==1 and panel.timer.isActive()
    panel.set_mobile_demand(False)
    assert not panel.timer.isActive()
    panel.close()


def test_hardware_demand_freshness_and_remote_comfy(tmp_path):
    demand=[]
    service=MobileService(tmp_path,MobileSettings(),tmp_path/'out',monitoring=demand.append)
    service.online=True
    service.jobs['one']=dict(id='one',owner='alice',status='running',seconds_per_iteration=.25)
    queue=asyncio.Queue(maxsize=2)
    service.subscribers[queue]='bob'
    service.broadcast()
    assert not demand
    service.subscribers[queue]='alice'
    service.broadcast()
    assert demand==[True]
    service.update_hardware(dict(utilization=65,vram_used=3*2**30,temperature=80,secret='no'))
    assert service.state(owner='alice')['hardware']==dict(utilization=65,vram_used=3*2**30)
    assert not service.state(owner='bob')['jobs']
    service.hardware_time-=6
    assert service.state()['hardware']=={}
    service.subscribers.clear()
    service.broadcast()
    assert demand==[True,False]
    remote=MobileService(tmp_path,MobileSettings(comfy_url='http://other-pc.example:8188'),tmp_path/'out',monitoring=demand.append)
    remote.online=True
    remote.jobs=service.jobs
    remote.subscribers[queue]='alice'
    remote.broadcast()
    remote.update_hardware(dict(utilization=65,vram_used=3*2**30))
    assert remote.state()['hardware']=={} and demand==[True,False]


def test_sampling_is_job_scoped_and_disconnect_clears_it(tmp_path,mobile_graph):
    async def scenario():
        stub=ComfyStub(mobile_graph)
        stub.running=[[1,'owned-prompt',mobile_graph,{},[]]]
        upstream=TestServer(stub.app())
        await upstream.start_server()
        service=MobileService(tmp_path,MobileSettings(comfy_url=str(upstream.make_url('/'))),tmp_path/'out')
        service.jobs['one']=dict(id='one',owner='alice',status='running',prompt_id='owned-prompt',images=[])
        await service.start()
        try:
            await until(lambda: bool(stub.sockets) and service.online)
            await stub.emit('execution_start',dict(prompt_id='owned-prompt'))
            await stub.emit('progress',dict(prompt_id='owned-prompt',value=1,max=4))
            await until(lambda: (service.jobs['one'].get('progress') or {}).get('value')==1)
            await asyncio.sleep(.03)
            await stub.emit('progress',dict(prompt_id='owned-prompt',value=2,max=4))
            await until(lambda: service.jobs['one'].get('seconds_per_iteration') is not None)
            assert service.state(owner='alice')['jobs'][0]['seconds_per_iteration']>0
            assert not service.state(owner='bob')['jobs']
            for socket in list(stub.sockets): await socket.close()
            await until(lambda: not service.online)
            assert service.jobs['one']['seconds_per_iteration'] is None
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())
