import asyncio
import uuid

import pytest
from aiohttp.test_utils import TestClient, TestServer

from comfyui_control.mobile.client import ComfyError
from comfyui_control.mobile.prompt_history import PromptHistory
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub


def test_history_pairs_deduplication_favorites_bounds_and_private_paths(tmp_path):
    store=PromptHistory(tmp_path)
    alice,bob='a'*64,'b'*64
    controls=[dict(key='p',role='positive',label='Prompt'),dict(key='n',role='negative',label='Negative')]
    first=store.record(alice,controls,dict(p='A quiet forest',n='noise'))
    store.favorite(alice,first['id'],True)
    again=store.record(alice,controls,dict(p='A quiet forest',n='noise'))
    assert again['favorite'] and len(store.list(alice))==1
    assert store.list(bob)==[]
    different=store.record(alice,controls,dict(p='A quiet forest',n='blur'))
    assert different['id']!=first['id']
    store.max_entries=3
    for value in ('one','two','three','four'):
        store.record(alice,controls,dict(p=value,n=''))
    loaded=PromptHistory(tmp_path).list(alice)
    assert len(loaded)==3 and next(item for item in loaded if item['id']==first['id'])['favorite']
    store.delete(alice,first['id'])
    assert not any(item['id']==first['id'] for item in store.list(alice))
    with pytest.raises(ValueError): store.path('../../credentials')
    with pytest.raises(ValueError): store.favorite(alice,loaded[0]['id'],'false')
    store.clear(alice)
    assert store.list(alice)==[]


def test_accepted_prompts_are_owned_persistent_and_retries_do_not_restore_deletions(tmp_path):
    async def scenario():
        graph={'p':{'class_type':'CustomText','inputs':{'sentence':'old'}},
               'n':{'class_type':'CustomText','inputs':{'sentence':'old negative'}}}
        stub=ComfyStub(graph)
        upstream=TestServer(stub.app()); await upstream.start_server()
        service=MobileService(tmp_path/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),tmp_path/'out')
        preset=service.presets.create('Custom prompts',graph)
        preset=service.presets.map(preset['id'],[
            dict(key='p',node='p',input='sentence',role='positive'),
            dict(key='n',node='n',input='sentence',role='negative')])
        await service.start()
        clients=[TestClient(TestServer(MobileHTTP(service).app())) for _ in range(2)]
        for client in clients:
            await client.start_server(); await client.get('/api/session')
        alice,bob=clients
        def headers(client): return {'Origin':str(client.make_url('/')).rstrip('/')}
        body=dict(request_id=str(uuid.uuid4()),preset=preset['id'],revision=revision(preset),values=dict(p='Portrait with GGUF',n='noise'))
        try:
            response=await alice.post('/api/generate',json=body,headers=headers(alice))
            assert response.status==202
            entries=await (await alice.get('/api/prompts')).json()
            assert len(entries)==1 and entries[0]['positive'][0]['value']=='Portrait with GGUF'
            assert entries[0]['negative'][0]['value']=='noise'
            identifier=entries[0]['id']
            assert (await bob.put('/api/prompts/'+identifier,json={'favorite':True},headers=headers(bob))).status==400
            assert await (await bob.get('/api/prompts')).json()==[]
            assert (await alice.put('/api/prompts/'+identifier,json={'favorite':True},headers=headers(alice))).status==200
            assert (await bob.delete('/api/prompts',json={},headers=headers(bob))).status==200
            assert len(await (await alice.get('/api/prompts')).json())==1
            repeat={**body,'request_id':str(uuid.uuid4())}
            await alice.post('/api/generate',json=repeat,headers=headers(alice))
            entries=await (await alice.get('/api/prompts')).json()
            assert len(entries)==1 and entries[0]['favorite']
            owner=service.jobs[body['request_id']]['owner']
            assert len(PromptHistory(tmp_path/'data/prompts').list(owner))==1
            await alice.delete('/api/prompts/'+identifier,json={},headers=headers(alice))
            await alice.post('/api/generate',json=body,headers=headers(alice))
            await service.refresh()
            assert await (await alice.get('/api/prompts')).json()==[]
            assert len(stub.submissions)==2  # Request retry never resubmits.
            # An accepted request whose HTTP response was lost is recorded on recovery.
            original=service.client.request
            async def lost(method,path,body=None):
                value=await original(method,path,body)
                if path=='/prompt': raise ComfyError('Lost response')
                return value
            service.client.request=lost
            lost_job=await service.submit({**body,'request_id':str(uuid.uuid4())},owner)
            service.client.request=original
            await service.refresh()
            assert lost_job['prompt_id'] and len(await service.prompt_history(owner))==1
            await service.prompt_history(owner,'clear')
            async def rejected(method,path,body=None):
                if path=='/prompt': raise ComfyError('Invalid workflow',rejected=True)
                return await original(method,path,body)
            service.client.request=rejected
            job=await service.submit({**body,'request_id':str(uuid.uuid4())},owner)
            assert job['status']=='failed' and await service.prompt_history(owner)==[]
            service.client.request=original
            def no_storage(*args): raise OSError('Disk full')
            service.prompts.record=no_storage
            request={**body,'request_id':str(uuid.uuid4())}
            job=await service.submit(request,owner)
            count=len(stub.submissions)
            assert job['status']=='queued' and job.get('prompt_history_notice')
            assert (await service.submit(request,owner))['prompt_id']==job['prompt_id']
            assert len(stub.submissions)==count
        finally:
            for client in clients: await client.close()
            await service.stop(); await upstream.close()
    asyncio.run(scenario())
