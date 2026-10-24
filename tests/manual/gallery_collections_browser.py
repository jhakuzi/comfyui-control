"""Desktop/Phone Gallery collections using private marks and real HTTP fixtures."""
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
from test_image_workflows import ImageWorkflowStub, picture
from test_mobile_integration import until


async def main(engine, output):
    output.mkdir(parents=True)
    images = output / 'images'
    for index in range(16): picture(images / f'image-{index:02}.png', 0xff335566 + index * 0x050500)
    originals = {path.name: path.read_bytes() for path in images.iterdir()}
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Saved prompt'})}
    stub.saved['Collections.json'] = graph
    stub.object_info['Prompt'] = {'input': {}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Collections', graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt', label='Prompt')])
    preset['comfy_source'] = 'Collections.json'
    save_json(service.presets.path(preset['id']), preset)
    await service.start()
    await until(lambda: service.online)
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    errors, posts = [], []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport=dict(width=1440, height=1000), has_touch=True, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
            url = str(mobile.make_url('/'))
            await page.goto(url)
            await page.wait_for_function('() => initialized && !busy')
            await page.locator('#preset').select_option('saved:Collections.json')
            await expect(page.locator('#generate')).to_be_enabled()
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 1)
            job = list(service.jobs.values())[-1]
            stub.history[job['prompt_id']] = dict(prompt=stub.pending[0], outputs={'save': {'images': [
                dict(filename=name, subfolder='', type='output') for name in originals]}},
                status=dict(status_str='success', messages=[]))
            stub.pending = []
            await service.refresh()
            await expect(page.locator('#generation-panel')).to_have_attribute('data-status', 'complete')
            await page.locator('[data-role="positive"]').fill('Do not change this unsent draft')
            saved_form = await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')
            await page.locator('#gallery-tab').click()
            grid = page.locator('#gallery-grid')
            await expect(grid.locator(':scope > button')).to_have_count(16)
            library = page.locator('#gallery-library-dialog')
            collection_grid = library.locator('.image-grid')
            status = library.locator('[role="status"]')
            for mode, message in [('favourites', 'No favourites yet'), ('wastebin', 'Wastebin is empty')]:
                before = len(posts)
                await page.locator('#gallery-' + mode).click()
                await expect(status).to_contain_text(message)
                assert len(posts) == before
                await page.locator('#close-gallery-library').click()
            tile = grid.get_by_role('button', name='View image-00.png', exact=True)
            await tile.evaluate('el => {window.originalTile=el; window.originalThumb=el.querySelector("img");}')
            await tile.click()
            heart = page.locator('#selected-image-actions [data-action="keep"]')
            await expect(heart).to_be_enabled()
            await heart.click()
            await expect(tile.locator('.gallery-image-heart')).to_have_count(1)
            assert await tile.evaluate('el => el===originalTile && el.querySelector("img")===originalThumb')
            await page.locator('#close-image').click()
            # An older Gallery response cannot undo a confirmed heart change.
            stale_started, stale_release = asyncio.Event(), asyncio.Event()
            async def stale_gallery(route):
                response = await route.fetch()
                stale_started.set()
                await stale_release.wait()
                await route.fulfill(response=response)
            await page.route('**/api/gallery?since=*', stale_gallery)
            await page.locator('#refresh-gallery').click()
            await asyncio.wait_for(stale_started.wait(), 5)
            await tile.click()
            await expect(heart).to_be_enabled()
            await heart.click()
            await expect(heart).to_have_attribute('aria-pressed', 'false')
            stale_release.set()
            await page.wait_for_function('() => galleryPromise === null')
            await expect(tile.locator('.gallery-image-heart')).to_have_count(0)
            assert await tile.evaluate('el => el===originalTile && el.querySelector("img")===originalThumb')
            await heart.click()
            await expect(heart).to_have_attribute('aria-pressed', 'true')
            await page.locator('#close-image').click()
            await page.unroute('**/api/gallery?since=*', stale_gallery)
            await page.locator('#gallery-favourites').click()
            await expect(collection_grid.locator(':scope > button')).to_have_count(1)
            await collection_grid.locator('button').click()
            await expect(page.locator('#image-caption')).to_have_text('image-00.png')
            await heart.click()
            await expect(page.locator('#image-dialog')).to_be_hidden()
            await expect(status).to_contain_text('No favourites yet')
            await expect(tile.locator('.gallery-image-heart')).to_have_count(0)
            await page.locator('#close-gallery-library').click()
            # Populate actual private sidecars via the same authenticated endpoints.
            catalogue = await (await page.request.get(url + 'api/gallery?refresh=1')).json()
            origin = {'Origin': url.rstrip('/')}
            for item in catalogue:
                number = int(item['filename'][6:8])
                response = await page.request.post(url + f'api/images/{item["id"]}/actions', headers=origin,
                    data=dict(action='keep' if number < 8 else 'delete', keep=True, confirm=True, modified=item['modified']))
                assert response.status == 200, await response.text()
            await page.locator('#refresh-gallery').click()
            await expect(grid.locator(':scope > button')).to_have_count(8)
            await expect(grid.locator('.gallery-image-heart')).to_have_count(8)
            await page.reload()
            await expect(grid.locator('.gallery-image-heart')).to_have_count(8)

            for width, height in [(1440, 1000), (390, 844), (320, 568), (844, 390), (768, 1024)]:
                await page.set_viewport_size(dict(width=width, height=height))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                buttons = page.locator('#gallery-page > .heading .gallery-library-tools > button')
                assert await buttons.evaluate_all('els => els.map(el => el.id)') == ['refresh-gallery', 'gallery-wastebin', 'gallery-favourites']
                for button in await buttons.all():
                    box = await button.bounding_box()
                    assert box['width'] >= 48 and box['height'] >= 48, box
                await page.evaluate('window.scrollTo(0, 0)')
                await page.screenshot(path=str(output / f'gallery-{width}.png'))
                for mode in ['favourites', 'wastebin']:
                    before = len(posts)
                    await page.locator('#gallery-' + mode).click()
                    await expect(collection_grid.locator(':scope > button')).to_have_count(8)
                    geometry = await collection_grid.evaluate('''el => ({height:el.clientHeight, scroll:el.scrollHeight,
                        tiles:[...el.children].map(tile => {const r=tile.getBoundingClientRect();
                            return {top:r.top,bottom:r.bottom,width:r.width,height:r.height};})})''')
                    assert geometry['scroll'] >= geometry['height'], geometry
                    columns = 4 if width >= 1000 and height >= 600 else 2
                    for index, box in enumerate(geometry['tiles']):
                        assert abs(box['width'] - box['height']) < 1, box
                        if index >= columns: assert box['top'] >= geometry['tiles'][index-columns]['bottom'] + 9, geometry
                    bounds = await library.bounding_box()
                    assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height, bounds
                    await expect(collection_grid.locator('button').first).not_to_have_attribute('aria-busy', 'true')
                    await page.screenshot(path=str(output / f'{mode}-{width}.png'))
                    if mode == 'favourites':
                        await collection_grid.locator('button').first.click()
                        await expect(page.locator('#image-dialog')).to_be_visible()
                        await expect(heart).to_have_attribute('aria-pressed', 'true')
                        await page.locator('#close-image').click()
                    else:
                        await collection_grid.locator('button').first.click()
                        await expect(library.locator('.gallery-library-deleted')).to_be_visible()
                        await expect(status).to_have_text('Deleted image thumbnail preview')
                        await expect(library.locator('.gallery-library-deleted img')).to_have_js_property('complete', True)
                        assert await library.locator('.gallery-library-deleted img').evaluate('el => el.naturalWidth > 0')
                        await library.get_by_role('button', name='Back to Wastebin').click()
                    assert len(posts) == before, posts[before:]
                    await page.locator('#close-gallery-library').click()
                current_form = await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')
                assert current_form == saved_form, (width, current_form, saved_form)
            # Popup stays open and read-only across presentation changes.
            await page.locator('#gallery-favourites').click()
            await expect(collection_grid.locator('button')).to_have_count(8)
            await page.set_viewport_size(dict(width=1440, height=1000))
            await expect(library).to_be_visible()
            await page.locator('#close-gallery-library').click()
            # Delayed Favourites cannot repaint a subsequently opened Wastebin.
            started, release = asyncio.Event(), asyncio.Event()
            async def delayed_favourites(route):
                response = await route.fetch()
                started.set()
                await release.wait()
                await route.fulfill(response=response)
            await page.route('**/api/gallery?favourites=*', delayed_favourites)
            await page.locator('#gallery-favourites').click()
            await asyncio.wait_for(started.wait(), 5)
            await page.locator('#close-gallery-library').click()
            await page.locator('#gallery-wastebin').click()
            await expect(collection_grid.locator('button')).to_have_count(8)
            release.set()
            await expect(library.locator('h2')).to_have_text('Wastebin')
            identifiers = [await button.get_attribute('data-image-id') for button in await collection_grid.locator('button').all()]
            assert not set(identifiers) & {item['id'] for item in catalogue}
            await page.unroute('**/api/gallery?favourites=*', delayed_favourites)
            await page.locator('#close-gallery-library').click()
            async def fail(route):
                await route.fulfill(status=503, content_type='application/json', body='{"error":"Storage unavailable"}')
            await page.route('**/api/trash', fail)
            await page.locator('#gallery-wastebin').click()
            await expect(status).to_contain_text('Storage unavailable')
            await expect(page.locator('#refresh-gallery-library')).to_be_enabled()
            await page.unroute('**/api/trash', fail)
            await page.locator('#refresh-gallery-library').click()
            await expect(collection_grid.locator('button')).to_have_count(8)
            await page.locator('#close-gallery-library').click()
            # Desktop and Phone share the library while live jobs stay private.
            other = await browser.new_context(viewport=dict(width=390, height=844), service_workers='block')
            stranger = await other.new_page()
            await stranger.goto(url)
            await stranger.locator('#gallery-tab').click()
            await expect(stranger.locator('#gallery-grid > button')).to_have_count(8)
            await expect(stranger.locator('.gallery-image-heart')).to_have_count(8)
            assert await stranger.evaluate('state.jobs.length') == 0
            for mode in ['favourites', 'wastebin']:
                await stranger.locator('#gallery-' + mode).click()
                await expect(stranger.locator('#gallery-library-dialog .image-grid > button')).to_have_count(8)
                await stranger.locator('#close-gallery-library').click()
            await other.close()
            # Older favourites remain viewable and comparable beyond recent 200.
            for index in range(210): picture(images / f'newer-{index:03}.png')
            await page.locator('#refresh-gallery').click()
            await expect(grid.locator(':scope > button')).to_have_count(200)
            await expect(grid.locator('.gallery-image-heart')).to_have_count(0)
            await page.locator('#gallery-favourites').click()
            await expect(collection_grid.locator('button')).to_have_count(8)
            await collection_grid.locator('button').first.click()
            await expect(heart).to_have_attribute('aria-pressed', 'true')
            await page.locator('#vary-image').click()
            picker = page.locator('#desktop-compare-picker .image-grid')
            await expect(picker.locator('button')).to_have_count(200)
            await picker.locator('button').first.click()
            await expect(page.locator('#compare-viewport')).to_be_visible()
            await page.locator('#close-compare').click()
            await page.locator('#close-image').click()
            await page.locator('#close-gallery-library').click()
            await page.locator('#gallery-favourites').click()
            await expect(collection_grid.locator('button')).to_have_count(8)
            await page.evaluate('showLogin()')
            await expect(library).to_be_hidden()
            await expect(collection_grid.locator('button')).to_have_count(0)
            assert all((images / name).read_bytes() == contents for name, contents in originals.items())
            assert len(stub.submissions) == 1
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: Desktop/Phone collections, live heart badges, shared Favourites/Wastebin, scrolling rows, image previews, stale/error/auth guards, original files and drafts passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
