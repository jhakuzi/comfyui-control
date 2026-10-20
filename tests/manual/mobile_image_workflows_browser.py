"""Real-browser saved-image workflow actions against an explicit protocol fixture."""
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
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_workflows import ImageWorkflowStub, picture
from test_mobile_integration import until


async def main(browser_name, root):
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'output'
    picture(output / 'older.png')
    picture(output / 'latest.png', 0xffaa7733)
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='CustomPrompt', inputs={'text': 'saved main prompt'}),
             'sampler': dict(class_type='CustomSampler', inputs={'seed': 42, 'steps': 20, 'prompt': ['text', 0]})}
    stub.object_info.update({node['class_type']: {'input': {}} for node in graph.values()})
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    preset = service.presets.create('Main generation', graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt'),
                                               dict(node='sampler', input='seed', role='seed', key='seed')])
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
            browser = await getattr(playwright, browser_name).launch(headless=True,
                **({'args': ['--no-sandbox']} if browser_name == 'chromium' else {}))
            context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(url)
            await page.locator('#preset').select_option(preset['id'])
            prompt = page.locator('[data-role="positive"]')
            await prompt.fill('Keep my unsent main draft')
            await page.get_by_role('button', name='View older.png', exact=True).click()
            edit = page.locator('#selected-image-actions [data-action="edit"]')
            await expect(edit).to_be_enabled()
            await edit.click()
            await expect(page.locator('#edit-image-source')).to_have_text('older.png')
            await page.locator('#edit-image-prompt').fill('Soft golden light')
            await page.locator('#cancel-edit-image').click()
            assert not stub.submissions and not stub.uploads
            await edit.click()
            await expect(page.locator('#edit-image-prompt')).to_have_value('Soft golden light')
            await page.locator('#edit-image-form button[type="submit"]').click()
            await expect(page.locator('#job-detail')).to_contain_text(IMAGE_WORKFLOWS['edit']['name'])
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            assert len(stub.submissions) == len(stub.uploads) == 1
            expected = deepcopy(stub.saved[IMAGE_WORKFLOWS['edit']['name'] + '.json'])
            expected['88']['inputs']['image'] = stub.uploads[0]['name']
            expected['89']['inputs']['prompt'] = 'Soft golden light'
            assert stub.submissions[0]['prompt'] == expected
            await expect(prompt).to_have_value('Keep my unsent main draft')
            await expect(page.locator('#preset')).to_have_value(preset['id'])
            # The header panel is only visible for active jobs and supports
            # reduced-motion settings without losing any live statistics.
            panel = page.locator('#header-generation')
            await expect(panel).to_be_visible()
            assert await panel.evaluate('el => getComputedStyle(el).borderTopWidth') == '1px'
            await page.emulate_media(reduced_motion='reduce')
            assert await panel.evaluate('el => getComputedStyle(el).transitionDuration') == '0s'
            await page.emulate_media(reduced_motion='no-preference')
            job = list(service.jobs.values())[-1]
            stub.running, stub.pending = stub.pending, []
            await service.refresh()
            await stub.emit('execution_start', {'prompt_id': job['prompt_id']})
            await stub.emit('progress', {'prompt_id': job['prompt_id'], 'value': 3, 'max': 10})
            await expect(page.locator('#job-detail')).to_contain_text('3 / 10')
            await page.screenshot(path=str(root / 'edit-progress-desktop.png'))
            await page.reload()
            await expect(page.locator('#job-detail')).to_contain_text('3 / 10')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Keep my unsent main draft')
            assert len(stub.submissions) == 1
            # Complete through the same queue/history path as normal generation.
            picture(output / 'edited.png', 0xff776699)
            stub.running = []
            stub.history[job['prompt_id']] = {'prompt': [1, job['prompt_id'], expected, {}, []],
                'outputs': {'result': {'images': [{'filename': 'edited.png', 'subfolder': '', 'type': 'output'}]}},
                'status': {'completed': True, 'status_str': 'success', 'messages': []}}
            await service.refresh()
            await expect(page.locator('#selected-image-name')).to_have_text('edited.png')
            await expect(panel).to_be_hidden()
            # Losing the HTTP response after queuing an upscale must reuse the
            # same persistent request UUID, including after a page refresh.
            await page.get_by_role('button', name='View older.png', exact=True).click()
            lost = {'once': True}
            async def lose_response(route):
                if route.request.method == 'POST' and lost['once']:
                    lost['once'] = False
                    await route.fetch()
                    await route.abort()
                else:
                    await route.continue_()
            await page.route('**/api/images/*/actions', lose_response)
            await page.locator('#selected-image-actions [data-action="upscale"]').click()
            await until(lambda: len(stub.submissions) == 2)
            await page.reload()
            await expect(page.locator('#job-detail')).to_contain_text(IMAGE_WORKFLOWS['upscale']['name'])
            assert len(stub.submissions) == len(stub.uploads) == 2
            assert await page.evaluate('JSON.parse(localStorage.getItem("comfy-mobile-pending"))') is None
            # Compact phone view retains the existing viewer actions; the edit
            # dialog fits and preserves the prompt when the phone is refreshed.
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.locator('#gallery-tab').click()
            await page.get_by_role('button', name='View latest.png', exact=True).click()
            await page.locator('#viewer-image-actions [data-action="edit"]').click()
            await expect(page.locator('#edit-image-source')).to_have_text('latest.png')
            await page.locator('#edit-image-prompt').fill('A phone edit draft')
            await page.screenshot(path=str(root / 'edit-dialog-phone.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.reload()
            await page.locator('#gallery-tab').click()
            await page.get_by_role('button', name='View latest.png', exact=True).click()
            await page.locator('#viewer-image-actions [data-action="edit"]').click()
            await expect(page.locator('#edit-image-prompt')).to_have_value('A phone edit draft')
            await page.locator('#cancel-edit-image').click()
            assert len(stub.submissions) == 2
            # Reproduce both reported editor-format failures. Instructions stay
            # readable beside the image, rather than vanishing with a toast.
            edit_name = IMAGE_WORKFLOWS['edit']['name'] + '.json'
            edit_api = deepcopy(stub.saved[edit_name])
            stub.saved[edit_name] = {'nodes': [{'id': 88, 'type': 'LoadImage',
                'widgets_values': ['saved.png', {'custom': 'upload widget'}]}], 'links': []}
            await page.locator('#viewer-image-actions [data-action="edit"]').click()
            await page.locator('#edit-image-form button[type="submit"]').click()
            await expect(page.locator('#viewer-image-actions .image-action-status')).to_contain_text('VeryComfy_Qwen21_Turbo_EDIT_ONLY.api.json')
            await expect(page.locator('#image-dialog')).to_be_visible()
            await page.locator('#notice').evaluate('el => el.hidden=true')
            await expect(page.locator('#viewer-image-actions .image-action-status')).to_be_visible()
            assert len(stub.submissions) == 2 and len(stub.uploads) == 2
            stub.saved[edit_name.removesuffix('.json') + '.api.json'] = edit_api
            await page.locator('#viewer-image-actions [data-action="edit"]').click()
            await expect(page.locator('#edit-image-prompt')).to_have_value('A phone edit draft')
            await page.locator('#edit-image-form button[type="submit"]').click()
            await expect(page.locator('#image-dialog')).to_be_hidden()
            await until(lambda: len(stub.submissions) == 3)
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            upscale_name = IMAGE_WORKFLOWS['upscale']['name'] + '.json'
            upscale_api = deepcopy(stub.saved[upscale_name])
            stub.saved[upscale_name] = {'nodes': [{'id': 1, 'type': 'LoadImage', 'widgets_values': ['saved.png']}],
                'links': [], 'definitions': {'subgraphs': [{'id': 'custom-editor-subgraph', 'nodes': []}]}}
            await page.get_by_role('button', name='View older.png', exact=True).click()
            await page.locator('#selected-image-actions [data-action="upscale"]').click()
            await expect(page.locator('#selected-image-actions .image-action-status')).to_contain_text('OfficialComfy-SeedVR_Upscaler.api.json')
            await expect(page.locator('#selected-image-panel')).to_be_visible()
            assert len(stub.submissions) == 3
            stub.saved[upscale_name.removesuffix('.json') + '.api.json'] = upscale_api
            await page.locator('#selected-image-actions [data-action="upscale"]').click()
            await until(lambda: len(stub.submissions) == 4)
            assert (output / 'older.png').is_file() and (output / 'latest.png').is_file()
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{browser_name}: edit/upscale, explicit source, graph preservation, drafts, progress, reload, lost response, persistent format errors and API companion recovery passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
