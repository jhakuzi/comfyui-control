import asyncio
from copy import deepcopy
import json
import hashlib

import pytest
from PySide6.QtGui import QImage
from aiohttp.test_utils import TestClient, TestServer

from comfyui_control.mobile.image_metadata import png_details, generation_details
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.server import MobileHTTP


def make_image(path,graph):
    image=QImage(16,32,QImage.Format.Format_RGB32)
    image.fill(0)
    if graph is not None: image.setText('prompt',json.dumps(graph))
    assert image.save(str(path))


def test_png_details_custom_gguf_loras_and_safe_extra_parameters(tmp_path):
    graph={
        'unet':dict(class_type='UnusualGGUF',inputs=dict(gguf_name='model.gguf')),
        'vae':dict(class_type='AnyVAE',inputs=dict(vae_name='vae.safetensors')),
        'clip':dict(class_type='AnyEncoder',inputs=dict(clip_name1='encoder.gguf')),
        'positive':dict(class_type='CustomText',inputs=dict(text='Sunlit forest')),
        'negative':dict(class_type='CustomText',inputs=dict(text='noise')),
        'sampler':dict(class_type='Anything',inputs=dict(positive=['positive',0],negative=['negative',0],
            steps=24,cfg=3.5,seed=18446744073709551600,sampler_name='euler',scheduler='simple')),
        'lora-one':dict(class_type='CustomAdapter',inputs=dict(lora_name='one.safetensors',strength_model=.7,strength_clip=.8)),
        'lora-two':dict(class_type='AnotherAdapter',inputs=dict(lora_name='two.safetensors',strength_model=0.)),
        'extra':dict(class_type='CustomUpscale',inputs=dict(tile_overlap=64,mode='soft',api_key='private-key',note='private arbitrary text')),
    }
    info={'UnusualGGUF':{'output':['MODEL'],'input':{'required':{'gguf_name':[['model.gguf','other.gguf']]}}},
          'CustomUpscale':{'input':{'required':{'mode':[['soft','sharp']]}}}}
    original=deepcopy(graph)
    path=tmp_path/'image.png'
    make_image(path,graph)
    before=path.read_bytes()
    details=png_details(path,info)
    assert details['positive'][0]['value']=='Sunlit forest'
    assert details['negative'][0]['value']=='noise'
    assert details['image']==dict(width=16,height=32)
    assert next(item['value'] for item in details['parameters'] if item['label']=='Seed')==18446744073709551600
    assert 'model.gguf' in json.dumps(details['parameters'])
    assert len(details['loras'])==2
    assert next(item for item in details['loras'] if item['name']=='two.safetensors')['fields'][-1]['value']==0.
    assert {item['value'] for item in details['additional']}=={64,'soft'}
    assert 'private-key' not in json.dumps(details) and 'private arbitrary text' not in json.dumps(details)
    assert path.read_bytes()==before and graph==original


def test_explicit_custom_prompt_mappings_and_unmapped_values_are_preserved():
    graph={'text':dict(class_type='Anything',inputs=dict(sentence='mapped',hidden=12)),
           'loader':dict(class_type='UnknownGGUF',inputs=dict(unet_name='quant.gguf')),
           'sampler':dict(class_type='CustomSampler',inputs=dict(steps=30))}
    controls=[dict(node='text',input='sentence',key='p',role='positive',label='My text'),
              dict(node='loader',input='unet_name',key='m',role='advanced',model_role='diffusion_model',label='Diffusion')]
    details=generation_details(controls,dict(p='New custom prompt',m='quant.gguf'),graph)
    assert details['positive']==[dict(label='My text',value='New custom prompt')]
    assert next(item for item in details['parameters'] if item['label']=='Diffusion model')['value']=='quant.gguf'
    assert next(item for item in details['parameters'] if item['label']=='Steps')['value']==30
    assert details['additional']==[dict(label='Anything · hidden',value=12)]
    assert graph['text']['inputs']['sentence']=='mapped'


def test_image_ownership_survives_pruning_and_restarts(tmp_path):
    async def scenario():
        output=tmp_path/'out'; output.mkdir()
        path=output/'owned.png'
        graph={'text':dict(class_type='CustomText',inputs=dict(text='Alice private prompt')),
               'sampler':dict(class_type='Sampler',inputs=dict(seed=12))}
        make_image(path,graph)
        service=MobileService(tmp_path/'data',MobileSettings(),output)
        service.jobs['job']=dict(id='job',owner='alice',status='complete',images=[])
        item=service.image_ref(dict(filename=path.name),'job')
        service.jobs['job']['images']=[item]
        service.persist()
        service.jobs.clear()  # The job journal is bounded; the file still exists.
        service.persist()
        reopened=MobileService(tmp_path/'data',MobileSettings(comfy_url='http://127.0.0.1:18188'),output)
        shared=await reopened.gallery('bob')
        identifier=next(entry['id'] for entry in shared if entry['filename']==path.name)
        assert identifier!=item['id']  # Public scope changed; private ownership did not.
        blocked=await reopened.image_details(identifier,'bob')
        assert blocked['restricted'] and 'Alice private prompt' not in json.dumps(blocked)
        assert await reopened.image_parameters(identifier,'bob')==[]
        assert (await reopened.image_details(identifier,'alice'))['positive'][0]['value']=='Alice private prompt'
        (tmp_path/'data/image-owners.json').write_text('invalid JSON')
        damaged=MobileService(tmp_path/'data',MobileSettings(),output)
        await damaged.gallery('bob')
        assert (await damaged.image_details(item['id'],'bob'))['restricted']
        with pytest.raises(ValueError): await reopened.image_details('../credentials','alice')
        path.unlink()
        assert not (await reopened.image_details(identifier,'alice'))['positive']
    asyncio.run(scenario())


def test_missing_metadata_and_legacy_jobs_remain_usable(tmp_path):
    async def scenario():
        make_image(tmp_path/'plain.png',None)
        details=png_details(tmp_path/'plain.png',{})
        assert details['image']==dict(width=16,height=32)
        assert not details['positive'] and not details['parameters']
        service=MobileService(tmp_path/'data',MobileSettings(),tmp_path)
        service.jobs['old']=dict(id='old',owner='alice',controls=[dict(key='p',role='positive',label='Prompt')],
            values=dict(p='Old saved prompt'))
        item=service.image_ref(dict(filename='deleted.png'),'old')
        details=await service.image_details(item['id'],'alice')
        assert details['source']=='mobile' and details['positive'][0]['value']=='Old saved prompt'
        assert details['image'] is None
    asyncio.run(scenario())


def test_foreign_downloads_do_not_bypass_metadata_privacy(tmp_path):
    async def scenario():
        path=tmp_path/'owned.png'
        graph={'text':dict(class_type='Text',inputs=dict(text='Private submitted text'))}
        make_image(path,graph)
        original=path.read_bytes()
        service=MobileService(tmp_path/'data',MobileSettings(),tmp_path)
        clients=[TestClient(TestServer(MobileHTTP(service).app())) for _ in range(2)]
        for client in clients:
            await client.start_server(); await client.get('/api/session')
        first,second=clients
        identity=first.session.cookie_jar.filter_cookies(first.make_url('/'))['mobile_client'].value
        owner=hashlib.sha256(identity.encode()).hexdigest()
        service.jobs['job']=dict(owner=owner,controls=[dict(key='p',role='positive',label='Prompt')],values=dict(p='Private submitted text'))
        item=service.image_ref(dict(filename='owned.png'),'job')
        try:
            details=await (await first.get(item['url']+'/details')).json()
            assert details['positive'][0]['value']=='Private submitted text'
            assert (await (await second.get(item['url']+'/details')).json())['restricted']
            assert await (await first.get(item['url'])).read()==original
            clean=await (await second.get(item['download'])).read()
            decoded=QImage.fromData(clean)
            assert not decoded.isNull() and (decoded.width(),decoded.height())==(16,32)
            assert not decoded.text('prompt') and not decoded.text('workflow')
            assert path.read_bytes()==original
            thumb=QImage.fromData(await (await second.get(item['thumbnail'])).read())
            assert not thumb.text('prompt')
        finally:
            for client in clients: await client.close()
    asyncio.run(scenario())
