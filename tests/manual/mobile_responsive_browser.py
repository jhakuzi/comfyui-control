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
            await expect(page.locator('#generation-empty')).to_be_visible()
            await page.locator('#preset').select_option(preset['id'])
            prompt = page.locator('[data-role="positive"]')
            await expect(prompt).to_be_visible()
            await prompt.fill('An unsent draft survives resizing')

            # Check rendered legibility and keyboard focus, not only token values.
            await page.emulate_media(reduced_motion='reduce')
            contrast = await page.evaluate('''() => {
                const luminance = color => {
                    const rgb = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => {
                        v /= 255;
                        return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
                    });
                    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
                };
                const ratio = (a, b) => {
                    const x = luminance(a), y = luminance(b);
                    return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
                };
                const button = getComputedStyle(document.querySelector('#generate'));
                const prompt = getComputedStyle(document.querySelector('[data-role="positive"]'));
                const hint = getComputedStyle(document.querySelector('#create-page .hint'));
                const card = getComputedStyle(document.querySelector('#generate-form > .card'));
                return {
                    button: ratio(button.color, button.backgroundColor),
                    prompt: ratio(prompt.color, prompt.backgroundColor),
                    hint: ratio(hint.color, card.backgroundColor),
                    transition: button.transitionDuration,
                };
            }''')
            assert all(contrast[name] >= 4.5 for name in ('button', 'prompt', 'hint')), contrast
            assert all(float(duration.strip().removesuffix('s')) == 0 for duration in contrast['transition'].split(','))
            await page.keyboard.press('Tab')
            await page.locator('#prompt-history').focus()
            focus = await page.locator('#prompt-history').evaluate('''el => {
                const css = getComputedStyle(el);
                return { visible: el.matches(':focus-visible'), style: css.outlineStyle, width: parseFloat(css.outlineWidth) };
            }''')
            assert focus['visible'] and focus['style'] != 'none' and focus['width'] >= 2, focus
            await page.emulate_media(reduced_motion='no-preference')

            async def select_page(tab, name):
                # Large layouts show both workspace areas; only compact layouts
                # have navigation tabs. Scrolling a visible column is sufficient.
                button = tab.locator('#' + name + '-tab')
                viewport = tab.viewport_size
                width, height = viewport['width'], viewport['height']
                studio = height >= 600 and (width >= 1440 or width >= 1024 and width / height >= 4/3)
                await expect(tab.locator('#workspace')).to_have_attribute('data-layout', 'studio' if studio else 'compact')
                if studio:
                    await expect(button).to_be_hidden()
                    await tab.locator('#' + name + '-page').evaluate('el => el.scrollIntoView({block: "nearest"})')
                else:
                    await expect(button).to_be_visible()
                    await button.click()

            async def show_details(tab, opened=True):
                if await tab.evaluate('ComfyPresentation.desktop.matches'):
                    if opened:
                        if not await tab.locator('#desktop-image-details').is_visible():
                            await tab.locator('#desktop-show-details').click()
                        await expect(tab.locator('#desktop-image-details')).to_be_visible()
                    elif await tab.locator('#desktop-image-details').is_visible():
                        await tab.locator('#desktop-close-details').click()
                        await expect(tab.locator('#desktop-image-details')).not_to_be_visible()
                else:
                    await tab.locator('#image-details').evaluate('(el, value) => el.open=value', opened)

            async def layout(width, height, wide):
                await page.set_viewport_size(dict(width=width, height=height))
                await expect(page.locator('#workspace')).to_have_attribute('data-layout', 'studio' if height >= 600 and (width >= 1440 or width >= 1024 and width / height >= 4/3) else 'compact')
                await page.evaluate('window.scrollTo(0,0)')
                await expect(page.locator('#generate')).to_be_visible()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                panel = await page.locator('#generation-panel').bounding_box()
                if await page.evaluate('studioLayout.matches'):
                    card = await page.locator('#workflow-card').bounding_box()
                    settings = await page.locator('#settings-card').bounding_box()
                    library = await page.locator('#gallery-page').bounding_box()
                    assert panel['x'] >= settings['x'] + settings['width'] + 12
                    assert abs(panel['y'] - settings['y']) < 1
                    # The redesigned desktop bounds settings and gives images
                    # the remaining width; the toolbar spans both columns.
                    assert abs(card['x'] - settings['x']) < 1
                    assert abs(card['x'] + card['width'] - panel['x'] - panel['width']) < 1
                    assert abs(library['x'] - card['x']) < 1 and abs(library['width'] - card['width']) < 1
                    assert library['y'] >= panel['y'] + panel['height']
                    for section in ('settings-card', 'resolution-card', 'lora-card'):
                        await expect(page.locator('#' + section)).to_have_js_property('open', True)
                    assert await page.locator('#desktop-generate-slot #generate').count() == 1
                    await expect(page.locator('.tabs')).to_be_hidden()
                elif wide:
                    form = await page.locator('#generate-form').bounding_box()
                    assert panel['x'] >= form['x'] + form['width'] + 12, (form, panel)
                    assert panel['width'] >= 350
                    card = await page.locator('#generate-form > .card').first.bounding_box()
                    assert abs(card['y'] - panel['y']) < 1, (card, panel)
                else:
                    assert await page.locator('#generation-dock').evaluate('el => getComputedStyle(el).position') == 'fixed'
                    assert await page.locator('#generation-dock #generate').count() == 1
                await expect(prompt).to_have_value('An unsent draft survives resizing')

            for width, height, wide in [(320, 568, False), (390, 844, False), (844, 390, False), (834, 1194, False),
                                         (1024, 1366, True), (1024, 768, True), (1133, 744, True), (1194, 834, True),
                                         (1280, 1920, True), (1366, 768, True), (1366, 1024, True), (1440, 900, True),
                                         (1920, 1080, True), (2560, 1440, True), (3440, 1440, True),
                                         (1000, 600, True), (1440, 500, False)]:
                await layout(width, height, wide)
            await layout(390, 844, False)
            await page.screenshot(path=str(root / 'create-phone.png'))
            await layout(1194, 834, True)
            await page.screenshot(path=str(root / 'create-tablet-landscape.png'))
            await layout(1440, 900, True)
            await page.screenshot(path=str(root / 'create-desktop.png'))
            await layout(390, 844, False)
            # Fixed-seed editing must allow clearing/replacing the text without
            # JavaScript rounding the 64-bit value or submitting a generation.
            # Restyled disclosure markers retain native keyboard activation.
            await page.locator('#settings-card > summary').focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            await page.wait_for_function('() => !disclosureAnimations.size')
            # Closing fades while native content is retained; rapid reversal
            # must leave it open and usable, with no stale animation styles.
            await page.locator('#settings-card > summary').evaluate('el => el.click()')
            assert await page.evaluate('disclosureAnimations.get(document.querySelector("#settings-card"))?.opening === false')
            await page.locator('#settings-card > summary').evaluate('el => el.click()')
            await page.wait_for_function('() => !disclosureAnimations.size')
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            await page.locator('#settings-card > summary').click()
            await expect(page.locator('#settings-card')).to_have_js_property('open', False)
            await page.emulate_media(reduced_motion='reduce')
            await page.locator('#settings-card > summary').click()
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            assert await page.evaluate('disclosureAnimations.size') == 0
            await page.emulate_media(reduced_motion='no-preference')
            settings_box = await page.locator('#settings-card').bounding_box()
            lora_box = await page.locator('#lora-card').bounding_box()
            assert settings_box['y'] < lora_box['y']
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
            await page.locator('#settings-card > summary').focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#settings-card')).to_have_js_property('open', False)
            await layout(1440, 900, True)
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            # Keyboard activation opens a normal control without submitting.
            await page.locator('#prompt-history').focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#prompt-history-dialog')).to_be_visible()
            await page.locator('#close-prompt-history').click()
            assert not stub.submissions
            submission_gate = asyncio.Event()
            async def hold_submission(route):
                await submission_gate.wait()
                await route.continue_()
            await page.route('**/api/generate', hold_submission)
            await page.locator('#generate').click()
            await expect(page.locator('#preview-loading')).to_be_visible()
            await expect(page.locator('#preview-loading-phase')).to_have_text('Submitting workflow…')
            await expect(page.locator('#generate')).to_have_attribute('data-progress', 'indeterminate')
            await expect(page.locator('#generate-label')).to_have_text('Submitting')
            await page.screenshot(path=str(root / 'submitting-placeholder.png'))
            submission_gate.set()
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            await expect(page.locator('#generate-label')).to_have_text('Queued')
            await expect(page.locator('#generate')).to_be_disabled()
            await expect(page.locator('#generation-panel #progress')).to_be_visible()
            await expect(page.locator('#preview-loading')).to_be_visible()
            await expect(page.locator('#preview-stage')).to_have_attribute('data-preview', 'false')
            await page.emulate_media(reduced_motion='reduce')
            assert await page.locator('#preview-loading .loading-spinner').evaluate('el => getComputedStyle(el).animationName') == 'none'
            assert await page.locator('#generate').evaluate('el => getComputedStyle(el, "::before").animationName') == 'none'
            await page.emulate_media(reduced_motion='no-preference')
            assert await page.locator('#preview-loading .loading-spinner').evaluate('el => getComputedStyle(el).animationName') == 'loading-spin'
            assert await page.locator('#progress').count() == 1
            assert len(stub.submissions) == 1
            stub.running, stub.pending = stub.pending, []
            job = list(service.jobs.values())[-1]
            # Drain an in-flight queued snapshot before emitting the fixture's
            # execution events, as a real queue transition would do.
            await service.refresh()
            await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
            await stub.emit('executing', dict(prompt_id=job['prompt_id'], node='model'))
            await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
            await expect(page.locator('#generate-label')).to_have_text('Loading models')
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=4, max=20))
            await expect(page.locator('#generate-label')).to_have_text('Sampling · 20%')
            await expect(page.locator('#generate')).to_have_attribute('data-progress', 'determinate')
            assert await page.locator('#generate').evaluate('el => el.style.getPropertyValue("--generation-progress")') == '0.2'
            # A new sampling stage can restart its progress. It must not retain
            # the old stage's fraction or submit any additional generation.
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=1, max=10))
            await expect(page.locator('#generate-label')).to_have_text('Sampling · 10%')
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=4, max=20))
            await expect(page.locator('#generate-label')).to_have_text('Sampling · 20%')
            service.update_hardware(dict(utilization=73, vram_used=6 * 2**30))
            await expect(page.locator('#stat-gpu')).to_have_text('73%')
            await expect(page.locator('#stat-vram')).to_have_text('6.0 GiB')
            await expect(page.locator('#preview-stat-gpu')).to_have_text('73%')
            await expect(page.locator('#preview-stat-vram')).to_have_text('6.0 GiB')
            await page.screenshot(path=str(root / 'sampling-placeholder.png'))
            for ws in stub.sockets:
                await ws.send_bytes(struct.pack('>II', 1, 2) + (output / 'image00.png').read_bytes())
            await expect(page.locator('#preview')).to_be_visible()
            await expect(page.locator('#preview-stage')).to_have_attribute('data-preview', 'true')
            await page.locator('#advanced').evaluate('el => el.open=true')
            await page.locator('#mapping').evaluate('el => el.open=true')

            async def reachable(identifiers=None):
                studio = await page.evaluate('studioLayout.matches')
                identifiers = identifiers or (('progress', 'cancel') if studio else ('generate', 'progress', 'cancel'))
                for identifier in identifiers:
                    if studio:
                        await page.locator('#' + identifier).evaluate('el => el.scrollIntoView({block: "center"})')
                    bounds = await page.locator('#' + identifier).bounding_box()
                    assert bounds and bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= page.viewport_size['height'] + 1, (identifier, bounds)
                    assert await page.evaluate('({x,y,id}) => !!document.elementFromPoint(x,y)?.closest("#"+id)',
                        dict(id=identifier, x=bounds['x'] + bounds['width']/2, y=bounds['y'] + bounds['height']/2))

            for width, height in [(1024, 1366), (1024, 768), (1194, 834), (1366, 768), (1366, 1024), (1440, 900), (2560, 1440), (1000, 600), (390, 844)]:
                await page.set_viewport_size(dict(width=width, height=height))
                at_top = width >= 1000 and height >= 600 and not await page.evaluate("studioLayout.matches")
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
            await select_page(page, 'gallery')
            await expect(page.locator('#gallery-grid button')).to_have_count(17)
            assert await page.locator('#gallery-grid').evaluate('el => getComputedStyle(el).gridTemplateColumns.split(" ").length') >= 4
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
            await select_page(page, 'create')
            await page.evaluate('window.scrollTo(0,0)')
            # A sign-in screen must not retain job information in the header
            # outside the now-hidden workspace. Reload restores the same job.
            await page.evaluate('showLogin()')
            await expect(page.locator('#header-generation')).to_be_hidden()
            await page.reload()
            await expect(page.locator('#generation-panel #progress')).to_be_visible()
            assert len(stub.submissions) == 1
            await context.set_offline(True)
            await expect(page.locator('#generate')).to_have_attribute('data-progress', 'paused')
            await expect(page.locator('#generate-label')).to_have_text('Reconnecting')
            stub.history[job['prompt_id']] = dict(prompt=stub.running[0], status=dict(status_str='success'),
                outputs=dict(save=dict(images=[dict(filename='image00.png', subfolder='', type='output')])))
            stub.running = []
            await stub.emit('execution_success', dict(prompt_id=job['prompt_id']))
            await asyncio.sleep(.2)
            await context.set_offline(False)
            await expect(page.locator('#selected-image-preview')).to_be_visible()
            await expect(page.locator('#job-title')).to_have_text('Your image is ready')
            await expect(page.locator('#generate')).to_have_attribute('data-progress', 'idle')
            await expect(page.locator('#generate-label')).to_have_text('✦ Generate')
            await expect(page.locator('#header-generation')).to_be_hidden()
            assert await page.locator('#job-card #job-metrics').count() == 1
            await page.reload()
            await expect(page.locator('#selected-image-preview')).to_be_visible()
            await expect(prompt).to_have_value('An unsent draft survives resizing')
            await reachable(('generate', 'reuse-selected-image', 'vary-selected-image'))
            # The full-size result and its actions fit typical laptop/iPad
            # landscape sizes and scale up without stretching side controls.
            for width, height in [(1024, 768), (1194, 834), (1366, 768), (1920, 1080), (3440, 1440)]:
                await page.set_viewport_size(dict(width=width, height=height))
                await expect(page.locator('#workspace')).to_have_attribute('data-layout', 'studio')
                await page.evaluate('window.scrollTo(0,0)')
                await reachable(('generate', 'download-image', 'reuse-selected-image'))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                image_box = await page.locator('#selected-image-preview').bounding_box()
                assert image_box['height'] >= 200, image_box
                await page.screenshot(path=str(root / f'large-result-{width}.png'))
            await page.set_viewport_size(dict(width=1440, height=900))
            assert len(stub.submissions) == 1
            await expect(page.locator('#open-selected-image')).to_be_hidden()
            await expect(page.locator('#desktop-show-details')).to_be_visible()
            await expect(page.locator('#image-dialog')).to_be_hidden()
            selected_id = await page.evaluate('selectedImage.id')
            await page.locator('#next-image').click()
            assert await page.evaluate('selectedImage.id') != selected_id
            assert await page.locator('#download-image').get_attribute('href') == await page.evaluate('selectedImage.download')
            await page.locator('#previous-image').click()
            assert await page.evaluate('selectedImage.id') == selected_id
            await page.screenshot(path=str(root / 'result-laptop.png'))
            async def view_image(tab, filename):
                await tab.get_by_role('button', name='View ' + filename, exact=True).click()
                if await tab.evaluate('studioLayout.matches'):
                    await expect(tab.locator('#selected-image-name')).to_have_text(filename)
                    await expect(tab.locator('#image-dialog')).to_be_hidden()
            # Center-panel reuse also targets an explicit saved image and only
            # prepares the existing form; it must not queue another job.
            await page.locator('#reuse-selected-image').click()
            await expect(page.locator('#random-seed')).not_to_be_checked()
            assert len(stub.submissions) == 1
            await page.locator('#vary-selected-image').click()
            await expect(page.locator('#random-seed')).to_be_checked()
            assert len(stub.submissions) == 1
            # Both gallery reuse actions must work with a generation saved by
            # this laptop browser, without submitting another job on selection.
            for action, randomize in [('reuse-selected-image', False), ('vary-selected-image', True)]:
                await select_page(page, 'gallery')
                if await page.locator('#select-compare').get_attribute('aria-pressed') == 'true':
                    await page.locator('#select-compare').click()
                await view_image(page, 'image00.png')
                await expect(page.locator('#reuse-selected-image')).to_be_enabled()
                await expect(page.locator('#vary-selected-image')).to_be_enabled()
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
            for action, randomize in [('reuse-selected-image', False), ('vary-selected-image', True)]:
                await select_page(page, 'gallery')
                tile = page.get_by_role('button', name='View desktop.png', exact=True)
                await tile.scroll_into_view_if_needed()
                await expect(tile.locator('img')).to_have_js_property('complete', True)
                assert 'size=768' in await tile.locator('img').evaluate('el => el.currentSrc')
                assert await tile.locator('img').evaluate('el => el.naturalWidth') == 512
                await tile.click()
                await expect(page.locator('#reuse-selected-image')).to_be_enabled()
                await show_details(page, True)
                await expect(page.locator('#image-metadata')).to_contain_text('Prompt saved directly by ComfyUI')
                if not randomize:
                    # LAN HTTP needs selection-copy fallback outside a dialog too.
                    await page.evaluate('Object.defineProperty(navigator, "clipboard", {configurable: true, value: undefined})')
                    await page.locator('#copy-image-prompt').click()
                    await expect(page.locator('#copy-prompt-status')).to_have_text('Prompt copied.')
                    await show_details(page, False)
                    async with page.expect_download() as download_info:
                        await page.locator('#download-image').click()
                    download = await download_info.value
                    await download.save_as(root / 'download-desktop.png')
                    assert (root / 'download-desktop.png').read_bytes() == original_png
                await show_details(page, False)
                await page.locator('#' + action).click()
                await expect(page.locator('#image-dialog')).to_be_hidden()
                await expect(prompt).to_have_value(external['text']['inputs']['text'])
                await page.locator('#settings-card').evaluate('el => el.open=true')
                await expect(page.locator('[data-role="seed"]')).to_have_value(str(external['sampler']['inputs']['seed']))
                if randomize:
                    await expect(page.locator('#random-seed')).to_be_checked()
                else:
                    await expect(page.locator('#random-seed')).not_to_be_checked()
                assert len(stub.submissions) == 1 and len(service.presets.list()) == 1
            await select_page(page, 'gallery')
            await view_image(page, 'image01.png')
            await page.locator('#reuse-selected-image').click()
            await expect(page.locator('#selected-reuse-status')).to_contain_text('no usable ComfyUI API workflow')
            await expect(page.locator('#image-dialog')).to_be_hidden()
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
            await touch.locator('#lora-card > summary').tap()
            await expect(touch.locator('#lora-card')).to_have_js_property('open', True)
            await touch.locator('#lora-card > summary').tap()
            await expect(touch.locator('#lora-card')).to_have_js_property('open', False)
            await touch.set_viewport_size(dict(width=1366, height=1024))
            await select_page(touch, 'gallery')
            high_dpi = touch.get_by_role('button', name='View desktop.png', exact=True)
            await high_dpi.scroll_into_view_if_needed()
            await expect(high_dpi.locator('img')).to_have_js_property('complete', True)
            assert 'size=1280' in await high_dpi.locator('img').evaluate('el => el.currentSrc')
            await view_image(touch, 'image00.png')
            await expect(touch.locator('#reuse-selected-image')).to_be_disabled()
            await expect(touch.locator('#selected-reuse-status')).to_contain_text('another browser session')
            await show_details(touch, True)
            await expect(touch.locator('#image-metadata')).to_contain_text('unavailable for this browser session')
            # The optional desktop setting shares image settings with a second
            # browser, while its job history and live controls remain isolated.
            service.settings = replace(service.settings, share_image_settings=True)
            await touch.evaluate('loadGallery(true)')
            await expect(touch.locator('#reuse-selected-image')).to_be_enabled()
            await expect(touch.locator('#image-metadata')).to_contain_text('An unsent draft survives resizing')
            await show_details(touch, False)
            await touch.set_viewport_size(dict(width=390, height=844))
            saved_seed = job['values'][next(field['key'] for field in job['controls'] if field['role'] == 'seed')]
            for action, randomize in [('reuse-image', False), ('vary-image', True)]:
                await select_page(touch, 'gallery')
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
            await select_page(touch, 'gallery')
            await touch.get_by_role('button', name='View image00.png', exact=True).tap()
            service.settings = replace(service.settings, share_image_settings=False)
            await touch.evaluate('loadGallery(true)')
            await expect(touch.locator('#reuse-image')).to_be_disabled()
            await tablet.close()
            # Saved-image actions always target the chosen older file, not the
            # latest job. Keep and selection survive reload; Trash is reversible.
            await page.set_viewport_size(dict(width=1440, height=900))
            await page.locator('#gallery-all').click()
            if await page.locator('#select-compare').get_attribute('aria-pressed') == 'true':
                await page.locator('#select-compare').click()
            await page.get_by_role('button', name='View image02.png', exact=True).click()
            await expect(page.locator('#selected-image-name')).to_have_text('image02.png')
            actions = page.locator('#selected-image-panel')
            await expect(actions.locator('[data-action="keep"]')).to_be_enabled()
            await expect(actions.locator('[data-action="edit"]')).to_be_disabled()
            await expect(actions.locator('[data-action="upscale"]')).to_be_disabled()
            await expect(actions.locator('.image-workflow-status')).to_contain_text('not configured')
            await reachable(('generate', 'download-image'))
            for control in ('keep', 'trash'):
                await actions.locator('[data-action="' + control + '"]').scroll_into_view_if_needed()
                box = await actions.locator('[data-action="' + control + '"]').bounding_box()
                assert box and box['y'] + box['height'] <= page.viewport_size['height'], box
            await actions.locator('[data-action="keep"]').click()
            await expect(actions.locator('[data-action="keep"]')).to_have_attribute('aria-pressed', 'true')
            await expect(actions.locator('[data-action="keep"]')).to_have_text('♥')
            await expect(actions.locator('[data-action="keep"]')).to_have_attribute('aria-label', 'Remove image from Favourites')
            await page.locator('#image-favourites').click()
            await expect(page.locator('#gallery-grid button')).to_have_count(1)
            await expect(page.locator('#gallery-kept')).to_have_text('Favourites')
            await page.reload()
            await expect(page.locator('#selected-image-name')).to_have_text('image02.png')
            await expect(page.locator('#gallery-kept')).to_have_attribute('aria-pressed', 'true')
            await expect(actions.locator('[data-action="keep"]')).to_have_attribute('aria-pressed', 'true')
            await expect(prompt).to_have_value(external['text']['inputs']['text'])
            await page.locator('#gallery-all').click()
            original = (output / 'image02.png').read_bytes()
            page.once('dialog', lambda dialog: dialog.accept())
            await actions.locator('[data-action="trash"]').click()
            await expect(page.get_by_role('button', name='View image02.png', exact=True)).to_have_count(0)
            assert not (output / 'image02.png').exists() and (output / 'image00.png').exists()
            await page.locator('#gallery-trash').click()
            await expect(page.locator('#trash-list .trash-entry')).to_have_count(1)
            await page.locator('#trash-list button').click()
            await expect(page.locator('#trash-status')).to_contain_text('empty')
            assert (output / 'image02.png').read_bytes() == original
            await page.locator('#gallery-all').click()
            await page.get_by_role('button', name='View image02.png', exact=True).click()
            await expect(actions.locator('[data-action="keep"]')).to_be_enabled()
            await actions.locator('[data-action="keep"]').click()
            await expect(actions.locator('[data-action="keep"]')).to_have_text('♡')
            await page.locator('#image-favourites').click()
            await expect(page.locator('#gallery-grid button')).to_have_count(0)
            assert (output / 'image02.png').read_bytes() == original
            assert len(stub.submissions) == 1
            # The redundant job-history shortcut remains a mobile control.
            await page.set_viewport_size(dict(width=390, height=844))
            await select_page(page, 'gallery')
            await page.locator('#gallery-jobs').click()
            await expect(page.locator('#generation-history-list button')).to_have_count(1)
            await page.locator('#generation-history-list button').click()
            await page.set_viewport_size(dict(width=1440, height=900))
            await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop')
            await expect(page.locator('#selected-image-name')).to_have_text('image00.png')
            assert len(stub.submissions) == 1
            await page.locator('#gallery-all').click()
            # A slow action response must not retarget the operation or replace
            # the image the user selected while waiting for it.
            posted, release = asyncio.Event(), asyncio.Event()
            async def delayed_action(route):
                if route.request.method != 'POST':
                    await route.continue_()
                    return
                response = await route.fetch()
                posted.set()
                await release.wait()
                await route.fulfill(response=response)
            await page.route('**/api/images/*/actions', delayed_action)
            await page.get_by_role('button', name='View image01.png', exact=True).click()
            await expect(actions.locator('[data-action="keep"]')).to_be_enabled()
            await actions.locator('[data-action="keep"]').click()
            await asyncio.wait_for(posted.wait(), 5)
            await page.get_by_role('button', name='View image02.png', exact=True).click()
            release.set()
            await expect(page.locator('#selected-image-name')).to_have_text('image02.png')
            await expect(page.get_by_role('button', name='View image01.png', exact=True)).to_have_class('kept-image')
            await page.unroute('**/api/images/*/actions', delayed_action)
            # Returning through sign-in/recovery without a reload restores
            # capability controls for the same selected image.
            await page.evaluate('showLogin(); bootstrap()')
            await expect(page.locator('#workspace')).to_be_visible()
            await expect(actions.locator('[data-action="keep"]')).to_be_enabled()
            await page.locator('#advanced').evaluate('el => el.open=false')
            await page.evaluate('window.scrollTo(0,0)')
            await page.screenshot(path=str(root / 'workspace-desktop.png'), full_page=True)
            # The same buttons remain available through the existing phone
            # viewer, and the same prompt draft survives viewport changes.
            await page.set_viewport_size(dict(width=390, height=844))
            await select_page(page, 'gallery')
            await view_image(page, 'image02.png')
            await expect(page.locator('#viewer-image-actions [data-action="keep"]')).to_have_attribute('aria-pressed', 'false')
            await page.locator('#viewer-image-actions [data-action="keep"]').click()
            await expect(page.locator('#viewer-image-actions [data-action="keep"]')).to_have_attribute('aria-pressed', 'true')
            assert await page.locator('#selected-image-preview').get_attribute('src') is None
            await page.screenshot(path=str(root / 'workspace-phone.png'))
            # One set of tools follows the current photo when moving from the
            # phone dialog into the wide preview and back; close cannot erase it.
            await show_details(page, True)
            await page.set_viewport_size(dict(width=1440, height=900))
            await expect(page.locator('#image-dialog')).to_be_hidden()
            await expect(page.locator('#desktop-show-details')).to_be_visible()
            await expect(page.locator('#selected-image-name')).to_have_text('image02.png')
            await show_details(page)
            await expect(page.locator('#image-metadata')).to_contain_text('Image resolution')
            await page.set_viewport_size(dict(width=390, height=844))
            await view_image(page, 'image02.png')
            await expect(page.locator('#image-dialog')).to_be_visible()
            await expect(page.locator('#viewer-image-tools #image-details')).to_be_visible()
            assert await page.locator('#image-details').count() == 1
            assert await page.locator('#download-image').count() == 1
            await page.set_viewport_size(dict(width=320, height=568))
            assert await page.locator('#image-dialog').evaluate('el => el.scrollWidth <= el.clientWidth')
            await page.locator('#close-image').click()
            await page.locator('#gallery-kept').click()
            await view_image(page, 'image02.png')
            (output / 'image02.png').unlink()
            await page.evaluate('loadGallery(true)')
            await expect(page.locator('#image-dialog')).to_be_hidden()
            await expect(page.get_by_role('button', name='View image02.png', exact=True)).to_have_count(0)
            assert not errors, errors
            print(json.dumps(dict(browser=browser_name, responsive_layout='phone, tablet portrait/landscape, Split View, laptop, short window; desktop prompts above open settings/preview and full-width gallery',
                motion='disclosure open/close, reversal, keyboard and reduced motion',
                button_progress='submission, queue, loading, actual sampling fraction, new stage, reconnect pause and completion reset',
                generation='fixture: model loading, progress/preview, sticky controls, offline completion and reload',
                reuse='mobile jobs and desktop PNG: exact seed, variation, no auto-submit, missing metadata, unchanged files',
                previews='768px at 1x, 1280px at 2x; private sessions remain isolated',
                cross_device='opt-in laptop to phone reuse/variation; independent history/jobs; disabling sharing restores image restrictions',
                image_actions='older-image hearts, Favourites shortcut, unlike, reload, phone/desktop consistency, unavailable workflow actions, Trash/restore and history',
                gallery='full-width below desktop workspace, keyboard comparison, accessible close', tablet='touch expansion, rotation, isolated draft', javascript_errors=errors)))
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
