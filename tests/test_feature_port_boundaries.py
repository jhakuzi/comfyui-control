"""Presentation additions preserve shared skins, native UI and backend contracts."""
import asyncio
from copy import deepcopy
import hashlib
import json
import re
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
ACTIVE_ASSETS = {'feature_generate.js', 'feature_generate.css', 'feature_image_actions.js',
                 'feature_image_api.js', 'feature_image_workflows.js', 'presentation_desktop.js', 'presentation_desktop.css',
                 'presentation_phone.css', 'feature_gallery_library.js', 'feature_gallery_library.css', 'feature_gallery_bulk.js', 'feature_image_confirm.js'}
GENERATE_INTEGRATION = {'comfyui_control/mobile/web/' + name for name in ('index.html', 'app.js', 'sw.js')}


def test_existing_main_assets_ui_settings_and_versions_are_unchanged():
    for relative, expected in BASELINE['files'].items():
        if relative in GENERATE_INTEGRATION:
            continue
        content = (ROOT / relative).read_bytes()
        if relative == 'pyproject.toml':
            # RPM %prep substitutes Fedora's distribution name for the PyPI wheel.
            # Reverse only that exact substitution; all other bytes stay protected.
            content = content.replace(b'"PySide6>=6.7,<7"', b'"PySide6-Essentials>=6.7,<7"')
        assert hashlib.sha256(content).hexdigest() == expected, relative
    web = ROOT / 'comfyui_control/mobile/web'
    for file in web.glob('feature_*'):
        enabled = file.name in ACTIVE_ASSETS
        assert ('/' + file.name in PUBLIC) is enabled
        assert (file.name in (web / 'index.html').read_text()) is enabled
        assert (file.name in (web / 'sw.js').read_text()) is enabled
    # Strip only the authorized additions; retain the original Phone markup.
    original = (web / 'index.html').read_text()
    for asset in ACTIVE_ASSETS:
        tag = f'<link rel="stylesheet" href="/{asset}" />' if asset.endswith('.css') else f'<script src="/{asset}" defer></script>'
        original = original.replace('    ' + tag + '\n', '')
    original = re.sub(r'    <dialog id="(?:edit|upscale)-image-dialog".*?</dialog>\n', '', original, flags=re.S)
    original = original.replace('              <div id="selected-image-actions" data-desktop-slot hidden></div>\n', '').replace(
        '<div class="actions" id="preview-reuse-actions">', '<div class="actions">').replace(
        '<span id="generate-label" data-generate-label>✦ Generate</span>', '<span aria-hidden="true">✦</span> Generate')
    assert hashlib.sha256(original.encode()).hexdigest() == BASELINE['files']['comfyui_control/mobile/web/index.html']
    original_sw = (web / 'sw.js').read_text().replace('comfy-control-batch-count-runs-1', 'comfy-control-mobile-1.0.1')
    for asset in ACTIVE_ASSETS:
        original_sw = original_sw.replace(f'  "/{asset}",\n', '')
    assert hashlib.sha256(original_sw.encode()).hexdigest() == BASELINE['files']['comfyui_control/mobile/web/sw.js']
    assert {file.name for file in web.glob('presentation*')} == {'presentation_desktop.js', 'presentation_desktop.css', 'presentation_phone.css'}
    assert not (web / 'theme.css').exists()
    css = re.sub(r'/\*.*?\*/', '', (web / 'presentation_desktop.css').read_text(), flags=re.S)
    assert all(selector.strip().startswith(':where(html[data-presentation="desktop"])')
               for selector in re.findall(r'([^{}]+)\{', css))
    phone_css = re.sub(r'/\*.*?\*/', '', (web / 'presentation_phone.css').read_text(), flags=re.S)
    assert all(selector.strip().startswith(':where(html[data-presentation="mobile"])')
               for selector in re.findall(r'([^{}]+)\{', phone_css)
               if not selector.strip().startswith('@media '))


def test_feature_assets_are_public_and_existing_component_skins_stay_frozen(tmp_path):
    async def scenario():
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            for file in (ROOT / 'comfyui_control/mobile/web').glob('feature_*'):
                assert (await client.get('/' + file.name)).status == (200 if file.name in ACTIVE_ASSETS else 404)
            for name in ('style.css', 'prompt_history.js', 'comparison.js', 'image_details.js', 'manifest.webmanifest'):
                response = await client.get('/' if name == 'index.html' else '/' + name)
                assert response.status == 200
                expected = BASELINE['files']['comfyui_control/mobile/web/' + name]
                assert hashlib.sha256(await response.read()).hexdigest() == expected
            assert (await client.get('/presentation_phone.css')).status == 200
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
