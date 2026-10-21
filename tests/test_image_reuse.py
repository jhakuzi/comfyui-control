import asyncio
from copy import deepcopy
import hashlib
import json
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.workflows import render, suggested_mappings
from test_image_details import make_image


def setup_service(tmp_path, graph):
    output = tmp_path / 'output'
    output.mkdir()
    service = MobileService(tmp_path / 'data', MobileSettings(), output)
    info = {node['class_type']: {'input': {}} for node in graph.values()}
    service.metadata = AsyncMock(return_value=info)
    service.info = info
    return service, output


def image_graph():
    return {
        'prompt': dict(class_type='CustomEncoder', inputs=dict(text='A forest in sunlight')),
        'negative': dict(class_type='CustomEncoder', inputs=dict(text='blur')),
        'gguf': dict(class_type='UnknownGGUF', inputs=dict(unet_name='flux.gguf')),
        'lora': dict(class_type='UnusualLoRA', inputs=dict(model=['gguf', 0], lora_name='one.safetensors', strength_model=.7)),
        'sampler': dict(class_type='CustomSampler', inputs=dict(positive=['prompt', 0], negative=['negative', 0],
            model=['lora', 0], seed=18446744073709551600, steps=20, cfg=3.5)),
        'upscale': dict(class_type='UnknownUpscaler', inputs=dict(image=['sampler', 0], settings={'keep': [1, 2, 3]})),
    }


def test_png_reuse_preserves_complete_graph_and_deduplicates_presets(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        path = output / 'desktop.png'
        make_image(path, graph)
        original = path.read_bytes()
        item = (await service.gallery('laptop'))[0]
        assert item['job'] is None and item['reuse']['available']
        first = await service.prepare_image_reuse(item['id'], 'laptop')
        second = await service.prepare_image_reuse(item['id'], 'laptop')
        assert first['preset'] == second['preset'] and len(service.presets.list()) == 1
        preset = service.presets.get(first['preset'])
        assert preset['image_reuse'] is True
        assert render(preset, first['values'])[0] == graph
        assert preset['graph'] == graph and path.read_bytes() == original
        assert first['disabled_loras'] == [] and not service.jobs
        assert 'graph' not in first and any(field['role'] == 'seed' for field in first['controls'])
    asyncio.run(scenario())


def test_png_reuse_keeps_existing_custom_mappings_and_original_preset(tmp_path):
    async def scenario():
        graph = {'p': dict(class_type='CustomText', inputs=dict(sentence='Old', hidden={'keep': True})),
                 'sample': dict(class_type='CustomSampler', inputs=dict(noise=123, prompt=['p', 0]))}
        service, output = setup_service(tmp_path, graph)
        preset = service.presets.create('My workflow', graph)
        preset = service.presets.map(preset['id'], [dict(node='p', input='sentence', role='positive', key='custom-prompt'),
            dict(node='sample', input='noise', role='seed', key='custom-seed')])
        original = deepcopy(preset)
        graph['p']['inputs']['sentence'] = 'Saved image prompt'
        graph['sample']['inputs']['noise'] = 18446744073709551600
        make_image(output / 'desktop.png', graph)
        item = (await service.gallery('laptop'))[0]
        reused = await service.prepare_image_reuse(item['id'], 'laptop')
        assert reused['preset'] == preset['id']
        assert reused['values'] == {'custom-prompt': 'Saved image prompt', 'custom-seed': 18446744073709551600}
        assert service.presets.get(preset['id']) == original
        assert render(original, reused['values'])[0] == graph
        graph['p']['inputs']['hidden'] = {'changed': True}
        make_image(output / 'other.png', graph)
        other = next(item for item in await service.gallery('laptop', force=True) if item['filename'] == 'other.png')
        separate = await service.prepare_image_reuse(other['id'], 'laptop')
        assert separate['preset'] != original['id']
        assert service.presets.get(separate['preset'])['graph'] == graph
        assert service.presets.get(original['id']) == original
    asyncio.run(scenario())


def test_reuse_missing_metadata_deleted_paths_and_foreign_jobs(tmp_path):
    async def scenario():
        service, output = setup_service(tmp_path, image_graph())
        make_image(output / 'plain.png', None)
        item = (await service.gallery('alice'))[0]
        with pytest.raises(ValueError, match='no usable ComfyUI API workflow'):
            await service.prepare_image_reuse(item['id'], 'alice')
        assert not service.presets.list()
        for identifier in ('../credentials', 'unknown'):
            with pytest.raises(ValueError, match='no longer available'):
                await service.prepare_image_reuse(identifier, 'alice')
        service.jobs['owned'] = dict(id='owned', owner='alice', status='complete', preset='saved', revision='rev',
            values=dict(prompt='Private text'), controls=[], images=[])
        owned = service.image_ref(dict(filename='plain.png'), 'owned')
        assert (await service.prepare_image_reuse(owned['id'], 'alice'))['values']['prompt'] == 'Private text'
        with pytest.raises(ValueError, match='another browser session'):
            await service.prepare_image_reuse(owned['id'], 'bob')
        service.jobs.clear()
        with pytest.raises(ValueError, match='another browser session'):
            await service.prepare_image_reuse(owned['id'], 'bob')
        make_image(output / 'plain.png', image_graph())
        with pytest.raises(ValueError, match='mobile generation record is no longer available'):
            await service.prepare_image_reuse(owned['id'], 'alice')
        assert not service.presets.list()  # Private prompts cannot become a shared preset.
        assert not service.image_reuse_status(dict(filename='plain.jpg', subfolder='', type='output'), 'alice')['available']
        (output / 'plain.png').unlink()
        with pytest.raises(ValueError, match='no usable ComfyUI API workflow'):
            await service.prepare_image_reuse(owned['id'], 'alice')
    asyncio.run(scenario())


def test_nfs_reuse_uses_existing_bounded_reader_and_rejects_scope_change(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        make_image(output / 'nas.png', graph)
        payload = (output / 'nas.png').read_bytes()
        item = service.image_ref(dict(filename='nas.png'))
        service.network_output = True
        service.network_io = AsyncMock(return_value=payload)
        reused = await service.prepare_image_reuse(item['id'], 'alice')
        service.network_io.assert_awaited_once_with('read', item)
        assert service.presets.get(reused['preset'])['graph'] == graph
        async def changed(*args):
            service.output_scope = 'changed'
            return payload
        service.network_io = changed
        with pytest.raises(ValueError, match='output folder or image ownership changed'):
            await service.prepare_image_reuse(item['id'], 'alice')
    asyncio.run(scenario())


def test_image_reuse_endpoint_validates_origin_and_browser_ownership(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        make_image(output / 'desktop.png', graph)
        clients = [TestClient(TestServer(MobileHTTP(service).app())) for _ in range(2)]
        try:
            for client in clients:
                await client.start_server()
                await client.get('/api/session')
            a, b = clients
            owner = hashlib.sha256(a.session.cookie_jar.filter_cookies(a.make_url('/'))['mobile_client'].value.encode()).hexdigest()
            images = await (await a.get('/api/gallery')).json()
            endpoint = '/api/images/' + images[0]['id'] + '/reuse'
            assert (await a.post(endpoint, json={})).status == 403
            assert (await a.post(endpoint, json=[], headers={'Origin': str(a.make_url('/')).rstrip('/')})).status == 400
            response = await a.post(endpoint, json={}, headers={'Origin': str(a.make_url('/')).rstrip('/')})
            assert response.status == 200
            saved = await response.json()
            assert 'graph' not in saved and not service.jobs
            service.jobs['private'] = dict(id='private', owner=owner, status='complete', preset=saved['preset'],
                revision=saved['revision'], values=dict(secret='private settings'), images=[])
            service.image_ref(dict(filename='desktop.png'), 'private')
            foreign = await (await b.get('/api/gallery')).json()
            assert foreign[0]['job'] is None and not foreign[0]['reuse']['available']
            denied = await b.post(endpoint, json={}, headers={'Origin': str(b.make_url('/')).rstrip('/')})
            assert denied.status == 400 and 'private settings' not in await denied.text()
        finally:
            for client in clients:
                await client.close()
    asyncio.run(scenario())
