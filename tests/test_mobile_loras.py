"""LoRA catalogues for standard combos and custom extension string widgets."""
import asyncio
from copy import deepcopy
import uuid

from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import fields_for, render
from test_mobile_integration import ComfyStub, until


def workflow():
    return {
        'base': dict(class_type='CustomGGUF', inputs=dict(unet_name='base.gguf')),
        'first': dict(class_type='CustomLoRA', inputs=dict(model=['base', 0],
            file='portraits/one.safetensors', strength_model=.7, strength_clip=.8)),
        'second': dict(class_type='ComboLoRA', inputs=dict(model=['first', 0],
            lora_name='two.safetensors', strength_model=.4)),
        'upscale': dict(class_type='UnusualUpscaler', inputs=dict(model=['second', 0], settings={'keep': [1, 2]})),
    }


def mapped(service):
    preset = service.presets.create('Custom LoRAs', workflow())
    return service.presets.map(preset['id'], [
        dict(node='base', input='unet_name', role='diffusion_model', key='base-name'),
        dict(node='first', input='file', role='lora_model', key='first-name', group='one'),
        dict(node='first', input='strength_model', role='lora_strength', key='first-strength', group='one'),
        dict(node='first', input='strength_clip', role='lora_strength', key='clip-strength', group='one'),
        dict(node='second', input='lora_name', role='lora_model', key='second-name', group='two'),
        dict(node='second', input='strength_model', role='lora_strength', key='second-strength', group='two'),
    ])


@pytest.mark.parametrize('schema', [[['two.safetensors', 'None']], ['COMBO', {'options': ['two.safetensors', 'None']}]])
def test_lora_fallback_preserves_registered_choices_and_changes_only_mapped_literals(tmp_path, schema):
    service = MobileService(tmp_path, MobileSettings(), tmp_path/'output')
    preset = mapped(service)
    original = deepcopy(preset)
    info = {'CustomLoRA': {'input': {'required': {'file': ['STRING']}}},
            'ComboLoRA': {'input': {'required': {'lora_name': schema}}}}
    catalogue = ['portraits/one.safetensors', 'landscapes/new.safetensors']
    fields = {field['key']: field for field in fields_for(preset, info, catalogue)}
    assert fields['first-name']['options'] == catalogue
    assert fields['second-name']['options'] == ['two.safetensors', 'None']
    changed, _ = render(preset, {'first-name': catalogue[1], 'second-name': 'None'},
                        disabled_loras=['one'], info=info, lora_models=catalogue)
    expected = workflow()
    expected['first']['inputs'].update(file=catalogue[1], strength_model=0., strength_clip=0.)
    expected['second']['inputs']['lora_name'] = 'None'
    assert changed == expected
    assert preset == original == service.presets.get(preset['id'])
    with pytest.raises(ValueError, match='not available'):
        render(preset, {'first-name': 'missing.safetensors'}, info=info, lora_models=catalogue)
    with pytest.raises(ValueError, match='not available'):
        render(preset, {'second-name': catalogue[0]}, info=info, lora_models=catalogue)


@pytest.mark.parametrize('saved_value', ['None', 'original.safetensors'])
def test_custom_lora_original_default_is_preserved_even_outside_catalogue(tmp_path, saved_value):
    service = MobileService(tmp_path, MobileSettings(), tmp_path/'output')
    graph = {'custom': dict(class_type='StringLoRA', inputs=dict(file=saved_value))}
    preset = service.presets.create('Saved default', graph)
    preset = service.presets.map(preset['id'], [dict(node='custom', input='file', role='lora_model', key='name')])
    for catalogue in ([], ['installed.safetensors']):
        assert render(preset, {}, lora_models=catalogue)[0] == graph
        with pytest.raises(ValueError, match='not available'):
            render(preset, {'name': 'invented.safetensors'}, lora_models=catalogue)


@pytest.mark.parametrize('catalogue', [None, [], ['portraits/one.safetensors', 'landscapes/new.safetensors']])
def test_lora_catalogue_http_refresh_submission_and_unavailable_server(tmp_path, catalogue):
    async def scenario():
        stub = ComfyStub(workflow())
        stub.loras = deepcopy(catalogue)
        stub.object_info = {node['class_type']: {'input': {}} for node in workflow().values()}
        stub.object_info['CustomLoRA']['input'] = {'required': {'file': ['STRING']}}
        stub.object_info['ComboLoRA']['input'] = {'required': {'lora_name': [['two.safetensors']]}}
        upstream = TestServer(stub.app())
        await upstream.start_server()
        service = MobileService(tmp_path, MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path/'out')
        preset = mapped(service)
        original = deepcopy(preset)
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await service.start()
            await until(lambda: service.online)
            await client.get('/api/session')
            headers = {'Origin': str(client.make_url('/')).rstrip('/')}
            for _ in range(2):
                response = await client.get(f"/api/presets/{preset['id']}")
                assert response.status == 200, await response.text()
                description = await response.json()
                fields = {f['key']: f for f in description['fields']}
                assert fields['first-name']['options'] == catalogue
                assert fields['first-name']['default'] == 'portraits/one.safetensors'
                assert fields['second-name']['options'] == ['two.safetensors']
            assert stub.lora_requests == 1  # one shared cache, including errors/empty catalogues
            stub.loras = ['portraits/one.safetensors', 'landscapes/new.safetensors']
            response = await client.post(f"/api/presets/{preset['id']}/models", json={}, headers=headers)
            assert response.status == 200, await response.text()
            assert stub.lora_requests == 2
            fields = {f['key']: f for f in (await response.json())['fields']}
            assert fields['first-name']['options'] == stub.loras
            assert service.presets.get(preset['id']) == original
            body = dict(request_id=str(uuid.uuid4()), preset=preset['id'], revision=revision(preset),
                        values={'first-name': 'landscapes/new.safetensors'})
            response = await client.post('/api/generate', json=body, headers=headers)
            assert response.status == 202, await response.text()
            await client.post('/api/generate', json=body, headers=headers)
            assert len(stub.submissions) == 1 and stub.lora_requests == 2
            expected = workflow()
            expected['first']['inputs']['file'] = 'landscapes/new.safetensors'
            assert stub.submissions[0]['prompt'] == expected
            assert service.presets.get(preset['id']) == original
        finally:
            await service.stop()
            await client.close()
            await upstream.close()
    asyncio.run(scenario())
