"""Requested Desktop geometry/state regressions against a local ComfyUI simulator.

No GPU inference or physical Phone behavior is claimed. See main_feature_port_browser.py
for before/after Phone pixel comparisons against an exported baseline.
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QColor, QImage, QPainter, QGuiApplication

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_workflows import ImageWorkflowStub
from test_mobile_integration import until

SIZES = [(1000, 600), (1280, 800), (1440, 900), (1920, 1080), (2560, 1440)]


async def main(engine, root):
    qt = QGuiApplication.instance() or QGuiApplication([])
    root.mkdir(parents=True)
    output = root / 'images'
    output.mkdir()
    for name, width, height, color in [('portrait', 640, 960, '#687966'), ('landscape', 960, 640, '#657b8c')]:
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        painter = QPainter(image)
        painter.setPen(QColor('#f2f2f6'))
        painter.drawText(36, 60, 'Completed image — browser test fixture')
        painter.end()
        assert image.save(str(output / f'{name}.png'))
    graph = {
        'text': dict(class_type='Prompt', inputs={'text': 'A quiet mountain lake in warm evening light.'}),
        'negative': dict(class_type='Prompt', inputs={'text': ''}),
        'diffusion': dict(class_type='DiffusionLoader', inputs={'unet_name': 'diffusion.gguf'}),
        'vae': dict(class_type='VAELoader', inputs={'vae_name': 'vae.safetensors'}),
        'encoder': dict(class_type='CLIPLoader', inputs={'clip_name': 'encoder.safetensors'}),
        'sampler': dict(class_type='Sampler', inputs={'seed': 18446744073709551600, 'steps': 20, 'width': 768, 'height': 1024}),
    }
    stub = ImageWorkflowStub()
    stub.object_info.update({node['class_type']: {'input': {}} for node in graph.values()})
    mappings = [dict(node=node, input=field, role=role, key=role, label=label) for node, field, role, label in [
        ('text', 'text', 'positive', 'Prompt'), ('negative', 'text', 'negative', 'Negative prompt'),
        ('diffusion', 'unet_name', 'diffusion_model', 'Diffusion model'), ('vae', 'vae_name', 'vae', 'VAE'),
        ('encoder', 'clip_name', 'text_encoder', 'Text encoder'), ('sampler', 'seed', 'seed', 'Seed'),
        ('sampler', 'steps', 'steps', 'Steps'), ('sampler', 'width', 'width', 'Width'),
        ('sampler', 'height', 'height', 'Height')]]
    for key, field in [('diffusion', 'unet_name'), ('vae', 'vae_name'), ('encoder', 'clip_name')]:
        stub.object_info[graph[key]['class_type']]['input'] = {'required': {field: [[graph[key]['inputs'][field], 'other.safetensors']]}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    preset = service.presets.create('Desktop layout fixture', graph)
    service.presets.map(preset['id'], mappings)
    mobile = TestServer(MobileHTTP(service).app())
    errors = []
    try:
        await service.start()
        await until(lambda: service.online)
        await mobile.start_server()
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport=dict(width=1440, height=900), service_workers='block', reduced_motion='reduce')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(str(mobile.make_url('/')))
            await expect(page.locator('#generate')).to_be_enabled()
            await expect(page.locator('.desktop-selector-refresh')).to_have_count(4)
            prompt = page.locator('[data-role="positive"]')
            await prompt.fill('An unsent draft survives overlay, refresh and resizing.')
            await page.locator('#settings-card').evaluate('el => el.open = true')
            await page.locator('#random-seed').uncheck()
            seed = page.locator('[data-role="seed"]')
            await expect(seed).to_have_value('18446744073709551600')

            async def geometry():
                await page.evaluate('document.activeElement?.blur(); window.scrollTo(0, 0)')
                await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                return await page.evaluate('''() => {
                  const rect = el => {const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom,r:r.right};};
                  const get = selector => rect(document.querySelector(selector));
                  return {left:get('#generate-form > .card'), right:get('#generation-panel'), tabs:get('.tabs'), createTab:get('#create-tab'), galleryTab:get('#gallery-tab'),
                    frame:get('#desktop-result-preview'), history:get('#prompt-history'), models:get('#model-controls'),
                    overflow:document.documentElement.scrollWidth > innerWidth,
                    selectors:[...document.querySelectorAll('.desktop-selector-tools')].map(row => [...row.children].map(rect))};
                }''')

            async def check_layout(state_name, expected=None):
                report = await geometry()
                assert not report['overflow'], report
                assert abs(report['left']['y'] - report['right']['y']) < 1, report
                assert abs(report['left']['b'] - report['right']['b']) < 1, report
                assert abs(report['right']['w'] - report['left']['w']) <= .02, report
                assert abs((report['left']['r'] + report['right']['x']) / 2 - (report['tabs']['x'] + report['tabs']['r']) / 2) <= .02, report
                assert abs(report['right']['x'] - report['left']['r'] - 28) <= .02, report
                assert abs(report['left']['x'] - report['tabs']['x']) < 1, report
                assert abs(report['right']['r'] - report['tabs']['r']) < 1, report
                if expected:
                    for key in ['left', 'right']:
                        assert report[key]['w'] == expected[key]['w'] and report[key]['h'] == expected[key]['h'], (state_name, expected, report)
                for select, button in report['selectors']:
                    assert 0 < button['x'] - select['r'] < 12 and abs((button['y'] + button['h']/2) - (select['y'] + select['h']/2)) < 1, report
                await expect(page.locator('#desktop-right-column > #resolution-card')).to_have_count(1)
                await expect(page.locator('#desktop-right-column > #advanced')).to_have_count(1)
                if state_name in ['completed', 'landscape']:
                    await expect(page.locator('#job-title')).to_be_hidden()
                    await expect(page.locator('#job-detail')).to_be_hidden()
                    assert report['frame']['h'] > expected['frame']['h'] + 80
                for section in ['resolution-card', 'advanced']:
                    panel = page.locator('#' + section)
                    was_open = await panel.evaluate('el => el.open')
                    await panel.locator(':scope > summary').evaluate('el => el.click()')
                    await expect(panel).to_have_js_property('open', not was_open)
                    await panel.locator(':scope > summary').evaluate('el => el.click()')
                    await expect(panel).to_have_js_property('open', was_open)
                await expect(page.locator('#reuse-last')).to_be_hidden()
                await expect(page.locator('#preview')).to_be_hidden()
                await page.screenshot(path=str(root / f'{state_name}-{page.viewport_size["width"]}.png'), full_page=True)
                return report

            empty = {}
            for width, height in SIZES:
                await page.set_viewport_size(dict(width=width, height=height))
                empty[width] = await check_layout('empty')
                await expect(page.locator('#desktop-result-preview')).to_be_visible()
                await expect(page.locator('#job-images > button')).to_have_count(0)
                before = await geometry()
                await page.locator('.prompt-editor-toggle').click()
                after = await geometry()
                assert before == after, (before, after)
                overlay = await prompt.bounding_box()
                history = after['history']
                assert overlay['y'] + overlay['height'] > history['y'] + history['h']
                assert await prompt.evaluate('el => getComputedStyle(el).boxShadow') != 'none'
                # Verify the expanded editor actually paints over the covered controls.
                await page.locator('#prompt-history').evaluate('el => el.scrollIntoView({block:"center"})')
                covered = await page.locator('#prompt-history').bounding_box()
                assert await page.evaluate('({x,y}) => document.elementFromPoint(x,y)?.matches("textarea.positive")',
                    dict(x=covered['x'] + 20, y=covered['y'] + 10))
                await page.evaluate('window.scrollTo(0,0)')
                await page.screenshot(path=str(root / f'overlay-{width}.png'))
                await page.locator('.prompt-editor-toggle').click()

            await page.set_viewport_size(dict(width=1440, height=900))
            for label in ['Workflow', 'Diffusion model', 'VAE', 'Text encoder']:
                path = '/api/workflows/saved' if label == 'Workflow' else f'/api/presets/{preset["id"]}/models'
                async with page.expect_response(lambda response: response.url.endswith(path)) as response:
                    await page.get_by_role('button', name='Refresh ' + label, exact=True).click()
                assert (await response.value).ok
                await expect(page.locator('.desktop-selector-refresh')).to_have_count(4)
                await expect(page.locator('.desktop-selector-refresh:disabled')).to_have_count(0)
                await expect(prompt).to_have_value('An unsent draft survives overlay, refresh and resizing.')
                await expect(seed).to_have_value('18446744073709551600')
            assert not stub.submissions
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 1)
            job = list(service.jobs.values())[-1]
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            await check_layout('first-queued', empty[1440])
            assert await page.locator('#job-images > button').count() == 0

            async def finish(job, name):
                queued = next(entry for entry in stub.pending if entry[1] == job['prompt_id'])
                stub.history[job['prompt_id']] = dict(prompt=queued, outputs={'save': {'images': [dict(filename=f'{name}.png', subfolder='', type='output')]}},
                    status=dict(status_str='success', messages=[]))
                stub.pending = [entry for entry in stub.pending if entry[1] != job['prompt_id']]
                await service.refresh()
                await expect(page.locator('#job-images img')).to_have_attribute('alt', name + '.png')
                await expect(page.locator('#job-images img')).to_have_js_property('complete', True)

            await finish(job, 'portrait')
            await expect(page.locator('#notice')).to_be_hidden(timeout=15000)
            await expect(page.locator('#generate-label')).to_have_text('✦ Generate')
            for width, height in SIZES:
                await page.set_viewport_size(dict(width=width, height=height))
                await check_layout('completed', empty[width])
            await page.set_viewport_size(dict(width=1440, height=900))
            image_node = await page.locator('#job-images img').element_handle()
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 2)
            job = list(service.jobs.values())[-1]
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            await expect(page.locator('#job-images img')).to_have_attribute('alt', 'portrait.png')
            assert await image_node.evaluate('el => el.isConnected')
            for width, height in SIZES:
                await page.set_viewport_size(dict(width=width, height=height))
                await check_layout('next-queued', empty[width])
            # A real running protocol event must keep the completed result too.
            await stub.emit('execution_start', dict(prompt_id=job['prompt_id']))
            await stub.emit('progress', dict(prompt_id=job['prompt_id'], value=4, max=20))
            await expect(page.locator('#job-title')).to_have_text('Creating your image')
            await expect(page.locator('#job-images img')).to_have_attribute('alt', 'portrait.png')
            await page.set_viewport_size(dict(width=1440, height=900))
            await check_layout('running', empty[1440])
            # Phone retains live-job images and original controls after the round trip.
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(page.locator('#generate-form > #resolution-card')).to_have_count(1)
            await expect(page.locator('#generate-form > #advanced')).to_have_count(1)
            await expect(page.locator('.desktop-selector-refresh')).to_have_count(0)
            await expect(page.locator('#job-images > button')).to_have_count(0)
            await expect(page.locator('#reuse-last')).to_be_visible()
            await expect(page.locator('#same-seed')).to_be_hidden()
            await expect(prompt).to_have_value('An unsent draft survives overlay, refresh and resizing.')
            await page.set_viewport_size(dict(width=1440, height=900))
            await expect(page.locator('#job-images img')).to_have_attribute('alt', 'portrait.png')
            await finish(job, 'landscape')
            await check_layout('landscape', empty[1440])
            assert len(stub.submissions) == 2
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: five desktop sizes; aligned stable panels and image frame; empty/completed/queued/running/replaced results; overlay geometry/hit testing; four refresh handlers; exact seeds/drafts and Phone restoration passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
