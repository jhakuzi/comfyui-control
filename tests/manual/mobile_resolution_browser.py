"""ControlAltAI-style resolution combos in desktop/phone WebUI; no inference."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings, save_json
from comfyui_control.mobile.workflows import fields_for, suggested_mappings
from test_mobile_integration import ComfyStub, until
from test_resolution_controls import controlaltai_resolution


async def main(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    graph, info = controlaltai_resolution.__wrapped__()
    original = deepcopy(graph)
    stub = ComfyStub(graph)
    stub.object_info = info
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root / 'out')
    preset = service.presets.create('VeryComfy resolution', graph)
    mappings = [m for m in suggested_mappings(graph, info) if m['role'] != 'resolution_mp']
    next(m for m in mappings if m['role'] == 'alignment')['role'] = 'advanced'
    preset = service.presets.map(preset['id'], mappings)
    preset.pop('resolution_controls_version')
    save_json(service.presets.path(preset['id']), preset)
    draft = {'revision': revision(preset), 'mappings': preset['mappings'],
             'fields': fields_for(preset, info), 'values': {
                 f['key']: 'Unsent prompt survives resolution upgrade' if f['role'] == 'positive'
                 else '32' if f['input'] == 'divisible_by' else f['default']
                 for f in fields_for(preset, info)}}
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
            await page.goto(url)
            panel = page.locator('#resolution-card')
            mp = panel.locator('[data-role="resolution_mp"]')
            ratio = panel.locator('[data-role="aspect_ratio"]')
            alignment = panel.locator('[data-role="alignment"]')
            custom = panel.locator('[data-role="custom_ratio"]')
            await expect(panel).to_have_js_property('open', True)
            await expect(mp).to_have_value('2.0')
            await expect(ratio).to_have_value('2:3 (Classic Portrait)')
            await expect(alignment).to_have_value('32')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Unsent prompt survives resolution upgrade')
            assert await mp.evaluate('el => el.tagName') == 'SELECT'
            assert await mp.locator('option').count() == 25
            assert await ratio.locator('option').all_text_contents() == info['FluxResolutionNode']['input']['required']['aspect_ratio'][0]
            assert await page.locator('[data-role="width"], [data-role="height"]').count() == 0
            assert await page.locator('#advanced-controls [data-role="advanced"]').count() == 0
            await page.screenshot(path=str(root / 'resolution-desktop.png'), full_page=True)
            await mp.select_option('1.5')
            await ratio.select_option('16:9 (Panorama)')
            await alignment.select_option('16')
            await custom.check()
            await panel.locator('[data-role="custom_aspect_ratio"]').fill('7:5')
            await page.reload()
            await expect(mp).to_have_value('1.5')
            await expect(ratio).to_have_value('16:9 (Panorama)')
            await expect(custom).to_be_checked()
            await expect(panel.locator('[data-role="custom_aspect_ratio"]')).to_have_value('7:5')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await expect(panel).to_have_js_property('open', False)
            await panel.locator('summary').click()
            await expect(mp).to_be_visible()
            await mp.select_option('1.8')
            await custom.uncheck()
            for width, height in [(320, 844), (1024, 768), (1440, 900), (2560, 1440)]:
                await page.set_viewport_size({'width': width, 'height': height})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await expect(mp).to_have_value('1.8')
            await page.set_viewport_size({'width': 1440, 'height': 900})
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 1)
            sent = stub.submissions[0]['prompt']
            assert sent['59']['inputs'] == {'megapixel': '1.8', 'aspect_ratio': '16:9 (Panorama)',
                'divisible_by': '16', 'custom_ratio': False, 'custom_aspect_ratio': '7:5'}
            assert sent['60'] == original['60'] and sent['3'] == original['3']
            assert service.presets.get(preset['id'])['graph'] == original
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: resolution combos/defaults, legacy mapping and draft upgrade, desktop/phone, reload, exact submitted strings/boolean and unchanged latent links passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
