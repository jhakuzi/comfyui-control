"""Frame-level Desktop submission checks against a protocol fixture, without GPU."""
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

async def main(engine, output):
    output.mkdir(parents=True)
    images = output / 'images'
    images.mkdir()
    image = QImage(64, 96, QImage.Format.Format_RGB32)
    image.fill(0xff446688)
    assert image.save(str(images / 'result.png'))
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Submission stability'})}
    stub = ComfyStub(graph)
    stub.saved['Transition.json'] = graph
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Transition', graph)
    preset = service.presets.map(preset['id'], [dict(key='prompt', node='text', input='text', role='positive', label='Prompt')])
    preset['comfy_source'] = 'Transition.json'
    save_json(service.presets.path(preset['id']), preset)
    mobile = TestServer(MobileHTTP(service).app())
    errors = []
    try:
        await service.start()
        await until(lambda: service.online)
        await mobile.start_server()
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            page = await browser.new_page(viewport=dict(width=1440, height=1000), service_workers='block')
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(str(mobile.make_url('/')))
            await expect(page.locator('#generate')).to_be_enabled()
            for phase in ('first', 'completed'):
                started, release = asyncio.Event(), asyncio.Event()
                async def hold(route):
                    started.set()
                    await release.wait()
                    await route.continue_()
                await page.route('**/api/generate', hold)
                await page.evaluate('window.scrollTo(0,0)')
                before = await page.locator('#desktop-result-preview').bounding_box()
                await page.locator('#generate').click()
                await asyncio.wait_for(started.wait(), 5)
                try:
                    frames = await page.evaluate('''async () => {
                        const frames = [];
                        for (let i=0; i<4; i++) {
                            await new Promise(requestAnimationFrame);
                            const r = document.getElementById('desktop-result-preview').getBoundingClientRect();
                            frames.push({rect:{x:r.x,y:r.y,width:r.width,height:r.height},
                                progress:[...document.querySelectorAll('progress')].filter(el => el.getClientRects().length && el.getBoundingClientRect().height > 0).map(el => el.id || el.parentElement.id)});
                        }
                        return frames;
                    }''')
                    await page.screenshot(path=str(output / f'{phase}-submitting.png'))
                    assert all(not frame['progress'] for frame in frames), frames
                    assert all(frame['rect'] == before for frame in frames), (before, frames)
                    await expect(page.locator('#generate')).to_have_attribute('data-progress', 'indeterminate')
                    await expect(page.locator('#generate')).to_be_disabled()
                    if phase == 'completed':
                        await expect(page.locator('#desktop-result-preview img')).to_be_visible()
                    await page.set_viewport_size(dict(width=390, height=844))
                    await expect(page.locator('#dock-submitting progress')).to_be_visible()
                    await page.set_viewport_size(dict(width=1440, height=1000))
                    await expect(page.locator('#dock-submitting')).to_be_hidden()
                finally:
                    release.set()
                await until(lambda: len(stub.submissions) == (1 if phase == 'first' else 2) and list(service.jobs.values())[-1]['status'] == 'queued')
                await expect(page.locator('#generation-panel')).to_have_attribute('data-status','queued')
                await expect(page.locator('#job-title')).to_have_text('In the queue')
                await page.unroute('**/api/generate', hold)
                await until(lambda: not service.refresh_task or service.refresh_task.done())
                job = list(service.jobs.values())[-1]
                await expect(page.locator('#job-title')).to_be_hidden()
                await expect(page.locator('#cancel')).to_be_visible()
                assert before == await page.locator('#desktop-result-preview').bounding_box(), (phase, before, await page.locator('#desktop-result-preview').bounding_box(), await page.locator('#job-output').evaluate('el => ({height:el.getBoundingClientRect().height, flex:getComputedStyle(el).flex})'))
                stub.running, stub.pending = stub.pending, []
                await service.refresh()
                await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
                await stub.emit('executing', dict(prompt_id=job['prompt_id'], node='text'))
                await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
                await expect(page.locator('#job-title')).to_be_hidden()
                assert before == await page.locator('#desktop-result-preview').bounding_box(), (phase, before, await page.locator('#desktop-result-preview').bounding_box(), await page.locator('#job-output').evaluate('el => ({height:el.getBoundingClientRect().height, flex:getComputedStyle(el).flex})'))
                await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=1, max=2))
                await expect(page.locator('#stat-steps')).to_have_text('1 / 2')
                assert before == await page.locator('#desktop-result-preview').bounding_box(), (phase, before, await page.locator('#desktop-result-preview').bounding_box(), await page.locator('#job-output').evaluate('el => ({height:el.getBoundingClientRect().height, flex:getComputedStyle(el).flex})'))
                await stub.emit('executing', dict(prompt_id=job['prompt_id'], node='save'))
                await expect(page.locator('#job-title')).to_have_text('Processing workflow…')
                await expect(page.locator('#job-title')).to_be_hidden()
                assert before == await page.locator('#desktop-result-preview').bounding_box(), (phase, before, await page.locator('#desktop-result-preview').bounding_box(), await page.locator('#job-output').evaluate('el => ({height:el.getBoundingClientRect().height, flex:getComputedStyle(el).flex})'))
                if phase == 'completed':
                    await expect(page.locator('#desktop-result-preview img')).to_be_visible()
                # Phone continues displaying the shared generation status.
                await page.set_viewport_size(dict(width=390,height=844))
                await expect(page.locator('#job-title')).to_be_visible()
                await page.set_viewport_size(dict(width=1440,height=1000))
                await expect(page.locator('#job-title')).to_be_hidden()
                await page.screenshot(path=str(output / f'{phase}-processing.png'))
                stub.history[job['prompt_id']] = dict(prompt=stub.running[-1], status=dict(status_str='success'),
                    outputs={'save': {'images': [dict(filename='result.png', subfolder='', type='output')]}})
                stub.pending = stub.running = []
                await service.refresh()
                await expect(page.locator('#job-title')).to_have_text('Your image is ready')
                await expect(page.locator('#desktop-result-preview img')).to_be_visible()
                await expect(page.locator('#generate')).to_be_enabled()
            job.update(status='failed', error='Fixture generation error')
            service.broadcast()
            await expect(page.locator('#job-title')).to_be_visible()
            await expect(page.locator('#job-detail')).to_have_text('Fixture generation error')
            await expect(page.locator('#job-detail')).to_be_visible()
            assert len(stub.submissions) == 2
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: first/repeated submissions keep preview geometry and last image stable; no Desktop native progress; Phone submission dock retained')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
