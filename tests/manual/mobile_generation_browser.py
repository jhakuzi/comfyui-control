"""Generation controls, exact seed reuse and batch queueing with protocol fixtures."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings, save_json
from comfyui_control.mobile.workflows import fields_for, suggested_mappings
from test_mobile_integration import ComfyStub, until
from test_generation_controls import generation_workflow
from test_resolution_controls import controlaltai_resolution


async def main(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    graph, info = generation_workflow.__wrapped__(controlaltai_resolution.__wrapped__())
    original = deepcopy(graph)
    stub = ComfyStub(graph)
    stub.object_info = info
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root / 'out')
    preset = service.presets.create('VeryComfy generation controls', graph)
    mappings = [m for m in suggested_mappings(graph, info) if m['role'] not in {'steps', 'sampler', 'scheduler', 'seed', 'batch'}]
    next(m for m in mappings if m['role'] == 'cfg').update(role='advanced', key='keep-cfg')
    preset = service.presets.map(preset['id'], mappings)
    preset.pop('generation_controls_version')
    save_json(service.presets.path(preset['id']), preset)
    draft = {'revision': revision(preset), 'fields': fields_for(preset, info), 'mappings': mappings,
             'values': {f['key']: 'Preserve my prompt' if f['role'] == 'positive'
                        else 4.25 if f['key'] == 'keep-cfg' else f['default'] for f in fields_for(preset, info)}}
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
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080}, service_workers='block')
            key = json.dumps('comfy-mobile-draft-' + preset['id'])
            await context.add_init_script(f'if (!localStorage.getItem({key})) localStorage.setItem({key},{json.dumps(json.dumps(draft))});')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            await page.goto(url)
            panel = page.locator('#settings-card')
            await expect(panel).to_have_js_property('open', True)
            for role in ('steps', 'cfg', 'sampler', 'scheduler', 'seed', 'batch'):
                await expect(panel.locator(f'[data-role="{role}"]')).to_be_visible()
            await expect(page.locator('#control-keep-cfg')).to_have_value('4.25')
            await expect(page.locator('#reuse-last-seed')).to_be_disabled()
            await expect(page.locator('#random-seed')).to_be_checked()
            await panel.locator('[data-role="sampler"]').select_option('dpmpp_2m')
            await panel.locator('[data-role="scheduler"]').select_option('karras')
            await panel.locator('[data-role="steps"]').fill('24')
            await panel.locator('[data-role="cfg"]').fill('4.5')
            await page.locator('#random-seed').uncheck()
            exact_seed = '18446744073709551599'
            await panel.locator('[data-role="seed"]').fill(exact_seed)
            await panel.locator('[data-role="batch"]').fill('3')
            await page.locator('#batch-count').fill('2')
            await page.reload()
            await expect(page.locator('#batch-count')).to_have_value('2')
            await expect(panel.locator('[data-role="seed"]')).to_have_value(exact_seed)
            await expect(page.locator('#random-seed')).not_to_be_checked()
            await page.evaluate('window.scrollTo(0,0)')
            await page.screenshot(path=str(root / 'generation-desktop.png'), full_page=True)
            for width, height in [(320, 844), (390, 844), (1024, 768), (1440, 900)]:
                await page.set_viewport_size({'width': width, 'height': height})
                await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop' if width >= 1024 else 'mobile')
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await expect(page.locator('#batch-count')).to_have_value('2')
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 2)
            for post in stub.submissions:
                assert post['prompt']['3']['inputs']['seed'] == int(exact_seed)
                assert post['prompt']['3']['inputs']['cfg'] == 4.5
                assert post['prompt']['3']['inputs']['sampler_name'] == 'dpmpp_2m'
                assert post['prompt']['3']['inputs']['scheduler'] == 'karras'
                assert post['prompt']['60']['inputs'] == {'width': ['59', 0], 'height': ['59', 1], 'batch_size': 3}
            await page.reload()
            await expect(page.locator('#job-detail')).to_contain_text('Batch 1/2')
            assert len(stub.submissions) == 2
            first = list(service.jobs.values())[0]
            record = stub.pending.pop(0)
            stub.history[first['prompt_id']] = {'prompt': record, 'outputs': {}, 'status': {'status_str': 'success'}}
            await service.refresh()
            await expect(page.locator('#job-detail')).to_contain_text('Batch 2/2')
            await expect(page.locator('#generate')).to_be_disabled()
            await page.locator('[data-role="positive"]').fill('Keep this new draft while reusing only the seed')
            await panel.locator('[data-role="cfg"]').fill('5.5')
            await page.locator('#random-seed').check()
            await page.locator('#reuse-last-seed').click()
            await expect(page.locator('#random-seed')).not_to_be_checked()
            await expect(panel.locator('[data-role="seed"]')).to_have_value(exact_seed)
            await expect(panel.locator('[data-role="cfg"]')).to_have_value('5.5')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Keep this new draft while reusing only the seed')
            # Cancel the remaining batch without cancelling another browser's job.
            current = service.presets.get(preset['id'])
            other = await service.submit({'request_id': str(uuid.uuid4()), 'preset': current['id'],
                'revision': revision(current), 'values': {}}, owner='other-browser')
            await page.locator('#cancel').click()
            await expect(page.locator('#generate')).to_be_enabled()
            assert len(stub.pending) == 1 and stub.pending[0][1] == other['prompt_id']
            await page.locator('#batch-count').fill('1')
            await page.locator('#random-seed').check()
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 4)
            random_value = stub.submissions[-1]['prompt']['3']['inputs']['seed']
            assert 0 <= random_value <= 2**53 - 1
            assert service.presets.get(preset['id'])['graph'] == original
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: full generation panel, mapping/draft upgrade, CFG/sampler/scheduler, exact fixed and reused seeds, random seeds, batch count/size, reload, progress and scoped cancellation passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
