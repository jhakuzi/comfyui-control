"""Generate fill checks against real WebUI and simulated ComfyUI events (no GPU)."""
import argparse
import asyncio
from pathlib import Path
import sys
import uuid

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until


async def main(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    graph = {'text': {'class_type': 'Prompt', 'inputs': {'text': 'Protocol test'}}}
    stub = ComfyStub(graph)
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root / 'out')
    preset = service.presets.create('Progress fixture', graph)
    service.presets.map(preset['id'], [dict(key='prompt', node='text', input='text', role='positive', label='Prompt')])
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport={'width': 1440, 'height': 900}, service_workers='block')
            page = await context.new_page()
            page.set_default_timeout(8000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
            button, label = page.locator('#generate'), page.locator('#generate-label')
            await expect(button).to_be_enabled()
            idle = await button.bounding_box()
            await expect(button).to_be_visible()
            # WPE's headless compositor can stall Playwright's stability frames.
            # Visibility/enabled/geometry checks still guard this fixture click.
            await button.click(force=engine == 'webkit')
            await expect(label).to_have_text('Queued')
            await expect(button).to_have_attribute('data-progress', 'indeterminate')
            job = list(service.jobs.values())[-1]
            stub.running, stub.pending = stub.pending, []
            await service.refresh()
            await stub.emit('execution_start', {'prompt_id': job['prompt_id']})
            await stub.emit('executing', {'prompt_id': job['prompt_id'], 'node': 'sampler'})
            await stub.emit('progress', {'prompt_id': job['prompt_id'], 'value': 8, 'max': 20})
            await expect(label).to_have_text('Sampling · 40%')
            await expect(button).to_have_attribute('data-progress', 'determinate')
            box = await button.bounding_box()
            assert box["width"] == idle["width"] and box["height"] == idle["height"], (idle, box)
            await page.screenshot(path=str(root / 'sampling.png'))
            await stub.emit('progress_state', {'prompt_id': job['prompt_id'], 'nodes': {
                'sampler': {'state': 'running', 'value': 20, 'max': 20}}})
            await expect(label).to_have_text('Processing')
            await expect(button).to_have_attribute('data-progress', 'indeterminate')
            await stub.emit('executing', {'prompt_id': job['prompt_id'], 'node': 'vae'})
            await expect(label).to_have_text('Processing')
            await page.screenshot(path=str(root / 'processing.png'))
            await context.set_offline(True)
            await expect(button).to_have_attribute('data-progress', 'paused')
            await context.set_offline(False)
            await expect(label).to_have_text('Processing')
            stub.history[job['prompt_id']] = dict(prompt=stub.running[0], status={'status_str': 'success'}, outputs={})
            stub.running = []
            await stub.emit('execution_success', {'prompt_id': job['prompt_id']})
            await expect(button).to_have_attribute('data-progress', 'success')
            assert await button.evaluate('el => el.style.getPropertyValue("--generation-progress")') == '1'
            await page.screenshot(path=str(root / 'success.png'))
            await expect(button).to_have_attribute('data-progress', 'idle')
            await page.reload()
            await expect(button).to_be_enabled()
            await expect(label).to_have_text('✦ Generate')
            page.on('dialog', lambda dialog: dialog.accept())
            # Main X cancels a single run, preserving the remaining batch.
            await page.locator('#batch-count').fill('3')
            await button.click(force=engine == 'webkit')
            await expect(page.locator('#cancel-queue')).to_be_visible()
            await until(lambda: len(stub.pending) == 3)
            await page.locator('#cancel').click(force=engine == 'webkit')
            await until(lambda: len(stub.pending) == 2)
            queue_button = page.locator('#cancel-queue')
            await expect(queue_button).to_have_attribute('aria-expanded', 'false')
            # First activation expands only; Escape reverses it.
            await queue_button.click(force=engine == 'webkit')
            await expect(queue_button).to_have_attribute('aria-expanded', 'true')
            assert len(stub.pending) == 2
            await queue_button.press('Escape')
            await expect(queue_button).to_have_attribute('aria-expanded', 'false')
            await queue_button.click(force=engine == 'webkit')
            await queue_button.click(force=engine == 'webkit')
            await until(lambda: not stub.pending)
            await expect(page.locator('#cancel-controls')).to_be_hidden()
            # Clear a running batch while retaining a different browser's job.
            await button.click(force=engine == 'webkit')
            await until(lambda: len(stub.pending) == 3)
            current = service.presets.get(preset['id'])
            other = await service.submit(dict(request_id=str(uuid.uuid4()), preset=current['id'],
                revision=revision(current), values={}), owner='other-browser')
            stub.running, stub.pending = stub.pending[:1], stub.pending[1:]
            await service.refresh()
            await expect(page.locator('#cancel-queue-count')).to_have_text('2')
            await queue_button.click(force=engine == 'webkit')
            await page.wait_for_function('() => document.getElementById("cancel-controls").getBoundingClientRect().width >= 221')
            await page.screenshot(path=str(root / 'cancel-expanded.png'))
            await page.set_viewport_size({'width': 390, 'height': 844})
            await expect(page.locator('html')).to_have_attribute('data-presentation', 'mobile')
            await expect(queue_button).to_be_visible()
            assert await queue_button.evaluate('el => el.getBoundingClientRect().right <= innerWidth')
            await page.screenshot(path=str(root / 'cancel-phone.png'))
            await page.set_viewport_size({'width': 1440, 'height': 900})
            await queue_button.click(force=engine == 'webkit')
            await until(lambda: len(stub.pending) == 1 and len(stub.interrupts) == 1)
            assert stub.pending[0][1] == other['prompt_id']
            assert stub.interrupts[0] == {'prompt_id': stub.running[0][1]}
            await expect(queue_button).to_be_hidden()
            # Stop live events before deterministic boundary snapshots. These
            # exercise presentation only; no generated requests are replayed.
            await page.evaluate('events?.close()')

            async def snapshot(jobs, online=True):
                await page.evaluate('''({jobs, online}) => {
                    state = {...state, jobs, online}; connected = true; recovering = false;
                    selectedJob = jobs[0]?.id; updateGenerate();
                }''', dict(jobs=jobs, online=online))

            queued = dict(id='queued', status='queued')
            running = dict(id='running', status='running', phase='sampling', progress={'value': 3, 'max': 10})
            await snapshot([queued, running])
            await expect(label).to_have_text('Sampling · 30%')
            await snapshot([queued, dict(running, status='complete')])
            await expect(label).to_have_text('Queued')
            await snapshot([dict(queued, status='cancelled'), dict(running, status='complete')])
            await expect(label).to_have_text('Cancelled')
            await expect(button).to_have_attribute('data-progress', 'idle')
            await snapshot([running])
            await snapshot([dict(running, status='failed')])
            await expect(label).to_have_text('Generation failed')
            # A new request replaces terminal feedback immediately.
            await snapshot([dict(running, status='unknown')])
            await expect(label).to_have_text('Checking submission')
            await page.emulate_media(reduced_motion='reduce')
            assert await button.evaluate('el => getComputedStyle(el, "::before").animationName') == 'none'
            assert await button.evaluate('el => getComputedStyle(el, "::after").transitionDuration') == '0s'
            assert await button.evaluate('el => getComputedStyle(el, "::after").animationName') == 'none'
            await snapshot([dict(running, status='cancelling')])
            await expect(label).to_have_text('Stopping')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await snapshot([running])
            await expect(button).to_be_visible()
            await expect(label).to_have_text('Sampling · 30%')
            await page.screenshot(path=str(root / 'phone.png'))
            await snapshot([dict(running, status='complete', batch_id='batch', batch_notice='Partial batch')])
            await expect(label).to_have_text('Generation failed')
            assert len(stub.submissions) == 8
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: Generate fill, real event flow, completion, recovery, queue/error/cancel, mobile and reduced motion passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'firefox', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
