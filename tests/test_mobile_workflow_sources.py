"""Saved workflow compatibility without hardcoded node classes or graph IDs."""
import asyncio
from copy import deepcopy
import json

from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.workflow_sources import editor_to_api, import_graph, saved_workflows, saved_workflow_graph
from comfyui_control.mobile.workflows import suggested_mappings, validate_mappings, render
from comfyui_control.mobile.settings import MobileSettings, save_json
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


@pytest.fixture
def bypassed_loras(flux_saved):
    editor, info = flux_saved
    # Arbitrary class names and node IDs: route from saved slot types or metadata,
    # never from a hardcoded LoRA class/name. Two outputs must stay distinct.
    info['OptionalAdapter'] = {'input': {'required': {'model': ['MODEL'], 'clip': ['CLIP'],
        'strength': ['FLOAT']}}, 'output': ['MODEL', 'CLIP']}
    info['ModelAdapter'] = {'input': {'required': {'model': ['MODEL'], 'strength': ['FLOAT']}},
        'output': ['MODEL']}
    editor['nodes'].extend([
        {'id': 'adapter', 'type': 'OptionalAdapter', 'mode': 4,
         'inputs': [{'name': 'model', 'link': 7}, {'name': 'clip', 'link': 8}],
         'widgets_values': ['opaque extension state must not be interpreted']},
        {'id': 83, 'type': 'ModelAdapter', 'mode': 4,
         'inputs': [{'name': 'model', 'link': 9}], 'widgets_values': [.7]},
    ])
    editor['links'].extend([[7, 'diff', 0, 'adapter', 0, 'MODEL'],
        [8, 'encoder', 0, 'adapter', 1, 'CLIP'], [9, 'adapter', 0, 83, 0, 'MODEL']])
    editor['links'][0][1:3] = ['adapter', 1]
    editor['links'][1][1:3] = [83, 0]
    return editor, info


def test_bypassed_lora_chain_preserves_model_and_encoder_routes(bypassed_loras):
    editor, info = bypassed_loras
    original = deepcopy(editor)
    graph = editor_to_api(editor, info)
    assert graph['sampler']['inputs']['model'] == ['diff', 0]
    assert graph['text']['inputs']['clip'] == ['encoder', 0]
    assert '83' not in graph and 'adapter' not in graph
    assert graph['sampler']['inputs']['seed'] == 18446744073709551600
    assert editor == original


def test_saved_slot_types_allow_bypassing_an_unavailable_disabled_extension(bypassed_loras):
    editor, info = bypassed_loras
    for node in editor['nodes'][-2:]:
        for entry in node['inputs']:
            entry['type'] = 'MODEL' if entry['name'] == 'model' else 'CLIP'
        node['outputs'] = [{'type': kind} for kind in info.pop(node['type'])['output']]
    graph = editor_to_api(editor, info)
    assert graph['sampler']['inputs']['model'] == ['diff', 0]
    assert graph['text']['inputs']['clip'] == ['encoder', 0]


def test_enabled_loras_keep_their_connections_and_strengths(bypassed_loras):
    editor, info = bypassed_loras
    for node, strength in zip(editor['nodes'][-2:], [.5, .7]):
        node['mode'] = 0
        node['widgets_values'] = [strength]
    original = deepcopy(editor)
    graph = editor_to_api(editor, info)
    assert graph['sampler']['inputs']['model'] == ['83', 0]
    assert graph['text']['inputs']['clip'] == ['adapter', 1]
    assert graph['83']['inputs'] == {'model': ['adapter', 0], 'strength': .7}
    assert graph['adapter']['inputs'] == {'model': ['diff', 0], 'clip': ['encoder', 0], 'strength': .5}
    assert editor == original


@pytest.mark.parametrize('problem', ['multiple-inputs', 'wildcard', 'mismatched-output', 'cycle'])
def test_uncertain_bypass_routing_is_rejected(bypassed_loras, problem):
    editor, info = bypassed_loras
    adapter = editor['nodes'][-1]
    if problem == 'multiple-inputs':
        adapter['inputs'].append({'name': 'other', 'type': 'MODEL', 'link': None})
    elif problem == 'wildcard':
        info['ArbitrarySampler']['input']['required']['model'] = ['*']
    elif problem == 'mismatched-output':
        adapter['outputs'] = [{'type': 'CLIP'}]
    else:
        editor['links'][-1][1:3] = [83, 0]
    with pytest.raises(ValueError, match='bypass'):
        editor_to_api(editor, info)


def test_muted_and_unused_bypassed_nodes_are_omitted_without_being_reenabled(flux_saved):
    editor, info = flux_saved
    editor['nodes'].extend([
        {'id': 'muted', 'type': 'UnavailableExtension', 'mode': 2, 'widgets_values': [{}]},
        {'id': 'bypassed', 'type': 'UnavailableExtension', 'mode': 4, 'widgets_values': [{}]},
    ])
    graph = editor_to_api(editor, info)
    assert 'muted' not in graph and 'bypassed' not in graph
    editor['nodes'][0]['mode'] = 2
    with pytest.raises(ValueError, match="required input 'model' is not connected"):
        editor_to_api(editor, info)


def test_normal_missing_node_metadata_reports_the_actual_problem(flux_saved):
    editor, info = flux_saved
    del info['ArbitraryDiffusion']
    with pytest.raises(ValueError, match='did not provide input metadata'):
        editor_to_api(editor, info)


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


@pytest.mark.parametrize('workflow_fixture', ['flux_saved', 'bypassed_loras'])
def test_saved_catalog_is_confined_and_import_reuses_mappings(tmp_path, request, workflow_fixture):
    editor,info=request.getfixturevalue(workflow_fixture)
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



def test_preset_catalog_describes_sources_without_deleting_stored_snapshots(tmp_path):
    async def scenario():
        service = MobileService(tmp_path / 'data', MobileSettings(require_auth=False), tmp_path / 'out')
        graph = {'text': {'class_type': 'CustomText', 'inputs': {'text': 'Saved prompt'}}}
        records = {}
        for name, marker in [('manual', {}), ('folder', {'comfy_source': 'nested/Portrait.json'}),
                             ('action', {'image_workflow': {'action': 'edit', 'source': 'Edit.json'}}),
                             ('image', {'image_reuse': True})]:
            item = service.presets.create(name, graph)
            item.update(marker)
            save_json(service.presets.path(item['id']), item)
            records[name] = item
        before = {p.name: p.read_bytes() for p in service.presets.directory.glob('*.json')}
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            response = await client.get('/api/presets')
            assert response.status == 200
            items = {item['id']: item for item in await response.json()}
            assert len(items) == 4
            assert items[records['folder']['id']]['comfy_source'] == 'nested/Portrait.json'
            assert items[records['action']['id']]['internal'] is True
            assert items[records['image']['id']]['image_reuse'] is True
            assert not items[records['manual']['id']]['internal']
            assert items[records['manual']['id']]['comfy_source'] is None
            assert all('graph' not in item for item in items.values())
            assert before == {p.name: p.read_bytes() for p in service.presets.directory.glob('*.json')}
        finally:
            await client.close()
    asyncio.run(scenario())

def test_unused_decoder_does_not_block_a_valid_output_branch():
    editor={'nodes':[
        {'id':1,'type':'Canvas','widgets_values':[]},
        {'id':2,'type':'Saver','inputs':[{'name':'images','link':1}],'widgets_values':[]},
        {'id':43,'type':'Decoder','inputs':[{'name':'samples','link':None},{'name':'vae','link':None}],'widgets_values':[]},
    ],'links':[[1,1,0,2,0,'IMAGE']]}
    info={
        'Canvas':{'input':{'required':{}},'output_node':False},
        'Saver':{'input':{'required':{'images':['IMAGE']}},'output_node':True},
        'Decoder':{'input':{'required':{'samples':['LATENT'],'vae':['VAE']}},'output_node':False},
    }
    original=deepcopy(editor)
    graph=editor_to_api(editor,info)
    assert graph['43']['inputs']=={} and graph['2']['inputs']['images']==['1',0]
    assert editor==original


def test_connected_decoder_input_is_preserved_and_missing_active_input_is_clear():
    editor={'nodes':[
        {'id':1,'type':'Latent','widgets_values':[]},
        {'id':43,'type':'Decoder','inputs':[{'name':'samples','link':'2'}],'widgets_values':[]},
        {'id':9,'type':'Save','inputs':[{'name':'images','link':'3'}],'widgets_values':[]},
    ],'links':[
        {'id':2,'origin_id':1,'origin_slot':0,'target_id':43,'target_slot':0,'type':'LATENT'},
        {'id':3,'origin_id':43,'origin_slot':0,'target_id':9,'target_slot':0,'type':'IMAGE'},
    ]}
    info={
        'Latent':{'input':{'required':{}},'output_node':False},
        'Decoder':{'input':{'required':{'samples':['LATENT']}},'output_node':False},
        'Save':{'input':{'required':{'images':['IMAGE']}},'output_node':True},
    }
    graph=editor_to_api(editor,info)
    assert graph['43']['inputs']['samples']==['1',0]
    assert graph['9']['inputs']['images']==['43',0]
    editor['nodes'][1]['inputs'][0]['link']=None
    with pytest.raises(ValueError,match="Node 43 .*required input 'samples' is not connected"):
        editor_to_api(editor,info)


def test_local_scan_ignores_non_json_and_symlink_escapes(tmp_path):
    from comfyui_control.mobile.workflow_sources import local_workflow_files
    root=tmp_path/'workflows'
    (root/'nested').mkdir(parents=True)
    (root/'A.json').write_text('{}')
    (root/'nested/B.JSON').write_text('{}')
    (root/'ignore.txt').write_text('text')
    (root/'outside.json').symlink_to(tmp_path/'private.json')
    external=tmp_path/'external'
    external.mkdir()
    (external/'secret.json').write_text('{}')
    (root/'escape').symlink_to(external,target_is_directory=True)
    assert local_workflow_files(root)==['A.json','nested/B.JSON']
    assert local_workflow_files(tmp_path/'missing')==[]
