"""Phone presentation with touch input and actual shared HTTP APIs; no GPU/device."""
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
from test_image_workflows import ImageWorkflowStub, picture
from test_mobile_integration import until


async def main(engine, output):
    output.mkdir(parents=True)
    images = output / 'images'
    for name, color in [('first.png', 0xffaa7733), ('second.png', 0xff446688)]:
        picture(images / name, color)
    originals = {path.name: path.read_bytes() for path in images.iterdir()}
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Saved prompt'}),
             'negative': dict(class_type='Prompt', inputs={'text': 'Saved negative'}),
             'sampler': dict(class_type='Sampler', inputs={'seed': 18446744073709551600, 'steps': 20})}
    stub.saved['Phone workflow.json'] = graph
    stub.object_info.update({entry['class_type']: {'input': {}} for entry in graph.values()})
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Phone workflow', graph)
    preset = service.presets.map(preset['id'], [dict(node=node, input=field, role=role, key=role, label=role.title())
        for node, field, role in [('text', 'text', 'positive'), ('negative', 'text', 'negative'),
                                  ('sampler', 'seed', 'seed'), ('sampler', 'steps', 'steps')]])
    preset['comfy_source'] = 'Phone workflow.json'
    save_json(service.presets.path(preset['id']), preset)
    await service.start()
    await until(lambda: service.online)
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport=dict(width=390, height=844), has_touch=True,
                                                device_scale_factor=2, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: (errors.append(str(error)), print(f'Browser error: {error}', file=sys.stderr)))
            await page.goto(str(mobile.make_url('/')))
            await page.wait_for_function('() => initialized && !busy')
            await page.locator('#preset').select_option('saved:Phone workflow.json')
            prompt = page.locator('[data-role="positive"]')
            try:
                await expect(prompt).to_have_value('Saved prompt')
            except AssertionError:
                print(await page.locator('#notice').text_content(), errors, file=sys.stderr)
                raise
            await expect(page.locator('#prompt-history')).to_be_visible()
            assert not await page.locator('#negative-controls').evaluate('el => el.open')
            await expect(page.locator('#negative-controls > summary')).to_be_visible()
            await expect(page.locator('.desktop-selector-refresh')).to_have_count(1)
            await expect(page.locator('.desktop-vram-cleanup')).to_be_enabled()
            async with page.expect_response('**/api/vram/cleanup') as response:
                await page.locator('.desktop-vram-cleanup').tap()
            assert (await response.value).status == 200
            await page.locator('#settings-card').evaluate('el => el.open=true')
            await page.locator('#random-seed').uncheck()
            await page.locator('#generate').tap()
            await until(lambda: len(stub.submissions) == 1)
            await expect(page.locator('#generation-dock #job-card')).to_be_visible()
            await expect(page.locator('.desktop-vram-cleanup')).to_be_disabled()
            await expect(page.locator('#selected-image-actions')).to_be_hidden()
            job = list(service.jobs.values())[-1]
            stub.history[job['prompt_id']] = dict(prompt=stub.pending[0], outputs={'save': {'images': [
                dict(filename=name, subfolder='', type='output') for name in originals]}},
                status=dict(status_str='success', messages=[]))
            stub.pending = []
            await service.refresh()
            actions = page.locator('#selected-image-actions')
            heart = actions.locator('[data-action="keep"]')
            edit = actions.locator('[data-action="edit"]')
            upscale = actions.locator('[data-action="upscale"]')
            delete = actions.locator('[data-action="trash"]')
            await expect(edit).to_be_enabled()
            await prompt.fill('Keep this Phone draft')
            saved_form = await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')

            async def original():
                for identifier in list(service.jobs):
                    if identifier != job['id'] and service.jobs[identifier]['status'] in ('queued', 'running'):
                        await service.cancel(identifier)
                await page.evaluate("async id => {selectedJob=id;applyState(await api('/api/state'));}", job['id'])
                await expect(edit).to_be_enabled()

            # The same nodes survive Phone/landscape/tablet/Desktop transitions.
            await page.evaluate('window.phonePrompt = document.querySelector(\'[data-role="positive"]\')')
            for width, height in [(320, 568), (390, 844), (430, 932), (768, 1024), (844, 390)]:
                await page.set_viewport_size(dict(width=width, height=height))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert await page.locator('#generation-dock').evaluate('el => getComputedStyle(el).position') == 'fixed'
                await expect(page.locator('#same-seed')).to_have_text('Same seed')
                await expect(page.locator('#variation')).to_have_text('New variation')
                await page.locator('#job-images > button').nth(1).tap()
                await expect(page.locator('#image-caption')).to_have_text('second.png')
                await expect(page.locator('#image-caption')).to_be_visible()
                await expect(page.locator('#vary-image')).to_have_text('New variation')
                for button in [heart, edit, upscale, delete, page.locator('#phone-compare-image')]:
                    box = await button.bounding_box()
                    assert box['width'] >= 44 and box['height'] >= 48, box
                await page.locator('#phone-compare-image').tap()
                picker = page.locator('#desktop-compare-picker')
                await expect(picker.locator('.image-grid > button')).to_have_count(1)
                bounds = await picker.bounding_box()
                assert bounds['x'] >= 0 and bounds['y'] >= 0, bounds
                assert bounds['x'] + bounds['width'] <= width and bounds['y'] + bounds['height'] <= height, bounds
                await page.screenshot(path=str(output / f'phone-picker-{width}.png'))
                await picker.locator('.image-grid > button').tap()
                await expect(page.locator('#compare-viewport')).to_be_visible()
                assert await page.evaluate('comparison.selected') == [job['images'][1]['id'], job['images'][0]['id']]
                await page.locator('#close-compare').tap()
                await expect(page.locator('#image-dialog')).to_be_visible()
                await page.locator('#close-image').tap()
                assert await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})') == saved_form
                assert await page.evaluate('phonePrompt === document.querySelector(\'[data-role="positive"]\')')
            await page.set_viewport_size(dict(width=390, height=844))
            # Phone picker rows remain square and scroll within short/portrait dialogs.
            extras = [images / f'extra-{index}.png' for index in range(8)]
            for path in extras: picture(path)
            for width, height in [(320, 568), (844, 390)]:
                await page.set_viewport_size(dict(width=width, height=height))
                await page.locator('#phone-compare-image').tap()
                grid = page.locator('#desktop-compare-picker .image-grid')
                await expect(grid.locator(':scope > button')).to_have_count(9)
                geometry = await grid.evaluate('''el => ({height:el.clientHeight, scroll:el.scrollHeight,
                    tiles:[...el.children].map(tile => {const r=tile.getBoundingClientRect();
                        return {top:r.top, bottom:r.bottom, width:r.width, height:r.height};})})''')
                assert geometry['scroll'] > geometry['height'], geometry
                for index, tile in enumerate(geometry['tiles']):
                    assert abs(tile['height'] - tile['width']) < 1, tile
                    if index >= 2: assert tile['top'] >= geometry['tiles'][index-2]['bottom'] + 9, geometry
                await page.screenshot(path=str(output / f'phone-many-{width}.png'))
                await page.get_by_role('button', name='Close comparison gallery').tap()
            for path in extras: path.unlink()
            await page.set_viewport_size(dict(width=390, height=844))
            started, release = asyncio.Event(), asyncio.Event()
            async def delayed_gallery(route):
                started.set()
                await release.wait()
                await route.continue_()
            await page.route('**/api/gallery?*', delayed_gallery)
            await page.locator('#phone-compare-image').tap()
            await asyncio.wait_for(started.wait(), 5)
            await page.get_by_role('button', name='Close comparison gallery').tap()
            async with page.expect_response('**/api/gallery?*'):
                release.set()
            await expect(page.locator('#desktop-compare-picker')).to_be_hidden()
            await page.unroute('**/api/gallery?*', delayed_gallery)
            assert await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})') == saved_form
            await page.evaluate('window.scrollTo(0, 0)')
            await page.locator('#notice').evaluate('el => el.hidden=true')
            await page.screenshot(path=str(output / 'phone-create.png'))
            await page.locator('#job-images > button').nth(1).tap()
            for action, button in [('edit', edit), ('upscale', upscale)]:
                await button.tap()
                await expect(page.locator(f'#{action}-image-source')).to_have_text('second.png')
                if action == 'edit': await page.locator('#edit-image-prompt').fill('Remember this instruction')
                await page.locator(f'#cancel-{action}-image').tap()
                await expect(button).to_be_enabled()
                assert await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})') == saved_form
                assert len(stub.submissions) == 1
            await edit.tap()
            await expect(page.locator('#edit-image-prompt')).to_have_value('Remember this instruction')
            await page.set_viewport_size(dict(width=1440, height=1000))
            await expect(page.locator('#edit-image-dialog')).to_be_hidden()
            await expect(page.locator('#phone-compare-image')).to_be_hidden()
            await expect(page.locator('#vary-image')).to_have_text('Compare')
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(page.locator('#phone-compare-image')).to_be_visible()
            await page.locator('#close-image').tap()
            await expect(page.locator('#prompt-history')).to_be_visible()
            # Native details and expanded prompt remain in normal flow on Phone.
            await expect(page.locator('#negative-controls > summary')).to_be_visible()
            assert not await page.locator('#negative-controls').evaluate('el => el.open')
            await page.locator('.prompt-editor-toggle').tap()
            assert await prompt.evaluate('el => getComputedStyle(el).position') != 'absolute'
            await page.locator('.prompt-editor-toggle').tap()
            # Existing Phone variation and full-settings reuse never submit.
            await page.locator('#variation').tap()
            await expect(page.locator('#random-seed')).to_be_checked()
            assert len(stub.submissions) == 1
            await original()
            await page.locator('#job-images > button').nth(1).tap()
            await page.locator('#reuse-image').tap()
            await expect(page.locator('[data-role="seed"]')).to_have_value('18446744073709551600')
            await expect(page.locator('#random-seed')).not_to_be_checked()
            assert len(stub.submissions) == 1
            await prompt.fill('Keep this Phone draft')
            # Real Edit/Upscale target the explicit second image and preserve drafts.
            for action in ('edit', 'upscale'):
                await original()
                await page.locator('#job-images > button').nth(1).tap()
                await actions.locator(f'[data-action="{action}"]').tap()
                if action == 'edit': await page.locator('#edit-image-prompt').fill('Golden light')
                else: await page.locator('#upscale-image-multiplier').fill('1.5')
                await page.locator(f'#{action}-image-form button[type="submit"]').tap()
                await until(lambda: len(stub.uploads) == (1 if action == 'edit' else 2))
                await expect(page.locator('#image-dialog')).to_be_hidden()
                assert QImage.fromData(stub.uploads[-1]['pixels']).pixelColor(0, 0) == QImage(str(images / 'second.png')).pixelColor(0, 0)
                sent = stub.submissions[-1]['prompt']
                if action == 'edit': assert sent['89']['inputs']['prompt'] == 'Golden light'
                else: assert sent['custom']['inputs']['scale_multiplier'] == 1.5
                await expect(prompt).to_have_value('Keep this Phone draft')
            # Uncertain submission keeps the UUID; Phone's existing Generate retries it.
            await original()
            await page.locator('#job-images > button').nth(1).tap()
            second = job['images'][1]['id']
            attempts = []
            async def lose_once(route):
                if route.request.method == 'POST':
                    attempts.append(route.request.post_data_json)
                    if len(attempts) == 1:
                        await route.abort('failed')
                        return
                await route.continue_()
            await page.route(f'**/api/images/{second}/actions', lose_once)
            await edit.tap()
            await page.locator('#edit-image-form button[type="submit"]').tap()
            await expect(actions.locator('.image-action-status')).to_contain_text('Connection lost')
            pending = await page.evaluate('readStore("pending",null)')
            assert pending['action']['image_id'] == second
            await page.locator('#close-image').tap()
            await expect(page.locator('#generate-label')).to_have_text('Retry submission')
            await page.locator('#generate').tap()
            await until(lambda: len(stub.submissions) == 4)
            assert attempts[0] == attempts[1] and attempts[0]['request_id'] == pending['request_id']
            await page.unroute(f'**/api/images/{second}/actions', lose_once)
            await original()
            await page.locator('#job-images > button').nth(1).tap()
            await heart.tap()
            await expect(heart).to_have_attribute('aria-pressed', 'true')
            await page.reload()
            await expect(prompt).to_have_value('Keep this Phone draft')
            await page.locator('#job-images > button').nth(1).tap()
            await expect(heart).to_have_attribute('aria-pressed', 'true')
            page.once('dialog', lambda dialog: dialog.dismiss())
            await delete.tap()
            assert not service.image_library.deleted
            page.once('dialog', lambda dialog: dialog.accept())
            await delete.tap()
            await until(lambda: bool(service.image_library.deleted))
            await expect(page.locator('#image-caption')).to_have_text('first.png')
            assert all((images / name).read_bytes() == data for name, data in originals.items())
            await page.screenshot(path=str(output / 'phone-viewer.png'))
            await page.evaluate('pauseConnection(); syncSelectedImageActions()')
            await expect(edit).to_be_disabled()
            await expect(actions.locator('.image-action-status')).to_contain_text('Reconnect')
            assert len(stub.submissions) == 4
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: Phone touch/layout/Compare, transitions, drafts, exact reuse/variation, Edit/Upscale, UUID retry, Favourites, virtual Delete and offline actions passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
