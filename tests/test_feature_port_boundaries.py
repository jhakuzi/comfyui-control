"""Only Generate is activated; every other main presentation contract is frozen."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from comfyui_control.mobile.server import MobileHTTP, PUBLIC
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import fields_for
from test_image_workflows import IMAGE_WORKFLOWS, ImageWorkflowStub, picture, ALICE
from test_mobile_integration import until

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((Path(__file__).parent / 'fixtures/main_presentation_baseline.json').read_text())
GENERATE_ASSETS = {'feature_generate.js', 'feature_generate.css'}
GENERATE_INTEGRATION = {'comfyui_control/mobile/web/' + name for name in ('index.html', 'app.js', 'sw.js')}


def test_existing_main_assets_ui_settings_and_versions_are_unchanged():
    for relative, expected in BASELINE['files'].items():
        if relative in GENERATE_INTEGRATION:
            continue
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    web = ROOT / 'comfyui_control/mobile/web'
    for file in web.glob('feature_*'):
        enabled = file.name in GENERATE_ASSETS
        assert ('/' + file.name in PUBLIC) is enabled
        assert (file.name in (web / 'index.html').read_text()) is enabled
        assert (file.name in (web / 'sw.js').read_text()) is enabled
    # Only the Generate label and its two assets may change the shared HTML.
    original = (web / 'index.html').read_text().replace(
        '    <link rel="stylesheet" href="/feature_generate.css" />\n', '').replace(
        '    <script src="/feature_generate.js" defer></script>\n', '').replace(
        '<span id="generate-label" data-generate-label>✦ Generate</span>', '<span aria-hidden="true">✦</span> Generate')
    assert hashlib.sha256(original.encode()).hexdigest() == BASELINE['files']['comfyui_control/mobile/web/index.html']
    original_sw = (web / 'sw.js').read_text().replace('comfy-control-mobile-generate-1', 'comfy-control-mobile-1.0.1').replace(
        '  "/feature_generate.js",\n', '').replace('  "/feature_generate.css",\n', '')
    assert hashlib.sha256(original_sw.encode()).hexdigest() == BASELINE['files']['comfyui_control/mobile/web/sw.js']
    assert not list(web.glob('presentation*')) and not (web / 'theme.css').exists()


def test_only_generate_helpers_are_public_and_other_ui_stays_frozen(tmp_path):
    async def scenario():
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            for file in (ROOT / 'comfyui_control/mobile/web').glob('feature_*'):
                assert (await client.get('/' + file.name)).status == (200 if file.name in GENERATE_ASSETS else 404)
            for name in ('style.css', 'prompt_history.js', 'comparison.js', 'image_details.js', 'manifest.webmanifest'):
                response = await client.get('/' if name == 'index.html' else '/' + name)
                assert response.status == 200
                expected = BASELINE['files']['comfyui_control/mobile/web/' + name]
                assert hashlib.sha256(await response.read()).hexdigest() == expected
        finally:
            await client.close()
    asyncio.run(scenario())


def test_actions_keep_main_picker_mapping_and_single_job_contract(tmp_path):
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        picture(tmp_path / 'out/source.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            await service.start()
            await until(lambda: service.online)
            graph = {'main': dict(class_type='CustomPrompt', inputs={'text':'unsent draft'}),
                     'sampler': dict(class_type='Sampler', inputs={'steps': 20, 'cfg': 4, 'seed': 42})}
            stub.object_info.update({node['class_type']: {'input': {}} for node in graph.values()})
            main = service.presets.create('My workflow', graph)
            main = service.presets.map(main['id'], [dict(node='main', input='text', role='positive', key='prompt')])
            before = deepcopy(await service.describe(main))
            picker = await (await client.get('/api/presets')).json()
            item = (await service.gallery(ALICE))[0]
            import uuid
            for action in ('edit', 'upscale'):
                result = await service.image_action(item['id'], ALICE,
                    dict(action=action, modified=item['modified'], request_id=str(uuid.uuid4()), prompt='Golden light'))
                assert 'batch_id' not in result['job'] and 'batch_count' not in result['job']
            assert len(stub.submissions) == 2
            assert await (await client.get('/api/presets')).json() == picker
            assert len(service.presets.list(include_internal=True)) == 3
            assert await service.describe(service.presets.get(main['id'])) == before
            assert service.presets.get(main['id'])['graph'] == graph
            assert fields_for(service.presets.get(main['id']), stub.object_info)[0]['role'] == 'positive'
            assert not any('generation_role' in field or 'resolution_role' in field for field in before['fields'])
            # Omitted queue-redesign endpoints stay absent.
            assert (await client.post('/api/queue/cancel', json={}, headers={'Origin': str(client.make_url('/')).rstrip('/')})).status == 404
        finally:
            await client.close()
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())
