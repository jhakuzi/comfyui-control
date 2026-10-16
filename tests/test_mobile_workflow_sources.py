"""Saved workflow compatibility without hardcoded node classes or graph IDs."""
import asyncio
from copy import deepcopy
import json

from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.workflow_sources import editor_to_api, import_graph, saved_workflows, saved_workflow_graph
from comfyui_control.mobile.workflows import suggested_mappings, validate_mappings, render
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.server import MobileHTTP


@pytest.fixture
def flux_saved():
    definitions = {
        'ArbitraryDiffusion': {'unet_name': [['flux.gguf','another.gguf']]},
        'ArbitraryVAE': {'vae_name': [['ae.safetensors','other-vae.safetensors']]},
        'ArbitraryEncoder': {'clip_name': [['text.gguf','other-text.gguf']]},
        'ArbitraryText': {'clip':['CLIP'], 'text':['STRING']},
        'ResolutionPlugin': {'megapixel':['FLOAT',{'min':0.1,'max':8.0,'step':0.1}],
            'aspect_ratio':[['2:3 (Classic Portrait)','1:1 (Square)']], 'divisible_by':['INT',{'min':1,'max':256}],
            'custom_ratio':[['Disable','Enable']], 'custom_aspect_ratio':['STRING']},
        'ArbitrarySampler': {'model':['MODEL'],'positive':['CONDITIONING'],'vae':['VAE'],
            'width':['INT',{'forceInput':True}],'height':['INT',{'forceInput':True}],
            'seed':['INT',{'control_after_generate':True,'min':0,'max':2**64-1}],
            'steps':['INT',{'min':1,'max':10000}], 'cfg':['FLOAT',{'min':0,'max':100}],
            'sampler_name':[['euler','dpmpp_2m']], 'scheduler':[['simple','karras']]},
    }
    info = {name:{'input':{'required':fields}} for name,fields in definitions.items()}
    nodes = [
        {'id':'diff','type':'ArbitraryDiffusion','widgets_values':['flux.gguf']},
        {'id':'vae','type':'ArbitraryVAE','widgets_values':['ae.safetensors']},
        {'id':'encoder','type':'ArbitraryEncoder','widgets_values':['text.gguf']},
        {'id':'text','type':'ArbitraryText','widgets_values':['A mountain lake'],'inputs':[{'name':'clip','link':1}]},
        {'id':'resolution','type':'ResolutionPlugin','title':'Flux Resolution Calc','widgets_values':[1.5,'2:3 (Classic Portrait)',64,'Disable','1:1']},
        {'id':'sampler','type':'ArbitrarySampler','widgets_values':[18446744073709551600,'randomize',20,3.5,'euler','simple'],
         'inputs':[{'name':name,'link':index+2} for index,name in enumerate(['model','positive','vae','width','height'])]},
    ]
    links = [[1,'encoder',0,'text',0,'CLIP'],[2,'diff',0,'sampler',0,'MODEL'],[3,'text',0,'sampler',1,'CONDITIONING'],
        [4,'vae',0,'sampler',2,'VAE'],[5,'resolution',0,'sampler',3,'INT'],[6,'resolution',1,'sampler',4,'INT']]
    return {'nodes':nodes,'links':links},info


def test_saved_editor_three_models_sampler_and_calculator_preserve_links(flux_saved):
    editor, info = flux_saved
    original = deepcopy(editor)
    graph = editor_to_api(editor,info)
    assert editor == original
    assert graph['sampler']['inputs']['width'] == ['resolution',0]
    assert graph['sampler']['inputs']['height'] == ['resolution',1]
    assert graph['sampler']['inputs']['seed'] == 18446744073709551600
    assert graph['sampler']['inputs']['steps'] == 20
    mappings = validate_mappings(graph,suggested_mappings(graph))
    roles = {m['role']:m for m in mappings}
    assert {'diffusion_model','vae','text_encoder','positive','sampler','scheduler','steps','cfg','resolution_mp','aspect_ratio','alignment','custom_ratio','custom_aspect_ratio'} <= roles.keys()
    assert 'width' not in roles and 'height' not in roles  # Linked outputs stay linked.
    values = {roles[r]['key']:v for r,v in {'diffusion_model':'another.gguf','vae':'other-vae.safetensors','text_encoder':'other-text.gguf',
        'sampler':'dpmpp_2m','scheduler':'karras','steps':30,'cfg':4.0,'resolution_mp':2.0,
        'aspect_ratio':'1:1 (Square)','alignment':64,'custom_ratio':'Enable','custom_aspect_ratio':'16:9'}.items()}
    changed, actual = render({'graph':graph,'mappings':mappings},values,info=info)
    assert changed['resolution']['inputs']['megapixel'] == 2.0
    assert changed['resolution']['inputs']['custom_aspect_ratio'] == '16:9'
    assert changed['sampler']['inputs']['width'] == ['resolution',0]
    assert changed['sampler']['inputs']['height'] == ['resolution',1]
    assert graph['resolution']['inputs']['megapixel'] == 1.5 and editor == original


def test_ambiguous_custom_widgets_and_bypass_require_exact_api(flux_saved):
    editor,info = flux_saved
    editor['nodes'][-1]['widgets_values'].append({'extension':'unknown'})
    with pytest.raises(ValueError,match='custom widgets'):
        editor_to_api(editor,info)
    editor['nodes'][0]['mode'] = 4
    with pytest.raises(ValueError,match='bypass'):
        editor_to_api(editor,info)


def test_import_prefers_exact_queued_snapshot_for_custom_serialization(flux_saved):
    editor,info = flux_saved
    editor['nodes'][-1]['widgets_values'].append({'custom':'state'})
    exact = {'opaque':{'class_type':'AnyCustomNode','inputs':{'keep':{'deep':['data',123]}}}}
    class Client:
        async def request(self,method,path,**kwargs):
            if path=='/queue':
                return {'queue_pending':[[1,'prompt-id',exact,{'extra_pnginfo':{'workflow':editor}},[]]]}
            if path.startswith('/history'):
                return {}
            raise AssertionError('Exact snapshot should not require metadata conversion')
    assert asyncio.run(import_graph(Client(),editor)) == exact


def test_saved_catalog_is_confined_and_import_reuses_mappings(tmp_path,flux_saved):
    editor,info=flux_saved
    class Client:
        async def request(self,method,path,**kwargs):
            if path.startswith('/userdata?'):
                assert kwargs['expected_type'] is list
                return ['nested/Flux portrait.json','../credentials.json','/private.json','readme.txt']
            if path.startswith('/userdata/'):
                assert path == '/userdata/workflows%2Fnested%2FFlux%20portrait.json'
                return editor
            if path=='/queue': return {'queue_pending':[], 'queue_running':[]}
            if path.startswith('/history'): return {}
            if path=='/object_info': return info
            raise AssertionError(path)
    async def scenario():
        backend = Client()
        assert await saved_workflows(backend) == ['nested/Flux portrait.json']
        with pytest.raises(ValueError,match='saved workflow list'):
            await saved_workflow_graph(backend,'../credentials.json')
        service=MobileService(tmp_path,MobileSettings(require_auth=False),tmp_path/'out')
        service.client=backend
        client=TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            origin=str(client.make_url('/')).rstrip('/')
            assert await (await client.get('/api/workflows/saved')).json() == ['nested/Flux portrait.json']
            response=await client.post('/api/workflows/saved',json={'name':'nested/Flux portrait.json'},headers={'Origin':origin})
            assert response.status==201,await response.text()
            first=await response.json()
            assert any(f['role']=='resolution_mp' and f['default']==1.5 for f in first['fields'])
            again=await service.import_saved_workflow('nested/Flux portrait.json')
            assert again['id']==first['id']
            service.settings.default_preset=first['id']
            presets=await (await client.get('/api/presets')).json()
            assert presets[0]['default'] is True
            bad=await client.post('/api/workflows/saved',json={'name':'../credentials.json'},headers={'Origin':origin})
            assert bad.status==400
        finally:
            await client.close()
    asyncio.run(scenario())
