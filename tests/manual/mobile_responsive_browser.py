"""Responsive layout checks in real browser engines with a ComfyUI protocol fixture.

No physical iPad/iPhone, VPN, GPU inference, or real model loading is exercised.
"""
import argparse
import asyncio
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QColor, QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub


async def main(browser_name, root):
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'output'
    output.mkdir(exist_ok=True)
    for number in range(16):
        image = QImage(192, 256, QImage.Format.Format_RGB32)
        image.fill(QColor.fromHsv(number * 20, 100, 160))
        assert image.save(str(output / f'image{number:02}.png'))
    graph = {
        'text': dict(class_type='CustomPrompt', inputs=dict(text='A quiet mountain lake')),
        'model': dict(class_type='CustomGGUF', inputs=dict(file='model.gguf')),
        'lora': dict(class_type='CustomLoRA', inputs=dict(model=['model', 0], strength=.7)),
        'sampler': dict(class_type='CustomSampler', inputs=dict(prompt=['text', 0], seed=42, steps=20, cfg=5.5, width=768, height=1024)),
    }
    stub = ComfyStub(graph)
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    preset = service.presets.create('Quantized workflow', graph)
    mappings = []
    for node, field, role in [('text', 'text', 'positive'), ('model', 'file', 'model'), ('lora', 'strength', 'lora_strength'),
                              ('sampler', 'seed', 'seed'), ('sampler', 'steps', 'steps'), ('sampler', 'cfg', 'cfg'),
                              ('sampler', 'width', 'width'), ('sampler', 'height', 'height')]:
        mappings.append(dict(node=node, input=field, role=role, label=field.title(), key=f'm-{len(mappings)}'))
    preset = service.presets.map(preset['id'], mappings)
    await service.start()
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
            context = await browser.new_context(viewport=dict(width=1440, height=900), service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(url)
            await expect(page.locator('#generation-empty')).to_be_visible()
            await page.locator('#preset').select_option(preset['id'])
            prompt = page.locator('[data-role="positive"]')
            await expect(prompt).to_be_visible()
            await prompt.fill('An unsent draft survives resizing')

            async def layout(width, height, wide):
                await page.set_viewport_size(dict(width=width, height=height))
                await page.evaluate('window.scrollTo(0,0)')
                await expect(page.locator('#generate')).to_be_visible()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                form = await page.locator('#generate-form').bounding_box()
                panel = await page.locator('#generation-panel').bounding_box()
                if wide:
                    assert panel['x'] >= form['x'] + form['width'] + 20, (form, panel)
                    assert panel['width'] >= 350
                    card = await page.locator('#generate-form > .card').first.bounding_box()
                    assert abs(card['y'] - panel['y']) < 1, (card, panel)
                else:
                    assert await page.locator('#generation-dock').evaluate('el => getComputedStyle(el).position') == 'fixed'
                await expect(prompt).to_have_value('An unsent draft survives resizing')

            for width, height, wide in [(320, 568, False), (390, 844, False), (844, 390, False), (834, 1194, False),
                                         (1024, 1366, True), (1194, 834, True), (1366, 1024, True), (1440, 900, True),
                                         (1000, 600, True), (1440, 500, False)]:
                await layout(width, height, wide)
            await layout(1440, 900, True)
            # Keyboard activation opens a normal control without submitting.
            await page.locator('#prompt-history').focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#prompt-history-dialog')).to_be_visible()
            await page.locator('#close-prompt-history').click()
            assert not stub.submissions
            await page.locator('#generate').click()
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            assert len(stub.submissions) == 1
            stub.running, stub.pending = stub.pending, []
            job = list(service.jobs.values())[-1]
            await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
            await stub.emit('executing', dict(prompt_id=job['prompt_id'], node='model'))
            await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=4, max=20))
            for ws in stub.sockets:
                await ws.send_bytes(struct.pack('>II', 1, 2) + (output / 'image00.png').read_bytes())
            await expect(page.locator('#preview')).to_be_visible()
            await page.locator('#advanced').evaluate('el => el.open=true')
            await page.locator('#mapping').evaluate('el => el.open=true')

            async def reachable(identifiers=('generate', 'progress', 'cancel')):
                for identifier in identifiers:
                    bounds = await page.locator('#' + identifier).bounding_box()
                    assert bounds and bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= page.viewport_size['height'] + 1, (identifier, bounds)
                    assert await page.evaluate('({x,y,id}) => !!document.elementFromPoint(x,y)?.closest("#"+id)',
                        dict(id=identifier, x=bounds['x'] + bounds['width']/2, y=bounds['y'] + bounds['height']/2))

            for width, height in [(1024, 1366), (1366, 1024), (1440, 900), (1000, 600), (390, 844)]:
                await page.set_viewport_size(dict(width=width, height=height))
                for scroll in (0, 800, 100000):
                    await page.evaluate('(y) => window.scrollTo(0,y)', scroll)
                    await page.wait_for_timeout(60)
                    await reachable()
                await page.evaluate('window.scrollTo(0,0)')
                await page.screenshot(path=str(root / f'progress-{width}.png'))
            # An NFS fallback warning must not push the wide preview/Generate
            # controls out of reach before the user has scrolled the page.
            service.output_status = dict(destination='local_fallback', level='warning', title='Local fallback — manual upload required',
                error='NAS is offline', message='Images are saved locally. Upload these images to your network storage manually.')
            service.broadcast()
            await expect(page.locator('#output-warning')).to_be_visible()
            await page.set_viewport_size(dict(width=1000, height=600))
            await page.evaluate('window.scrollTo(0,0)')
            await reachable()
            service.output_status = {}
            service.broadcast()
            await page.set_viewport_size(dict(width=1440, height=900))
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#gallery-grid button')).to_have_count(16)
            assert await page.locator('#gallery-grid').evaluate('el => getComputedStyle(el).gridTemplateColumns.split(" ").length') == 4
            await page.evaluate('window.scrollTo(0,100000)')
            await reachable()
            await page.locator('#select-compare').click()
            await page.locator('#gallery-grid button').nth(0).click()
            await page.locator('#gallery-grid button').nth(1).click()
            await page.locator('#compare-images').click()
            await expect(page.locator('#compare-viewport')).to_be_visible()
            assert (await page.locator('#compare-dialog').bounding_box())['width'] > 1000
            await page.locator('#compare-slider').focus()
            await page.keyboard.press('ArrowRight')
            await expect(page.locator('#compare-slider')).to_have_value('51')
            await page.screenshot(path=str(root / 'comparison-laptop.png'))
            await page.locator('#close-compare').click()
            await page.locator('#create-tab').click()
            await page.evaluate('window.scrollTo(0,0)')
            await context.set_offline(True)
            stub.history[job['prompt_id']] = dict(prompt=stub.running[0], status=dict(status_str='success'),
                outputs=dict(save=dict(images=[dict(filename='image00.png', subfolder='', type='output')])))
            stub.running = []
            await stub.emit('execution_success', dict(prompt_id=job['prompt_id']))
            await asyncio.sleep(.2)
            await context.set_offline(False)
            await expect(page.locator('#job-output #job-images img')).to_be_visible()
            await expect(page.locator('#job-title')).to_have_text('Your image is ready')
            await page.reload()
            await expect(page.locator('#job-images img')).to_be_visible()
            await expect(prompt).to_have_value('An unsent draft survives resizing')
            await reachable(('generate', 'same-seed', 'variation'))
            assert len(stub.submissions) == 1
            await page.screenshot(path=str(root / 'result-laptop.png'))
            # A separate touch-capable tablet client starts clean and rotates
            # between wide and Split View layouts without losing its own draft.
            tablet = await browser.new_context(viewport=dict(width=1024, height=1366), is_mobile=True, has_touch=True, service_workers='block')
            touch = await tablet.new_page()
            touch.on('pageerror', lambda error: errors.append(str(error)))
            await touch.goto(url)
            await touch.locator('#preset').select_option(preset['id'])
            await touch.locator('[data-role="positive"]').fill('Tablet draft')
            await touch.locator('.prompt-editor-toggle').tap()
            await expect(touch.locator('.prompt-editor-toggle')).to_have_attribute('aria-expanded', 'true')
            for width, height in [(1024, 1366), (1366, 1024), (744, 1024)]:
                await touch.set_viewport_size(dict(width=width, height=height))
                await expect(touch.locator('[data-role="positive"]')).to_have_value('Tablet draft')
                assert await touch.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert await touch.locator('#job-card').is_hidden()
            await tablet.close()
            assert not errors, errors
            print(json.dumps(dict(browser=browser_name, responsive_layout='phone, tablet portrait/landscape, Split View, laptop, short window',
                generation='fixture: model loading, progress/preview, sticky controls, offline completion and reload',
                gallery='4 columns, keyboard comparison, accessible close', tablet='touch expansion, rotation, isolated draft', javascript_errors=errors)))
            await browser.close()
    finally:
        await service.stop()
        await runner.cleanup()
        await upstream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    parser.add_argument('--output', type=Path, default=Path(tempfile.mkdtemp(prefix='mobile-responsive-')))
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
