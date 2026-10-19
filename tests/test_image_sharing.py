import asyncio
from dataclasses import replace
import hashlib
import json

from aiohttp.test_utils import TestClient, TestServer
import pytest
from PySide6.QtGui import QImage

from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.service import revision
from comfyui_control.mobile.server import MobileHTTP
from test_image_details import make_image
from test_image_reuse import image_graph, setup_service


def test_image_sharing_preference_defaults_validation_and_persistence(tmp_path):
    path = tmp_path / 'mobile.json'
    path.write_text('{}')
    assert not MobileSettings.load(path).share_image_settings
    settings = MobileSettings(share_image_settings=True)
    settings.save(path)
    assert MobileSettings.load(path) == settings
    for invalid in (1, None, 'false'):
        with pytest.raises(ValueError, match='image settings sharing'):
            replace(settings, share_image_settings=invalid).validate()


def test_shared_image_settings_do_not_share_live_jobs_cancel_or_prompt_history(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        laptop, phone = 'a' * 64, 'b' * 64
        path = output / 'mobile.png'
        make_image(path, graph)
        preset = service.presets.create('Existing custom workflow', graph)
        preset = service.presets.map(preset['id'], [dict(node='prompt', input='text', role='positive', key='p'),
            dict(node='sampler', input='seed', role='seed', key='s')])
        job = dict(id='private-job', owner=laptop, status='running', prompt_id='private-prompt-id',
            preset=preset['id'], revision=revision(preset), values=dict(p='An image made on the laptop', s=987654321),
            controls=[dict(key='p', role='positive', label='Prompt'), dict(key='s', role='seed', label='Seed')],
            disabled_loras=[], images=[])
        service.jobs[job['id']] = job
        item = service.image_ref(dict(filename=path.name), job['id'])
        service.preview = (path.read_bytes(), 'image/png')
        service.preview_job = job['id']
        service.prompts.record(laptop, job['controls'], job['values'])
        assert (await service.image_details(item['id'], phone))['restricted']
        assert not service.image_reuse_status(item, phone)['available']
        with pytest.raises(ValueError, match='another browser session'):
            await service.prepare_image_reuse(item['id'], phone)
        service.settings = replace(service.settings, share_image_settings=True)
        reused = await service.prepare_image_reuse(item['id'], phone)
        assert reused['values'] == job['values'] and reused['preset'] == job['preset']
        assert set(reused) == {'preset', 'revision', 'values', 'controls', 'disabled_loras'}
        details = await service.image_details(item['id'], phone)
        assert details['positive'][0]['value'] == job['values']['p']
        assert await service.image_parameters(item['id'], phone)
        state = service.state(owner=phone)
        assert not state['jobs'] and state['preview'] is None
        assert not await service.prompt_history(phone)
        with pytest.raises(ValueError):
            await service.cancel(job['id'], phone)
        assert job == service.jobs[job['id']]
        service.settings = replace(service.settings, share_image_settings=False)
        assert (await service.image_details(item['id'], phone))['restricted']
        assert not await service.image_parameters(item['id'], phone)
    asyncio.run(scenario())


def test_shared_png_reuse_survives_job_pruning_and_server_restart(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        make_image(output / 'mobile.png', graph)
        original = (output / 'mobile.png').read_bytes()
        service.jobs['old'] = dict(id='old', owner='laptop', status='complete', images=[])
        item = service.image_ref(dict(filename='mobile.png'), 'old')
        service.jobs.clear()
        service.persist()
        reopened, _ = setup_service_for_existing(tmp_path, graph, output)
        images = await reopened.gallery('phone')
        assert not images[0]['reuse']['available']
        reopened.settings = replace(reopened.settings, share_image_settings=True)
        restored = await reopened.prepare_image_reuse(item['id'], 'phone')
        assert reopened.presets.get(restored['preset'])['graph'] == graph
        assert not reopened.jobs and (output / 'mobile.png').read_bytes() == original
    asyncio.run(scenario())


def setup_service_for_existing(tmp_path, graph, output):
    from unittest.mock import AsyncMock
    from comfyui_control.mobile.service import MobileService
    service = MobileService(tmp_path / 'data', MobileSettings(), output)
    service.info = {node['class_type']: {'input': {}} for node in graph.values()}
    service.metadata = AsyncMock(return_value=service.info)
    return service, output


def test_http_sharing_allows_reuse_without_raw_workflow_download_or_private_state(tmp_path):
    async def scenario():
        graph = image_graph()
        service, output = setup_service(tmp_path, graph)
        path = output / 'mobile.png'
        make_image(path, graph)
        original = path.read_bytes()
        clients = [TestClient(TestServer(MobileHTTP(service).app())) for _ in range(2)]
        try:
            for client in clients:
                await client.start_server()
                await client.get('/api/session')
            laptop, phone = clients
            owner = hashlib.sha256(laptop.session.cookie_jar.filter_cookies(laptop.make_url('/'))['mobile_client'].value.encode()).hexdigest()
            preset = service.presets.create('Saved workflow', graph)
            service.jobs['owned'] = dict(id='owned', owner=owner, status='complete', preset=preset['id'],
                revision=revision(preset), values={}, controls=[], images=[], prompt_id='do-not-share')
            item = service.image_ref(dict(filename=path.name), 'owned')
            service.jobs['owned']['images'] = [item]
            assert (await (await phone.get(item['url'] + '/details')).json())['restricted']
            assert not QImage.fromData(await (await phone.get(item['download'])).read()).text('prompt')
            service.settings = replace(service.settings, share_image_settings=True)
            gallery = await (await phone.get('/api/gallery')).json()
            assert gallery[0]['reuse']['available'] and gallery[0]['job'] is None
            reply = await phone.post(item['url'] + '/reuse', json={}, headers={'Origin': str(phone.make_url('/')).rstrip('/')})
            assert reply.status == 200
            assert 'do-not-share' not in json.dumps(await reply.json())
            assert not (await (await phone.get('/api/state')).json())['jobs']
            shared_download = QImage.fromData(await (await phone.get(item['download'])).read())
            assert not shared_download.text('prompt')
            service.settings = replace(service.settings, share_image_settings=False)
            assert (await (await phone.get(item['url'] + '/details')).json())['restricted']
            assert not QImage.fromData(await (await phone.get(item['download'])).read()).text('prompt')
            assert path.read_bytes() == original
        finally:
            for client in clients:
                await client.close()
    asyncio.run(scenario())
