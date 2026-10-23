"""Shared model/workflow refresh stability in real browsers with protocol fixtures.

Checks DOM identity, drafts, focus, scroll, height writes, catalogue changes,
structural additions/removals and failed/stale responses; no real inference.
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings, save_json
from test_image_workflows import ImageWorkflowStub
from test_mobile_integration import until


async def main(engine, root):
    root.mkdir(parents=True)
    output = root / 'images'
    output.mkdir()
    graph = {
        'text': dict(class_type='Prompt', inputs={'text': 'A quiet mountain lake in warm evening light.'}),
        'negative': dict(class_type='Prompt', inputs={'text': ''}),
        'diffusion': dict(class_type='DiffusionLoader', inputs={'unet_name': 'diffusion.gguf'}),
        'vae': dict(class_type='VAELoader', inputs={'vae_name': 'vae.safetensors'}),
        'encoder': dict(class_type='CLIPLoader', inputs={'clip_name': 'encoder.safetensors'}),
        'sampler': dict(class_type='Sampler', inputs={'seed': 18446744073709551600, 'steps': 20, 'width': 768, 'height': 1024}),
    }
    stub = ImageWorkflowStub()
    stub.saved['Desktop layout fixture.json'] = graph
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
    preset = service.presets.map(preset['id'], mappings)
    preset['comfy_source'] = 'Desktop layout fixture.json'
    save_json(service.presets.path(preset['id']), preset)
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
            await page.locator('#preset').select_option('saved:Desktop layout fixture.json')
            await expect(page.locator('#generate')).to_be_enabled()
            await expect(page.locator('.desktop-selector-refresh')).to_have_count(4)
            await expect(page.locator('#prompt-history')).to_be_hidden()
            await expect(page.locator('[data-role="negative"]')).to_be_visible()
            await page.locator('[data-role="negative"]').fill('Keep this negative prompt')
            await expect(page.locator('#negative-controls > summary')).to_be_hidden()
            await expect(page.locator('#negative-controls .prompt-editor-toggle')).to_have_count(1)
            assert await page.locator('#negative-controls .desktop-vram-cleanup').count() == 0
            for width, height in [(1000,700), (1440,1000), (1920,1080)]:
                await page.set_viewport_size(dict(width=width,height=height))
                await page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                for role in ('positive','negative'):
                    editor = page.locator(f'[data-role="{role}"]')
                    toggle = editor.locator('..').locator('.prompt-editor-toggle')
                    await toggle.scroll_into_view_if_needed()
                    card = page.locator('#generate-form > .card').first
                    before = await card.bounding_box()
                    panel_before = await page.locator('#generation-panel').bounding_box()
                    await toggle.click()
                    await expect(toggle).to_have_attribute('aria-expanded','true')
                    await page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                    bounds, panel = await editor.bounding_box(), await card.bounding_box()
                    assert abs(bounds['y'] + bounds['height'] - panel['y'] - panel['height']) < 1, (role, bounds, panel)
                    assert before == panel, (role,before,panel)
                    assert panel_before == await page.locator('#generation-panel').bounding_box()
                    assert await editor.evaluate('el => getComputedStyle(el).boxShadow') != 'none'
                    await page.screenshot(path=str(root / f'expanded-{role}-{width}.png'))
                    await toggle.click()
                    await expect(toggle).to_have_attribute('aria-expanded','false')

            await page.set_viewport_size(dict(width=390,height=844))
            await expect(page.locator('#prompt-history')).to_be_visible()
            await expect(page.locator('#negative-controls > summary')).to_be_visible()
            await expect(page.locator('#negative-controls .prompt-editor-toggle')).to_have_count(0)
            await expect(page.locator('#negative-controls')).to_have_js_property('open',False)
            await page.locator('#negative-controls').evaluate('el => el.open=true')
            await expect(page.locator('[data-role="negative"]')).to_have_value('Keep this negative prompt')
            await page.set_viewport_size(dict(width=1440,height=900))
            await expect(page.locator('[data-role="negative"]')).to_be_visible()
            await expect(page.locator('#prompt-history')).to_be_hidden()
            prompt = page.locator('[data-role="positive"]')
            await prompt.fill('An unsent draft survives overlay, refresh and resizing.')
            await page.locator('#settings-card').evaluate('el => el.open = true')
            await page.locator('#random-seed').uncheck()
            seed = page.locator('[data-role="seed"]')
            await expect(seed).to_have_value('18446744073709551600')

            selected_id = await page.evaluate('preset.id')
            model_url = f'**/api/presets/{selected_id}/models'
            for width, height in [(390, 844), (1280, 800), (1920, 1080)]:
                await page.set_viewport_size(dict(width=width, height=height))
                await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                await prompt.fill('Draft before refresh')
                await prompt.evaluate('el => {el.focus(); el.setSelectionRange(3, 8)}')
                await page.evaluate("""() => {
                    window.stableNodes = [...document.querySelectorAll('#generate-form input, #generate-form textarea, #generate-form select, .desktop-selector-refresh')];
                    window.removedControls = [];
                    window.heightWrites = [];
                    window.refreshObserver = new MutationObserver(records => {
                      for (const record of records) {
                        for (const removed of record.removedNodes)
                          if (stableNodes.some(node => node === removed || removed.contains?.(node))) removedControls.push(removed.nodeName);
                        if (record.type === 'attributes' && record.attributeName === 'style' && record.target.id === 'generation-panel') heightWrites.push(record.target.getAttribute('style'));
                      }
                    });
                    refreshObserver.observe(document.getElementById('workspace'), {subtree:true, childList:true, attributes:true, attributeFilter:['style']});
                    window.refreshFocus = document.activeElement;
                    window.refreshScroll = [scrollX, scrollY];
                }""")
                started, release = asyncio.Event(), asyncio.Event()
                async def delay(route):
                    started.set()
                    await release.wait()
                    await route.continue_()
                await page.route(model_url, delay)
                await page.locator('#refresh-models').evaluate('el => el.click()')
                await asyncio.wait_for(started.wait(), 5)
                await prompt.fill('Draft typed during refresh')
                await prompt.evaluate('el => el.setSelectionRange(4, 9)')
                release.set()
                await expect(page.locator('#refresh-models')).to_be_enabled()
                await page.unroute(model_url, delay)
                await expect(prompt).to_have_value('Draft typed during refresh')
                await expect(seed).to_have_value('18446744073709551600')
                proof = await page.evaluate("""() => {
                    refreshObserver.disconnect();
                    return {same:stableNodes.every(node => node.isConnected && (!node.id || document.getElementById(node.id) === node)),
                      removed:removedControls, heightWrites, focus:document.activeElement === refreshFocus,
                      selection:[refreshFocus.selectionStart, refreshFocus.selectionEnd],
                      scroll:[scrollX,scrollY], before:refreshScroll};
                }""")
                assert proof['same'] and not proof['removed'] and not proof['heightWrites'] and proof['focus'], proof
                assert proof['selection'] == [4,9] and proof['scroll'] == proof['before'], proof
            await page.set_viewport_size(dict(width=1440,height=900))
            await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            await page.locator('#settings-card').evaluate('el => el.open=false')
            await page.locator('#notice').evaluate('el => el.hidden=true')
            refresh_button = page.locator('.desktop-selector-refresh').nth(1)
            await refresh_button.click()
            await expect(page.locator('#refresh-models')).to_be_enabled()
            await expect(refresh_button).to_be_focused()
            # Changed option catalogues preserve selector nodes and unavailable selections.
            await page.set_viewport_size(dict(width=1440,height=900))
            selector = page.locator('[data-role="vae"]')
            original_node = await selector.element_handle()
            async def options(route):
                response = await route.fetch()
                description = await response.json()
                for field in description['fields']:
                    if field['role'] == 'vae': field['options'] = ['new-vae.safetensors']
                await route.fulfill(response=response, json=description)
            await page.route(model_url, options)
            await page.locator('#refresh-models').evaluate('el => el.click()')
            await expect(selector.locator('option[value="new-vae.safetensors"]')).to_have_count(1)
            await expect(selector).to_have_value('vae.safetensors')
            assert await original_node.evaluate('el => el.isConnected')
            await page.unroute(model_url, options)
            # A real added/removed field takes the atomic full-render fallback.
            async def structure(route):
                response = await route.fetch()
                description = await response.json()
                field = dict(next(field for field in description['fields'] if field['role'] == 'steps'))
                field.update(key='new-control', role='advanced', label='Added control')
                description['fields'].append(field)
                await route.fulfill(response=response, json=description)
            await page.route(model_url, structure)
            await page.locator('#refresh-models').evaluate('el => el.click()')
            await expect(page.locator('#control-new-control')).to_have_count(1)
            await expect(page.locator('#refresh-models')).to_be_enabled()
            await expect(prompt).to_have_value('Draft typed during refresh')
            await page.unroute(model_url, structure)
            await page.locator('#refresh-models').evaluate('el => el.click()')
            await expect(page.locator('#control-new-control')).to_have_count(0)
            await expect(page.locator('#refresh-models')).to_be_enabled()
            await expect(prompt).to_have_value('Draft typed during refresh')
            # A failed model refresh leaves the current form and drafts intact.
            await page.evaluate('window.failedNodes = [...document.querySelectorAll("#generate-form input, #generate-form select, #generate-form textarea")]')
            async def model_failure(route):
                await route.fulfill(status=400, content_type='application/json', body='{"error":"Refresh failed fixture"}')
            await page.route(model_url, model_failure)
            await page.locator('#refresh-models').evaluate('el => el.click()')
            await expect(page.locator('#notice')).to_have_text('Refresh failed fixture')
            await expect(page.locator('#refresh-models')).to_be_enabled()
            assert await page.evaluate('failedNodes.every(node => node.isConnected)')
            await expect(prompt).to_have_value('Draft typed during refresh')
            await page.unroute(model_url, model_failure)
            # Workflow options stay attached while loading, and on request failure.
            await page.evaluate('window.savedGroup = document.querySelector("#preset optgroup")')
            started, release = asyncio.Event(), asyncio.Event()
            async def workflow_failure(route):
                started.set()
                await release.wait()
                await route.abort()
            await page.route('**/api/workflows/saved', workflow_failure)
            await page.locator('#refresh-workflows').evaluate('el => el.click()')
            await asyncio.wait_for(started.wait(), 5)
            assert await page.evaluate('!savedGroup || savedGroup.isConnected')
            release.set()
            await expect(page.locator('#refresh-workflows')).to_be_enabled()
            assert await page.evaluate('!savedGroup || savedGroup.isConnected')
            await page.unroute('**/api/workflows/saved', workflow_failure)
            # A response for a workflow the user left must not resurrect its controls.
            started, release = asyncio.Event(), asyncio.Event()
            async def stale(route):
                started.set()
                await release.wait()
                await route.continue_()
            await page.route(model_url, stale)
            await page.locator('#refresh-models').evaluate('el => el.click()')
            await asyncio.wait_for(started.wait(), 5)
            await page.evaluate('document.getElementById("preset").value=""; choosePreset("")')
            release.set()
            await expect(page.locator('#refresh-models')).to_be_enabled()
            await expect(page.locator('#prompt-controls textarea')).to_have_count(0)
            assert await page.evaluate('preset === null')
            assert not stub.submissions
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: delayed refresh DOM identity, focus/selection/scroll, live drafts/seeds, no temporary height writes; option changes, structural additions/removals, workflow failure preservation passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
