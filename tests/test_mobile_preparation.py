"""Preparation state and fresh randomized jobs use the existing request journal."""
import asyncio
from copy import deepcopy
import uuid

from aiohttp.test_utils import TestServer

from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until


def test_loading_sampling_next_stage_and_reconnection_state(tmp_path,mobile_graph):
    async def scenario():
        stub=ComfyStub(deepcopy(mobile_graph))
        upstream=TestServer(stub.app())
        await upstream.start_server()
        service=MobileService(tmp_path,MobileSettings(comfy_url=str(upstream.make_url('/'))),tmp_path/'out')
        try:
            await service.start()
            await until(lambda:service.online)
            preset=service.presets.create('Workflow',mobile_graph)
            job=await service.submit({'request_id':str(uuid.uuid4()),'preset':preset['id'],
                'revision':revision(preset),'values':{}},'phone')
            stub.running,stub.pending=stub.pending,[]
            await stub.emit('execution_start',{'prompt_id':job['prompt_id']})
            await stub.emit('executing',{'prompt_id':job['prompt_id'],'node':'quantized'})
            await until(lambda:job['status']=='running')
            assert job['phase']=='preparing' and job['progress'] is None
            # Both initial and compact SSE snapshots restore preparation on return.
            for detailed in (True,False):
                state=service.state(include_details=detailed,owner='phone')
                assert state['jobs'][0]['phase']=='preparing'
            assert service.state(owner='other-phone')['jobs']==[]
            await stub.emit('progress',{'prompt_id':job['prompt_id'],'value':1,'max':8})
            await until(lambda:job['phase']=='sampling')
            assert job['progress']=={'value':1,'max':8}
            await stub.emit('executing',{'prompt_id':job['prompt_id'],'node':'upscale'})
            await until(lambda:job['phase']=='processing')
            assert job['progress'] is None
            await stub.emit('progress_state',{'prompt_id':job['prompt_id'],'nodes':{
                'upscale':{'state':'running','value':2,'max':6}}})
            await until(lambda:job['phase']=='sampling')
            assert job['progress']=={'value':2,'max':6}
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_randomization_changes_new_requests_but_not_retries_or_fixed_seed(tmp_path,mobile_graph,monkeypatch):
    sequence=iter([111,222])
    monkeypatch.setattr('comfyui_control.mobile.workflows.secrets.randbelow',lambda maximum:next(sequence))
    async def scenario():
        original=deepcopy(mobile_graph)
        stub=ComfyStub(mobile_graph)
        upstream=TestServer(stub.app())
        await upstream.start_server()
        service=MobileService(tmp_path,MobileSettings(comfy_url=str(upstream.make_url('/'))),tmp_path/'out')
        try:
            await service.start()
            await until(lambda:service.online)
            preset=service.presets.create('Seeded',mobile_graph)
            preset=service.presets.map(preset['id'],[{'node':'sampler','input':'noise','role':'seed','key':'seed'}])
            body={'request_id':str(uuid.uuid4()),'preset':preset['id'],'revision':revision(preset),
                'values':{'seed':'18446744073709551600'},'random_seed':True}
            first=await service.submit(body,'phone')
            retry=await service.submit(body,'phone')
            assert retry['prompt_id']==first['prompt_id'] and len(stub.submissions)==1
            body['request_id']=str(uuid.uuid4())
            second=await service.submit(body,'phone')
            assert first['values']['seed']!=second['values']['seed']
            assert [s['prompt']['sampler']['inputs']['noise'] for s in stub.submissions]==[111,222]
            body.update(request_id=str(uuid.uuid4()),random_seed=False)
            fixed=await service.submit(body,'phone')
            assert fixed['values']['seed']==18446744073709551600
            assert service.presets.get(preset['id'])['graph']==original
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())
