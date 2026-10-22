"""Responsive layout checks in real browser engines with a ComfyUI protocol fixture.

No physical iPad/iPhone, VPN, GPU inference, or real model loading is exercised.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import tempfile
from dataclasses import replace

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QColor, QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until


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
    external = deepcopy(graph)
    external['text']['inputs']['text'] = 'Prompt saved directly by ComfyUI'
    external['sampler']['inputs']['seed'] = 18446744073709551600
    image = QImage(1024, 1536, QImage.Format.Format_RGB32)
    image.fill(QColor('#456b89'))
    image.setText('prompt', json.dumps(external))
    assert image.save(str(output / 'desktop.png'))
    original_png = (output / 'desktop.png').read_bytes()
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
            await expect(page.locator('#desktop-result-preview')).to_be_visible()
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
            # Fixed-seed editing must allow clearing/replacing the text without
            # JavaScript rounding the 64-bit value or submitting a generation.
            await page.locator('#settings-card').evaluate('el => el.open=true')
            await expect(page.locator('[data-role="seed"]')).to_be_disabled()
            await page.locator('#random-seed').uncheck()
            seed = page.locator('[data-role="seed"]')
            await expect(seed).to_be_enabled()
            await seed.fill('')
            await expect(seed).to_have_value('')
            await seed.fill('18446744073709551600')
            await page.reload()
            await expect(seed).to_have_value('18446744073709551600')
            await expect(page.locator('#random-seed')).not_to_be_checked()
            await seed.fill('42')
            await page.locator('#random-seed').check()
            await page.locator('#settings-card').evaluate('el => el.open=false')
            # Keyboard activation opens a normal control without submitting.
            await page.locator('#prompt-history').focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#prompt-history-dialog')).to_be_visible()
            await page.locator('#close-prompt-history').click()
            assert not stub.submissions
            await page.locator('#generate').click()
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            await expect(page.locator('#header-generation #progress')).to_be_visible()
            assert await page.locator('#progress').count() == 1
            assert len(stub.submissions) == 1
            await until(lambda:not service.refresh_task or service.refresh_task.done())
            stub.running, stub.pending = stub.pending, []
            job = list(service.jobs.values())[-1]
            await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
            await stub.emit('executing', dict(prompt_id=job['prompt_id'], node='model'))
            await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=4, max=20))
            service.update_hardware(dict(utilization=73, vram_used=6 * 2**30))
            await expect(page.locator('#stat-gpu')).to_have_text('73%')
            await expect(page.locator('#stat-vram')).to_have_text('6.0 GiB')
            for ws in stub.sockets:
                await ws.send_bytes(struct.pack('>II', 1, 2) + (output / 'image00.png').read_bytes())
            # Desktop reserves an empty result until completion; Phone retains live previews.
            await expect(page.locator('#preview')).to_have_js_property('hidden', False)
            await expect(page.locator('#preview')).to_be_hidden()
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(page.locator('#preview')).to_be_visible()
            await page.set_viewport_size(dict(width=1440, height=900))
            await page.locator('#advanced').evaluate('el => el.open=true')
            await page.locator('#mapping').evaluate('el => el.open=true')

            async def reachable(identifiers=('generate', 'progress', 'cancel')):
                for identifier in identifiers:
                    # Desktop's requested full-height panel scrolls with the form.
                    await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                    if await page.evaluate('wideLayout.matches'):
                        await page.locator('#' + identifier).evaluate('el => el.scrollIntoView({block: "center"})')
                    bounds = await page.locator('#' + identifier).bounding_box()
                    assert bounds and bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= page.viewport_size['height'] + 1, (identifier, bounds)
                    assert await page.evaluate('({x,y,id}) => !!document.elementFromPoint(x,y)?.closest("#"+id)',
                        dict(id=identifier, x=bounds['x'] + bounds['width']/2, y=bounds['y'] + bounds['height']/2)), (identifier, bounds)

            for width, height in [(1024, 1366), (1366, 1024), (1440, 900), (1000, 600), (390, 844)]:
                await page.set_viewport_size(dict(width=width, height=height))
                at_top = width >= 1000 and height >= 600
                parent = '#header-generation' if at_top else '#job-card'
                await expect(page.locator(parent + ' #progress')).to_be_visible()
                await expect(page.locator(parent + ' #generation-stats')).to_be_visible()
                for scroll in (0, 800, 100000):
                    await page.evaluate('(y) => window.scrollTo(0,y)', scroll)
                    await page.wait_for_timeout(60)
                    await reachable()
                    await reachable(('stat-iteration', 'stat-vram', 'stat-gpu'))
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
            await expect(page.locator('#gallery-grid button')).to_have_count(17)
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
            # A sign-in screen must not retain job information in the header
            # outside the now-hidden workspace. Reload restores the same job.
            await page.evaluate('showLogin()')
            await expect(page.locator('#header-generation')).to_be_hidden()
            await page.reload()
            await expect(page.locator('#header-generation #progress')).to_be_visible()
            assert len(stub.submissions) == 1
            await context.set_offline(True)
            stub.history[job['prompt_id']] = dict(prompt=stub.running[0], status=dict(status_str='success'),
                outputs=dict(save=dict(images=[dict(filename='image00.png', subfolder='', type='output')])))
            stub.running = []
            await stub.emit('execution_success', dict(prompt_id=job['prompt_id']))
            await asyncio.sleep(.2)
            await context.set_offline(False)
            await expect(page.locator('#desktop-result-preview #job-images img')).to_be_visible()
            await expect(page.locator('#job-title')).to_have_text('Your image is ready')
            await expect(page.locator('#job-title')).to_be_hidden()
            await expect(page.locator('#header-generation')).to_be_hidden()
            assert await page.locator('#job-card #job-metrics').count() == 1
            await page.reload()
            await expect(page.locator('#job-images img')).to_be_visible()
            await expect(prompt).to_have_value('An unsent draft survives resizing')
            await reachable(('generate', 'same-seed', 'variation'))
            assert len(stub.submissions) == 1
            await page.screenshot(path=str(root / 'result-laptop.png'))
            # Both gallery reuse actions must work with a generation saved by
            # this laptop browser, without submitting another job on selection.
            for action, randomize in [('reuse-image', False), ('vary-image', True)]:
                await page.locator('#gallery-tab').click()
                if await page.locator('#select-compare').get_attribute('aria-pressed') == 'true':
                    await page.locator('#select-compare').click()
                await page.get_by_role('button', name='View image00.png', exact=True).click()
                await expect(page.locator('#reuse-image')).to_be_enabled()
                await expect(page.locator('#vary-image')).to_be_enabled()
                await page.locator('#' + action).click()
                await expect(page.locator('#image-dialog')).to_be_hidden()
                await expect(prompt).to_have_value('An unsent draft survives resizing')
                await page.locator('#settings-card').evaluate('el => el.open=true')
                if randomize:
                    await expect(page.locator('#random-seed')).to_be_checked()
                else:
                    await expect(page.locator('#random-seed')).not_to_be_checked()
                assert len(stub.submissions) == 1
            # Direct ComfyUI output has no mobile job. Recover its exact mapped
            # values from PNG metadata, retaining the user's custom mappings.
            for action, randomize in [('reuse-image', False), ('vary-image', True)]:
                await page.locator('#gallery-tab').click()
                tile = page.get_by_role('button', name='View desktop.png', exact=True)
                await tile.scroll_into_view_if_needed()
                await expect(tile.locator('img')).to_have_js_property('complete', True)
                assert 'size=768' in await tile.locator('img').evaluate('el => el.currentSrc')
                assert await tile.locator('img').evaluate('el => el.naturalWidth') == 512
                await tile.click()
                await expect(page.locator('#reuse-image')).to_be_enabled()
                await page.locator('#' + action).click()
                await expect(page.locator('#image-dialog')).to_be_hidden()
                await expect(prompt).to_have_value(external['text']['inputs']['text'])
                await page.locator('#settings-card').evaluate('el => el.open=true')
                await expect(page.locator('[data-role="seed"]')).to_have_value(str(external['sampler']['inputs']['seed']))
                assert await page.locator('#random-seed').is_checked() == randomize
                assert len(stub.submissions) == 1 and len(service.presets.list()) == 1
            await page.locator('#gallery-tab').click()
            await page.get_by_role('button', name='View image01.png', exact=True).click()
            await page.locator('#reuse-image').click()
            await expect(page.locator('#image-reuse-status')).to_contain_text('no usable ComfyUI API workflow')
            await expect(page.locator('#image-dialog')).to_be_visible()
            await page.locator('#close-image').click()
            assert (output / 'desktop.png').read_bytes() == original_png
            # A separate touch-capable tablet client starts clean and rotates
            # between wide and Split View layouts without losing its own draft.
            tablet = await browser.new_context(viewport=dict(width=1024, height=1366), device_scale_factor=2, is_mobile=True, has_touch=True, service_workers='block')
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
            await touch.set_viewport_size(dict(width=1366, height=1024))
            await touch.locator('#gallery-tab').tap()
            high_dpi = touch.get_by_role('button', name='View desktop.png', exact=True)
            await high_dpi.scroll_into_view_if_needed()
            await expect(high_dpi.locator('img')).to_have_js_property('complete', True)
            assert 'size=1280' in await high_dpi.locator('img').evaluate('el => el.currentSrc')
            await touch.get_by_role('button', name='View image00.png', exact=True).tap()
            await expect(touch.locator('#reuse-image')).to_be_disabled()
            await expect(touch.locator('#image-reuse-status')).to_contain_text('another browser session')
            # The optional desktop setting shares image settings with a second
            # browser, while its job history and live controls remain isolated.
            service.settings = replace(service.settings, share_image_settings=True)
            await touch.evaluate('loadGallery(true)')
            await expect(touch.locator('#reuse-image')).to_be_enabled()
            await touch.locator('#close-image').tap()
            await touch.set_viewport_size(dict(width=390, height=844))
            saved_seed = job['values'][next(field['key'] for field in job['controls'] if field['role'] == 'seed')]
            for action, randomize in [('reuse-image', False), ('vary-image', True)]:
                await touch.locator('#gallery-tab').tap()
                await touch.get_by_role('button', name='View image00.png', exact=True).tap()
                await expect(touch.locator('#reuse-image')).to_be_enabled()
                await touch.locator('#' + action).tap()
                await expect(touch.locator('#image-dialog')).to_be_hidden()
                await expect(touch.locator('[data-role="positive"]')).to_have_value('An unsent draft survives resizing')
                await touch.locator('#settings-card').evaluate('el => el.open=true')
                await expect(touch.locator('[data-role="seed"]')).to_have_value(str(saved_seed))
                assert await touch.locator('#random-seed').is_checked() == randomize
                assert await touch.evaluate('fetch("/api/state").then(r=>r.json()).then(s=>s.jobs.length)') == 0
                assert await touch.evaluate('fetch("/api/prompts").then(r=>r.json()).then(p=>p.length)') == 0
                assert len(stub.submissions) == 1
            await touch.locator('#gallery-tab').tap()
            await touch.get_by_role('button', name='View image00.png', exact=True).tap()
            service.settings = replace(service.settings, share_image_settings=False)
            await touch.evaluate('loadGallery(true)')
            await expect(touch.locator('#reuse-image')).to_be_disabled()
            await tablet.close()
            assert not errors, errors
            print(json.dumps(dict(browser=browser_name, responsive_layout='phone, tablet portrait/landscape, Split View, laptop, short window',
                generation='fixture: model loading, progress/preview, sticky controls, offline completion and reload',
                reuse='mobile jobs and desktop PNG: exact seed, variation, no auto-submit, missing metadata, unchanged files',
                previews='768px at 1x, 1280px at 2x; private sessions remain isolated',
                cross_device='opt-in laptop to phone reuse/variation; independent history/jobs; disabling sharing restores image restrictions',
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
