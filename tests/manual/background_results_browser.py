"""Background completion, overtaken full-state responses and sampling tab title."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings, save_json
from test_mobile_integration import ComfyStub, until


async def check(browser, engine, output, viewport):
    output.mkdir(parents=True)
    images = output / 'images'
    images.mkdir()
    for name, colour in [('old.png', 0xff446688), ('new.png', 0xffaa6611)]:
        image = QImage(64, 96, QImage.Format.Format_RGB32)
        image.fill(colour)
        assert image.save(str(images / name))
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Original'})}
    stub = ComfyStub(graph)
    stub.saved['Background.json'] = graph
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Background', graph)
    preset = service.presets.map(preset['id'], [dict(key='prompt', node='text', input='text', role='positive', label='Prompt')])
    preset['comfy_source'] = 'Background.json'
    save_json(service.presets.path(preset['id']), preset)
    mobile = TestServer(MobileHTTP(service).app())
    context = await browser.new_context(viewport=viewport, service_workers='block')
    page = await context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        await service.start()
        await until(lambda: service.online)
        await mobile.start_server()
        await page.goto(str(mobile.make_url('/')))
        await expect(page.locator('#generate')).to_be_enabled()
        title = await page.title()
        async def start():
            await page.locator('#generate').click()
            await until(lambda: len(service.jobs) > len(stub.history))
            job = list(service.jobs.values())[-1]
            stub.running, stub.pending = stub.pending, []
            await service.refresh()
            await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
            return job
        async def complete(job, filename):
            stub.history[job['prompt_id']] = dict(prompt=stub.running[-1], status=dict(status_str='success'),
                outputs={'save': {'images': [dict(filename=filename, subfolder='', type='output')]}})
            stub.running = []
            await service.refresh()
        first = await start()
        await complete(first, 'old.png')
        await expect(page.locator('#job-images img')).to_have_attribute('alt', 'old.png')
        await expect(page.locator('#generate')).to_be_enabled()
        # Another Comfy Control tab/window retains the earlier selected job in
        # memory. It must follow new work by this same browser session as well.
        returning = await context.new_page()
        await returning.goto(str(mobile.make_url('/')))
        await expect(returning.locator('#job-images img')).to_have_attribute('alt', 'old.png')
        await page.bring_to_front()
        second = await start()
        await stub.emit('progress', dict(prompt_id=second['prompt_id'], value=10, max=40))
        await expect(page).to_have_title('25% · ' + title)
        await page.locator('[data-role="positive"]').fill('Unsent edits survive returning to this tab')
        await page.locator('#gallery-tab').click()
        await page.locator('#create-tab').click()
        # Simulated hidden tab; retain the existing stream, without a new poller.
        await page.evaluate('''() => {
            Object.defineProperty(document, 'hidden', {configurable:true, value:true});
            document.dispatchEvent(new Event('visibilitychange'));
        }''')
        await stub.emit('progress', dict(prompt_id=second['prompt_id'], value=26, max=40))
        await expect(page).to_have_title('65% · ' + title)
        count = 0
        async def overtaken(route):
            nonlocal count
            response = await route.fetch()
            data = await response.json()
            count += 1
            # A newer summary arrives before every full response. Old code keeps
            # rejecting image details and endlessly retries, retaining old.png.
            service.broadcast()
            await page.wait_for_function('(v) => state.version > v', arg=data['version'])
            await route.fulfill(response=response)
        await page.route('**/api/state', overtaken)
        await complete(second, 'new.png')
        await expect(page.locator('#job-images img')).to_have_attribute('alt', 'new.png')
        assert count <= 3, count
        await expect(page).to_have_title(title)
        await returning.bring_to_front()
        await returning.evaluate('window.dispatchEvent(new Event("focus"))')
        await expect(returning.locator('#job-images img')).to_have_attribute('alt', 'new.png')
        await returning.evaluate('(id) => localStorage.setItem("comfy-mobile-job", JSON.stringify(id))', first['id'])
        await returning.reload()
        await expect(returning.locator('#job-images img')).to_have_attribute('alt', 'new.png')
        await returning.close()
        await page.bring_to_front()
        await page.unroute('**/api/state', overtaken)
        # Real suspension/BFCache uses pagehide and resumes with a full snapshot.
        await page.evaluate('''() => {
            window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}));
            Object.defineProperty(document, 'hidden', {configurable:true, value:false});
            window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));
            document.dispatchEvent(new Event('visibilitychange'));
        }''')
        await expect(page.locator('#generate')).to_be_enabled()
        await expect(page.locator('#job-images img')).to_have_attribute('alt', 'new.png')
        await expect(page.locator('[data-role="positive"]')).to_have_value('Unsent edits survive returning to this tab')
        assert len(stub.submissions) == 2
        # Invalid/indeterminate/reconnecting states never invent a percentage.
        for progress, phase, online in [(None, 'loading', True), ({'value':1,'max':0}, 'sampling', True),
                                        ({'value':2,'max':4}, 'processing', True), ({'value':2,'max':4}, 'sampling', False)]:
            second.update(status='running', progress=progress, phase=phase)
            service.online = online
            service.broadcast()
            await expect(page).to_have_title(title)
        assert not errors, errors
        await page.screenshot(path=str(output / 'returned-result.png'))
    finally:
        await context.close()
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine} {viewport["width"]}: background title progress, overtaken completion details, resume, drafts and no duplicate submissions passed')


async def main(engine, output):
    async with async_playwright() as pw:
        browser = await getattr(pw, engine).launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                await check(browser, engine, output / str(width), dict(width=width, height=height))
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['chromium', 'webkit', 'firefox'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
