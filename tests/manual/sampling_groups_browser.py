"""Verify desktop sampling groups and reversible phone layout with a disposable backend."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from test_mobile_integration import ComfyStub, until
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.settings import MobileSettings


def make_graph():
    graph = {}
    for index in ('1', '2'):
        for prefix, kind, inputs in [('n', 'Noise', {'noise_seed': int(index)}),
                ('s', 'Select', {'sampler_name': 'test'}), ('g', 'Guider', {'cfg': 1}),
                ('d', 'Scheduler', {'scheduler': 'normal', 'steps': 3})]:
            graph[prefix + index] = {'class_type': kind, 'inputs': inputs}
        graph['stage' + index] = {'class_type': 'Sampler', 'inputs': {
            'noise': ['n' + index, 0], 'sampler': ['s' + index, 0],
            'guider': ['g' + index, 0], 'sigmas': ['d' + index, 0]}}
    graph['stage2']['inputs']['latent_image'] = ['stage1', 0]
    return graph


async def main(engine, output):
    output.mkdir(parents=True, exist_ok=True)
    graph = make_graph()
    stub = ComfyStub(graph)
    stub.saved['Fixture.json'] = graph
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output / 'images')
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            page = await browser.new_page(viewport={'width': 1440, 'height': 900}, service_workers='block')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto('http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]) + '/')
            await expect(page.locator('#settings-card')).to_be_visible()
            await page.locator('#settings-card summary').click()
            await expect(page.locator('.desktop-sampling-group')).to_have_count(2)
            for index in (1, 2):
                group = page.locator('.desktop-sampling-group').nth(index - 1)
                await expect(group.locator('h3')).to_have_text('Sampling stage ' + str(index))
                assert await group.locator('[data-role]').evaluate_all('(items) => items.map(item => item.dataset.role)') == ['sampler', 'scheduler', 'steps', 'cfg', 'seed']
            step = page.locator('.desktop-sampling-group').first.locator('[data-role="steps"]')
            await step.fill('7')
            await page.screenshot(path=str(output / 'desktop.png'))
            seed = page.locator('[data-role="seed"]').first
            await page.set_viewport_size({'width': 390, 'height': 844})
            await expect(page.locator('.desktop-sampling-group')).to_have_count(0)
            assert await page.locator('#basic-controls > .control').count() == 10
            await expect(page.locator('[data-role="steps"]').first).to_have_value('7')
            await page.set_viewport_size({'width': 1440, 'height': 900})
            await expect(page.locator('.desktop-sampling-group')).to_have_count(2)
            await expect(page.locator('.desktop-sampling-group').first.locator('[data-role="steps"]')).to_have_value('7')
            assert await seed.count() == 1
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: sampling groups and phone restoration passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
