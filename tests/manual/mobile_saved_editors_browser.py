"""Browser Edit/Upscale checks using redacted versions of the supplied workflows.

ComfyUI HTTP/WS is a protocol fixture; no GPU/model inference is performed.
"""
import argparse
import asyncio
from copy import deepcopy
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.image_actions import IMAGE_WORKFLOWS
from comfyui_control.mobile.workflow_sources import editor_to_api
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_workflows import ImageWorkflowStub, picture
from test_editor_workflow_compatibility import fixture, metadata
from test_mobile_integration import until


async def main(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'output'
    picture(output / 'source.png')
    stub = ImageWorkflowStub()
    stub.saved = {IMAGE_WORKFLOWS[role]['name'] + '.json': fixture(source)
                  for role, source in [('edit','qwen-editor'), ('upscale','seedvr-editor')]}
    originals = deepcopy(stub.saved)
    stub.object_info = metadata()
    stub.image_names = stub.object_info['LoadImage']['input']['required']['image'][0]
    stub.object_info['CustomPrompt'] = {'input': {'required': {'text': ['STRING']}}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    main_graph = {'text': dict(class_type='CustomPrompt', inputs={'text': 'Main prompt'})}
    preset = service.presets.create('Main generation', main_graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt')])
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch(headless=True,
                **({'args': ['--no-sandbox']} if engine == 'chromium' else {}))
            context = await browser.new_context(viewport={'width':1440, 'height':1000}, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(url)
            await page.locator('#preset').select_option(preset['id'])
            await page.locator('[data-role="positive"]').fill('Preserve my normal generation draft')
            await page.get_by_role('button', name='View source.png', exact=True).click()
            await page.locator('#selected-image-actions [data-action="edit"]').click()
            await page.locator('#edit-image-prompt').fill('Adjust the lighting')
            await page.locator('#edit-image-form button[type="submit"]').click()
            await until(lambda: len(stub.submissions) == 1)
            expected = editor_to_api(fixture('qwen-editor'), stub.object_info)
            expected['88']['inputs']['image'] = stub.uploads[0]['name']
            expected['89']['inputs']['prompt'] = 'Adjust the lighting'
            assert stub.submissions[0]['prompt'] == expected
            assert expected['90']['inputs']['model'] == ['99',0]
            await expect(page.locator('#preset')).to_have_value(preset['id'])
            await expect(page.locator('[data-role="positive"]')).to_have_value('Preserve my normal generation draft')
            job = next(iter(service.jobs.values()))
            picture(output / 'edited.png', 0xff886699)
            stub.pending = []
            stub.history[job['prompt_id']] = {'prompt':[1,job['prompt_id'],expected,{},[]],
                'outputs': {'97': {'images':[dict(filename='edited.png',subfolder='',type='output')]}},
                'status': {'completed':True,'status_str':'success','messages':[]}}
            await service.refresh()
            await expect(page.locator('#selected-image-name')).to_have_text('edited.png')
            await page.locator('#selected-image-actions [data-action="upscale"]').click()
            await page.locator('#upscale-image-multiplier').fill('1.5')
            await page.locator('#upscale-image-form button[type="submit"]').click()
            await until(lambda: len(stub.submissions) == 2)
            expected = editor_to_api(fixture('seedvr-editor'), stub.object_info)
            expected['1']['inputs']['image'] = stub.uploads[1]['name']
            expected['66:57']['inputs']['resize_type.multiplier'] = 1.5
            assert stub.submissions[1]['prompt'] == expected
            assert not any(name.endswith('.api.json') for name in stub.saved)
            await expect(page.locator('#preset')).to_have_value(preset['id'])
            await page.reload()
            await expect(page.locator('#job-detail')).to_contain_text(IMAGE_WORKFLOWS['upscale']['name'])
            await expect(page.locator('[data-role="positive"]')).to_have_value('Preserve my normal generation draft')
            assert len(stub.submissions) == 2
            await page.screenshot(path=str(root / 'saved-editor-upscale-desktop.png'))
            await page.set_viewport_size({'width':390,'height':844})
            await page.locator('#gallery-tab').click()
            await page.get_by_role('button', name='View source.png', exact=True).click()
            await page.locator('#viewer-image-actions [data-action="edit"]').click()
            await expect(page.locator('#edit-image-prompt')).to_have_value('Adjust the lighting')
            await page.locator('#cancel-edit-image').click()
            assert len(stub.submissions) == 2
            await page.locator('#close-image').click()
            await page.set_viewport_size({'width':1440,'height':1000})
            upscale_job = list(service.jobs.values())[-1]
            picture(output / 'upscaled.png', 0xff668899)
            stub.pending = []
            stub.history[upscale_job['prompt_id']] = {'prompt':[2,upscale_job['prompt_id'],expected,{},[]],
                'outputs': {'9': {'images':[dict(filename='upscaled.png',subfolder='',type='output')]}},
                'status': {'completed':True,'status_str':'success','messages':[]}}
            await service.refresh()
            await expect(page.locator('#selected-image-name')).to_have_text('upscaled.png')
            await page.locator('#reuse-selected-image').click()
            await page.locator('#advanced').evaluate('el => el.open=true')
            await expect(page.locator('#control-action-scale')).to_have_value('1.5')
            assert len(stub.submissions) == 2
            assert stub.saved == originals and (output / 'source.png').is_file() and (output / 'edited.png').is_file()
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: supplied editor structure, upload widget, dynamic Qwen images, GGUF connection, SeedVR subgraph/multiplier, draft and reload recovery passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium','webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
