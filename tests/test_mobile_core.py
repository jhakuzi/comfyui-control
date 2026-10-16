import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.settings import MobileSettings, check_password, password_hash
from comfyui_control.mobile.workflows import Presets, fields_for, graph_from, render
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision


def test_api_timeouts_are_reported_as_comfy_offline():
    from comfyui_control.mobile.client import ComfyClient, ComfyError

    class TimedOut:
        async def __aenter__(self):
            raise asyncio.TimeoutError()

        async def __aexit__(self, *args):
            pass

    class Session:
        def request(self, *args, **kwargs):
            return TimedOut()

    with pytest.raises(ComfyError, match='unavailable'):
        asyncio.run(ComfyClient(Session(), 'http://127.0.0.1:8188').request('GET', '/queue'))


def test_custom_workflow_changes_only_explicit_inputs(tmp_path, mobile_graph):
    store = Presets(tmp_path)
    graph = deepcopy(mobile_graph)
    original = deepcopy(graph)
    preset = store.create('Quantized + upscaler', graph)
    preset = store.map(preset['id'], [
        {"node": "arbitrary-text", "input": "sentence", "role": "positive", "key": "prompt"},
        {"node": "lora-a", "input": "power", "role": "lora_strength", "group": "one", "key": "a"},
        {"node": "lora-a", "input": "clip_power", "role": "lora_strength", "group": "one", "key": "clip"},
        {"node": "lora-b", "input": "power", "role": "lora_strength", "key": "b"},
    ])
    changed, values = render(preset, {"prompt": "new"}, disabled_loras=['one'])
    expected = deepcopy(original)
    expected['arbitrary-text']['inputs']['sentence'] = 'new'
    expected['lora-a']['inputs']['power'] = 0.0
    expected['lora-a']['inputs']['clip_power'] = 0.0
    assert changed == expected
    assert graph == original == store.get(preset['id'])['graph']
    assert values['b'] == 0.4


def test_mapping_rejects_connections_unknown_values_and_node_editor_json(tmp_path, mobile_graph):
    store = Presets(tmp_path)
    preset = store.create('Custom', deepcopy(mobile_graph))
    with pytest.raises(ValueError, match='connections'):
        store.map(preset['id'], [{"node": "sampler", "input": "conditioning", "role": "positive"}])
    with pytest.raises(ValueError, match='unmapped'):
        render(preset, {"arbitrary-path": "/etc/passwd"})
    with pytest.raises(ValueError, match='API format'):
        graph_from({"nodes": [], "links": []})
    with pytest.raises(ValueError, match='preset ID'):
        store.get('../credentials')


def test_metadata_drives_model_choices_and_limits(tmp_path, mobile_graph):
    store = Presets(tmp_path)
    preset = store.create('Model', deepcopy(mobile_graph))
    preset = store.map(preset['id'], [{"node": "quantized", "input": "file", "role": "model", "key": "model"}])
    info = {"GGUFLoaderWhatever": {"input": {"required": {"file": [["model.gguf", "other.gguf"]]}}}}
    assert fields_for(preset, info)[0]['options'] == ['model.gguf', 'other.gguf']
    with pytest.raises(ValueError, match='not available'):
        render(preset, {"model": "missing.gguf"}, info=info)
    assert render(preset, {"model": "other.gguf"}, info=info)[0]['quantized']['inputs']['file'] == 'other.gguf'


def test_legacy_model_controls_upgrade_preserves_mappings_and_refreshes_choices(tmp_path):
    import time
    graph={
        'loader':{'class_type':'CustomQuantizedLoader','inputs':{'unet_name':'flux.gguf'}},
        'text':{'class_type':'Text','inputs':{'text':'saved prompt'}},
        'sampler':{'class_type':'Sampler','inputs':{'model':['loader',0]}},
    }
    info={'CustomQuantizedLoader':{'output':['MODEL'],'input':{'required':{'unet_name':[['flux.gguf','other.gguf']]}}},
          'Text':{'input':{'required':{'text':['STRING']}}},'Sampler':{'input':{}}}
    async def scenario():
        service=MobileService(tmp_path,MobileSettings(require_auth=False),tmp_path/'out')
        preset=service.presets.create('Old preset',graph)
        preset=service.presets.map(preset['id'],[{'node':'text','input':'text','role':'positive','key':'model-1','label':'My prompt'}],automatic=True)
        old_revision=revision(preset)
        old_mappings=deepcopy(preset['mappings'])
        service.info,service.info_time=deepcopy(info),time.monotonic()
        description=await service.describe(preset)
        diffusion=next(f for f in description['fields'] if f['role']=='diffusion_model')
        assert diffusion['options']==['flux.gguf','other.gguf']
        upgraded=service.presets.get(preset['id'])
        assert upgraded['mappings'][0]==old_mappings[0] and upgraded['graph']==graph
        assert description['model_upgrade_revision']==old_revision
        assert len({m['key'] for m in upgraded['mappings']})==2
        changed,_=render(upgraded,{diffusion['key']:'other.gguf'},info=info)
        assert changed['loader']['inputs']['unet_name']=='other.gguf'
        assert changed['sampler']['inputs']['model']==['loader',0]
        # Explicitly hiding a control stays respected on subsequent loads.
        hidden=service.presets.map(preset['id'],old_mappings)
        assert not any(f['role']=='diffusion_model' for f in (await service.describe(hidden))['fields'])
        calls=[]
        class Client:
            async def request(self,method,path):
                calls.append((method,path))
                fresh=deepcopy(info)
                fresh['CustomQuantizedLoader']['input']['required']['unet_name'][0].append('new.gguf')
                return fresh
        service.client=Client()
        client=TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            response=await client.post(f"/api/presets/{preset['id']}/models",json={},headers={'Origin':str(client.make_url('/')).rstrip('/')})
            assert response.status==200,await response.text()
            refreshed=await response.json()
            assert calls==[('GET','/object_info')]
            assert next(f for f in refreshed['fields'] if f['role']=='diffusion_model')['options'][-1]=='new.gguf'
            assert service.presets.get(preset['id'])['mappings'][0]==old_mappings[0]
            assert service.presets.get(preset['id'])['graph']==graph
        finally:
            await client.close()
    asyncio.run(scenario())


def test_custom_diffusion_name_uses_model_output_metadata_without_mapping_connections():
    from comfyui_control.mobile.workflows import suggested_mappings
    graph={
        'quantized':{'class_type':'CustomLoader','inputs':{'model_name':'flux.gguf'}},
        'encoder':{'class_type':'CustomEncoder','inputs':{'model_name':'text.gguf'}},
        'gguf-encoder':{'class_type':'CustomEncoder','inputs':{'gguf_name':'text.gguf'}},
        'alias':{'class_type':'OtherLoader','inputs':{'diffusion_model_name':'flux.safetensors'}},
        'linked':{'class_type':'OtherLoader','inputs':{'diffusion_model_name':['quantized',0]}},
    }
    info={'CustomLoader':{'output':['MODEL']},'CustomEncoder':{'output':['CLIP']}}
    targets={(m['node'],m['input']):m['role'] for m in suggested_mappings(graph,info)}
    assert targets=={('quantized','model_name'):'diffusion_model',('alias','diffusion_model_name'):'diffusion_model'}


@pytest.mark.parametrize('loader,input_name',[
    ('UnetLoaderGGUF','unet_name'),('UnetLoaderGGUFAdvanced','unet_name'),
    ('LoaderGGUF','gguf_name'),('LoaderGGUFAdvanced','gguf_name'),
    ('CustomGGUFLoader','custom_file'),
])
def test_gguf_diffusion_controls_use_loader_choices_and_keep_advanced_mapping(tmp_path,loader,input_name):
    from comfyui_control.mobile.workflows import suggested_mappings, with_model_controls
    graph={
        'gguf':{'class_type':loader,'inputs':{input_name:'portraits/flux-Q4.gguf'}},
        'sampler':{'class_type':'Sampler','inputs':{'model':['gguf',0]}},
        'clip':{'class_type':'CLIPLoaderGGUF','inputs':{'clip_name':'text.gguf'}},
    }
    info={
        loader:{'output':['MODEL'],'input':{'required':{input_name:[['portraits/flux-Q4.gguf','flux-Q8.gguf']]}}},
        'CLIPLoaderGGUF':{'output':['CLIP'],'input':{'required':{'clip_name':[['text.gguf','other-text.gguf']]}}},
    }
    store=Presets(tmp_path)
    preset=store.create('GGUF workflow',graph)
    # Existing versions can have the filename mapped as an Advanced control.
    preset=store.map(preset['id'],[{'node':'gguf','input':input_name,'role':'advanced','key':'keep-this-key'}])
    fields=fields_for(preset,info)
    assert fields[0]['model_role']=='diffusion_model' and fields[0]['key']=='keep-this-key'
    assert fields[0]['options']==['portraits/flux-Q4.gguf','flux-Q8.gguf']
    changed,_=render(preset,{'keep-this-key':'flux-Q8.gguf'},info=info)
    assert changed['gguf']['inputs'][input_name]=='flux-Q8.gguf'
    assert changed['sampler']['inputs']['model']==['gguf',0] and graph==store.get(preset['id'])['graph']
    assert next(m for m in suggested_mappings(graph,info) if m['node']=='gguf')['role']=='diffusion_model'
    upgraded=with_model_controls(preset,info)
    assert upgraded['mappings'][0]==preset['mappings'][0]
    assert sum(m['node']=='gguf' for m in upgraded['mappings'])==1
    with pytest.raises(ValueError,match='not available'):
        render(preset,{'keep-this-key':'unlisted.gguf'},info=info)


def test_optional_network_password_keeps_secrets_out_of_url(tmp_path):
    hashed = password_hash('correct horse battery')
    assert check_password('correct horse battery', hashed)
    assert not check_password('incorrect', hashed)
    settings = MobileSettings(enabled=True, bind='0.0.0.0', advertised='my-vpn.example', password=hashed)
    settings.save(tmp_path/'mobile.json')
    assert MobileSettings.load(tmp_path/'mobile.json') == settings
    assert settings.url() == 'http://my-vpn.example:8189/'
    assert 'correct horse battery' not in (tmp_path/'mobile.json').read_text()
    assert hashed not in settings.url()
    replace(settings, require_auth=False).validate()
    with pytest.raises(ValueError, match='Set a mobile password'):
        replace(settings, require_auth=True, password='').validate()
    with pytest.raises(ValueError):
        replace(settings, advertised='http://user:secret@vpn.example').validate()


def test_fixed_64_bit_seed_is_not_rounded_by_browser_serialization(tmp_path, mobile_graph):
    from comfyui_control.mobile.service import json_safe
    graph = deepcopy(mobile_graph)
    graph['sampler']['inputs']['noise'] = 18446744073709551600
    store = Presets(tmp_path)
    preset = store.create('Seed precision', graph)
    preset = store.map(preset['id'], [{'node': 'sampler', 'input': 'noise', 'role': 'seed', 'key': 'seed'}])
    safe = json_safe(fields_for(preset, {}))
    assert safe[0]['default'] == '18446744073709551600'
    changed, actual = render(preset, {'seed': safe[0]['default']})
    assert changed['sampler']['inputs']['noise'] == 18446744073709551600
    assert graph == store.get(preset['id'])['graph']


def test_unmapped_literals_are_private_and_progress_omits_prompt_history(tmp_path, mobile_graph):
    import time
    from comfyui_control.mobile.service import MobileService
    async def scenario():
        service = MobileService(tmp_path, MobileSettings(), tmp_path/'output')
        graph = deepcopy(mobile_graph)
        graph['sampler']['inputs']['custom_secret'] = 'must-not-leak-to-phone'
        preset = service.presets.create('Private defaults', graph)
        service.info = {node['class_type']: {'input': {}} for node in graph.values()}
        service.info_time = time.monotonic()
        description = await service.describe(preset)
        assert 'must-not-leak-to-phone' not in json.dumps(description)
        service.jobs['example'] = {'id': 'example', 'status': 'running', 'values': {'prompt': 'private prompt'}, 'images': [], 'controls': []}
        assert 'private prompt' in json.dumps(service.state())
        assert 'private prompt' not in json.dumps(service.state(include_details=False))
    asyncio.run(scenario())


def test_auth_csrf_host_validation_and_output_confinement(tmp_path):
    async def scenario():
        settings = MobileSettings(require_auth=True, password=password_hash('test password 123'))
        service = MobileService(tmp_path/'data', settings, tmp_path/'output')
        client = TestClient(TestServer(MobileHTTP(service).app()), cookie_jar=aiohttp.CookieJar(unsafe=True))
        await client.start_server()
        origin = str(client.make_url('/')).rstrip('/')
        try:
            assert (await client.get('/api/state')).status == 401
            assert (await client.post('/api/login', json={'password': 'test password 123'}, headers={'Origin': 'https://evil.example'})).status == 403
            assert (await client.get('/api/session', headers={'Host': 'evil.example'})).status == 403
            assert (await client.post('/api/login', json={'password': 'test password 123'}, headers={'Origin': origin})).status == 200
            assert (await client.get('/api/state')).status == 200
            manifest = await (await client.get('/manifest.webmanifest')).json()
            assert manifest['name'] == 'comfyui-control Mobile'
            from PySide6.QtGui import QImage
            for size in (192, 512):
                icon = await client.get(f'/icon-{size}.png')
                decoded = QImage.fromData(await icon.read())
                assert (decoded.width(), decoded.height()) == (size, size)
            assert (await client.get('/api/images/../../etc/passwd')).status in (400, 404)
            assert service.image_ref({'filename': '../secret.png'}) is None
            output = tmp_path/'output'
            output.mkdir()
            private = tmp_path/'private.png'
            private.write_bytes(b'private')
            (output/'escape.png').symlink_to(private)
            ref = service.image_ref({'filename': 'escape.png'})
            assert service.local_image(ref) is None
            assert (await client.get(ref['url'])).status == 404
        finally:
            await client.close()
    asyncio.run(scenario())


def test_upgrade_previous_localhost_defaults_preserves_explicit_preferences(tmp_path,monkeypatch):
    monkeypatch.setattr('comfyui_control.mobile.settings.lan_address',lambda:'192.168.10.20')
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'enabled':True,'bind':'127.0.0.1','port':8189,'require_auth':True,'password':''}))
    upgraded=MobileSettings.load(path)
    assert upgraded.bind=='0.0.0.0' and not upgraded.require_auth
    assert upgraded.url()=='http://192.168.10.20:8189/'
    upgraded.bind='127.0.0.1'
    upgraded.save(path)
    assert MobileSettings.load(path).bind=='127.0.0.1'  # A new explicit choice is respected.
    path.write_text(json.dumps({'bind':'127.0.0.1','advertised':'https://vpn.example','require_auth':True,'password':'existing-hash'}))
    explicit=MobileSettings.load(path)
    assert explicit.bind=='127.0.0.1' and explicit.require_auth and explicit.password=='existing-hash'
