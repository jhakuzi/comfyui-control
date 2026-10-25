"""Real-API bulk selection, in-app confirmation and missing-original Bin cleanup."""
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
    for name in ['a.png', 'b.png', 'c.png', 'd.png', 'e.png', 'single.png', 'phone.png']:
        picture(images / name)
    originals = {p.name: p.read_bytes() for p in images.iterdir()}
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Preserve this draft'})}
    stub.saved['Bulk fixture.json'] = graph
    stub.object_info['Prompt'] = {'input': {}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Bulk fixture', graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt', label='Prompt')])
    preset['comfy_source'] = 'Bulk fixture.json'
    save_json(service.presets.path(preset['id']), preset)
    await service.start()
    await until(lambda: service.online)
    http = TestServer(MobileHTTP(service).app())
    await http.start_server()
    url = str(http.make_url('/'))
    errors, browser_prompts, posts = [], [], []
    try:
        async with async_playwright() as pw:
            browser = await getattr(pw, engine).launch()
            context = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: (browser_prompts.append(d.message), asyncio.create_task(d.dismiss())))
            page.on('request', lambda r: posts.append(r.post_data_json) if r.method == 'POST' and r.url.endswith('/actions') else None)
            await page.goto(url)
            await page.wait_for_function('() => initialized && !recovering')
            await page.locator('#preset').select_option('saved:Bulk fixture.json')
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#gallery-grid > button')).to_have_count(7)
            draft = await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')
            select = page.locator('#select-gallery-images')
            tile = lambda name: page.locator('#gallery-grid').get_by_role('button', name='View ' + name, exact=True)
            async def choose(*names):
                if await select.get_attribute('aria-pressed') != 'true':
                    await select.click()
                for name in names:
                    await tile(name).click()
            async def bulk_action(action):
                await page.locator('#gallery-grid .gallery-bulk-selected').first.click(button='right')
                await expect(page.locator('#gallery-selection-menu')).to_be_visible()
                await page.locator('#' + ('favourite-gallery-selected' if action == 'keep' else 'delete-gallery-selected')).click()
            # The same icon nodes sit beside Compare at wide/minimum Desktop
            # widths, and restore their original Phone heading without duplication.
            await page.evaluate('window.originalGalleryTools = document.querySelector("#gallery-page .gallery-library-tools")')
            for width, height in [(1440, 1000), (1000, 600), (390, 844), (1440, 1000)]:
                await page.set_viewport_size(dict(width=width, height=height))
                desktop = width >= 1000 and height >= 600
                parent = '.comparison-actions' if desktop else '.heading'
                await expect(page.locator(f'#gallery-page > {parent} > .gallery-library-tools')).to_be_visible()
                assert await page.evaluate('originalGalleryTools === document.querySelector("#gallery-page .gallery-library-tools")')
                assert await page.locator('#gallery-page .gallery-library-tools').count() == 1
                if desktop:
                    ids = ['select-compare', 'select-gallery-images', 'compare-images', 'refresh-gallery', 'gallery-wastebin', 'gallery-favourites']
                    row = [await page.locator('#'+id).bounding_box() for id in ids]
                    assert max(b['y'] for b in row) - min(b['y'] for b in row) <= 1
                    assert all(a['x']+a['width'] <= b['x'] for a,b in zip(row,row[1:]))
                    assert row[-1]['x'] + row[-1]['width'] <= width
                    for icon in row[-3:]: assert icon['width'] >= 48 and icon['height'] >= 48
            boxes = [await page.locator('#' + id).bounding_box() for id in ['select-compare', 'select-gallery-images', 'compare-images']]
            assert boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x']
            assert abs(boxes[0]['width'] - boxes[1]['width']) < 1 and abs(boxes[2]['width'] - 2 * boxes[0]['width']) < 1
            await expect(page.locator('#gallery-page h1')).to_be_hidden()
            await expect(page.locator('#gallery-page .eyebrow')).to_be_hidden()
            await expect(page.locator('#gallery-page > .heading + .hint')).to_be_hidden()
            await expect(page.locator('#refresh-gallery')).to_be_visible()
            await page.screenshot(path=str(output / 'desktop-gallery-single-toolbar.png'))
            grid_top = (await page.locator('#gallery-grid').bounding_box())['y']
            # Comparison still selects exactly A/B; entering bulk ends compare mode.
            await page.locator('#select-compare').click()
            await tile('a.png').click()
            await tile('b.png').click()
            await expect(page.locator('#compare-images')).to_be_enabled()
            await choose('a.png', 'b.png', 'c.png')
            await expect(page.locator('.gallery-bulk-count')).to_have_text('3 selected')
            await expect(page.locator('.gallery-bulk-count')).to_be_hidden()
            await expect(page.locator('.gallery-bulk-help')).to_be_hidden()
            assert (await page.locator('#gallery-grid').bounding_box())['y'] == grid_top
            assert await page.locator('.comparison-selected').count() == 0
            await expect(page.locator('#compare-images')).to_be_disabled()
            await expect(page.locator('#image-dialog')).to_be_hidden()
            # Actions are in a context menu, never permanent buttons above the grid.
            menu = page.locator('#gallery-selection-menu')
            assert await page.locator('.gallery-bulk-actions button').count() == 0
            await expect(menu).to_be_hidden()
            selection = page.locator('#gallery-grid .gallery-bulk-selected').first
            await selection.click(button='right')
            await expect(menu).to_be_visible()
            await expect(page.locator('#favourite-gallery-selected')).to_be_focused()
            await page.keyboard.press('ArrowDown')
            await expect(page.locator('#delete-gallery-selected')).to_be_focused()
            await page.keyboard.press('ArrowUp')
            await expect(page.locator('#favourite-gallery-selected')).to_be_focused()
            await page.keyboard.press('Escape')
            await expect(menu).to_be_hidden()
            await expect(selection).to_be_focused()
            assert not posts
            await selection.press('Shift+F10')
            await expect(menu).to_be_visible()
            await page.keyboard.press('End')
            await expect(page.locator('#delete-gallery-selected')).to_be_focused()
            await page.keyboard.press('Home')
            await expect(page.locator('#favourite-gallery-selected')).to_be_focused()
            await page.keyboard.press('Tab')
            await expect(menu).to_be_hidden()
            assert not posts
            await selection.click(button='right')
            await page.locator('.tabs').click(position=dict(x=5,y=5))
            await expect(menu).to_be_hidden()
            await expect(page.locator('.gallery-bulk-count')).to_have_text('3 selected')
            await expect(page.locator('.gallery-bulk-count')).to_be_hidden()
            await expect(page.locator('.gallery-bulk-help')).to_be_hidden()
            assert (await page.locator('#gallery-grid').bounding_box())['y'] == grid_top
            # Near the viewport edge, keep every menu item reachable.
            await page.evaluate('''() => {
                const button = document.querySelector('#gallery-grid .gallery-bulk-selected');
                button.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true,cancelable:true,
                    clientX:innerWidth-2,clientY:innerHeight-2}));
            }''')
            await expect(menu).to_be_visible()
            bounds = await menu.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 1440
            assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= 1000
            await page.screenshot(path=str(output / 'desktop-selection-context-menu.png'))
            await page.evaluate('window.dispatchEvent(new Event("resize"))')
            await expect(menu).to_be_hidden()
            # Hold a response: one request, no duplicate operation, fixed snapshot.
            first_started, release = asyncio.Event(), asyncio.Event()
            async def hold(route):
                if route.request.method == 'POST':
                    first_started.set()
                    await release.wait()
                await route.continue_()
            await page.route('**/api/images/*/actions', hold)
            await bulk_action('keep')
            await asyncio.wait_for(first_started.wait(), 5)
            await expect(page.locator('#delete-gallery-selected')).to_be_disabled()
            await page.evaluate('galleryBulk.perform("keep")')
            assert len(posts) == 1
            release.set()
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('3 images added to Favourites')
            await page.unroute('**/api/images/*/actions', hold)
            assert len(posts) == 3 and all(p['keep'] is True for p in posts)
            assert (await page.locator('#gallery-grid').bounding_box())['y'] == grid_top
            assert await page.locator('#gallery-grid .gallery-image-heart').count() == 3
            # Re-favouriting is an explicit true, never a toggle that removes a heart.
            await choose('a.png', 'd.png')
            await bulk_action('keep')
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('2 images added to Favourites')
            assert len(posts) == 5 and await tile('a.png').locator('.gallery-image-heart').count() == 1
            await choose('a.png', 'b.png', 'c.png')
            await page.screenshot(path=str(output / 'desktop-multi-selection.png'))
            await bulk_action('delete')
            await expect(page.locator('#image-confirm-dialog')).to_be_visible()
            await expect(page.locator('#image-confirm-message')).to_contain_text('3 selected images')
            assert await page.evaluate('document.activeElement.id') == 'cancel-image-confirm'
            await page.keyboard.press('Escape')
            assert len(posts) == 5
            # A denied image stays selected; successful virtual deletes retain originals.
            async def deny_b(route):
                if route.request.method == 'POST' and route.request.post_data_json['action'] == 'delete':
                    await route.fulfill(status=400, content_type='application/json', body='{"error":"Fixture image permission denied"}')
                else:
                    await route.continue_()
            b = next(item for item in service.images.values() if item['filename'] == 'b.png')
            await page.route(f'**/api/images/{b["id"]}/actions', deny_b)
            await bulk_action('delete')
            await page.locator('#accept-image-confirm').click()
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('Fixture image permission denied')
            await expect(page.locator('.gallery-bulk-count')).to_have_text('1 selected')
            await expect(tile('b.png')).to_have_attribute('aria-pressed', 'true')
            assert all((images / name).read_bytes() == value for name, value in originals.items())
            await page.unroute(f'**/api/images/{b["id"]}/actions', deny_b)
            await bulk_action('delete')
            await page.locator('#accept-image-confirm').click()
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('1 image moved to Wastebin')
            # Replaced versions must be explicitly selected again after refresh.
            await choose('e.png')
            picture(images / 'e.png')
            await page.locator('#refresh-gallery').click()
            await expect(page.locator('.gallery-bulk-count')).to_have_text('0 selected')
            # Leave bulk, then verify single-image Delete uses the same app dialog.
            await select.click()
            await tile('single.png').click()
            delete = page.locator('#selected-image-actions [data-action="trash"]')
            await expect(delete).to_be_enabled()
            await delete.click()
            await expect(page.locator('#image-confirm-message')).to_contain_text('single.png')
            await page.locator('#cancel-image-confirm').click()
            assert (images / 'single.png').exists()
            await delete.click()
            await page.locator('#accept-image-confirm').click()
            await until(lambda: len(service.image_library.deleted) == 4)
            await page.locator('#close-image').click()
            # Missing original: named placeholder, confirmed Clear Bin finishes it.
            (images / 'a.png').unlink()
            await page.locator('#gallery-wastebin').click()
            await expect(page.locator('#gallery-library-dialog .image-grid > button')).to_have_count(4)
            await expect(page.locator('#gallery-library-dialog .missing')).to_contain_text('a.png')
            await page.locator('#clear-gallery-bin').click()
            await expect(page.locator('#image-confirm-message')).to_contain_text('cannot be undone')
            await page.screenshot(path=str(output / 'clear-bin-confirmation.png'))
            await page.locator('#cancel-image-confirm').click()
            assert len(service.image_library.entries(service.output_scope, None, shared=True)) == 4
            await page.locator('#clear-gallery-bin').click()
            await page.locator('#accept-image-confirm').click()
            await expect(page.locator('#gallery-library-dialog [role="status"]')).to_have_text('Wastebin is empty.')
            await page.locator('#close-gallery-library').click()
            for name in ['a.png', 'b.png', 'c.png', 'single.png']:
                assert not (images / name).exists()
            assert (images / 'd.png').read_bytes() == originals['d.png']
            # Phone has original two-button comparison row, no bulk UI; in-app Delete.
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(select).to_be_hidden()
            await expect(page.locator('#gallery-page h1')).to_be_visible()
            await expect(menu).to_be_hidden()
            await expect(page.locator('.gallery-bulk-actions')).to_be_hidden()
            await page.locator('#refresh-gallery').click()
            await tile('phone.png').click()
            await expect(delete).to_be_enabled()
            await delete.click()
            await expect(page.locator('#image-confirm-dialog')).to_be_visible()
            await page.screenshot(path=str(output / 'phone-delete-confirmation.png'))
            await page.locator('#cancel-image-confirm').click()
            await page.locator('#close-image').click()
            # A lost response may have persisted a heart. Stop, retain selection,
            # reconcile with GET and only repeat an explicitly requested keep:true.
            await page.set_viewport_size(dict(width=1440, height=1000))
            for name in ['lost-one.png', 'lost-two.png', 'nav-one.png', 'nav-two.png']:
                picture(images / name)
            await page.locator('#refresh-gallery').click()
            await expect(tile('lost-one.png')).to_be_visible()
            await choose('lost-one.png', 'lost-two.png')
            attempts = []
            async def lost_reply(route):
                if route.request.method == 'POST':
                    attempts.append(route.request.post_data_json)
                    response = await route.fetch()
                    assert response.ok
                    await route.abort('failed')
                else:
                    await route.continue_()
            await page.route('**/api/images/*/actions', lost_reply)
            await bulk_action('keep')
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('Refresh Gallery to check')
            assert len(attempts) == 1
            await page.unroute('**/api/images/*/actions', lost_reply)
            await page.locator('#refresh-gallery').click()
            await expect(tile('lost-one.png').locator('.gallery-image-heart')).to_have_count(1)
            await expect(page.locator('.gallery-bulk-count')).to_have_text('2 selected')
            await bulk_action('keep')
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('2 images added to Favourites')
            # Navigating away while the first confirmed POST is in flight stops
            # remaining batch requests; returning reads the committed server state.
            await choose('nav-one.png', 'nav-two.png')
            navigation_started, navigation_release = asyncio.Event(), asyncio.Event()
            navigation_attempts = []
            async def hold_navigation(route):
                if route.request.method == 'POST':
                    navigation_attempts.append(route.request.post_data_json)
                    navigation_started.set()
                    await navigation_release.wait()
                await route.continue_()
            await page.route('**/api/images/*/actions', hold_navigation)
            await bulk_action('delete')
            await page.locator('#accept-image-confirm').click()
            await asyncio.wait_for(navigation_started.wait(), 5)
            await page.locator('#create-tab').click()
            navigation_release.set()
            await page.wait_for_function('() => !galleryBulk.pending')
            assert len(navigation_attempts) == 1
            await page.unroute('**/api/images/*/actions', hold_navigation)
            await page.locator('#gallery-tab').click()
            await expect(tile('nav-one.png')).to_have_count(0)
            await expect(tile('nav-two.png')).to_be_visible()
            await expect(select).to_have_attribute('aria-pressed', 'false')
            assert (images / 'nav-one.png').is_file() and (images / 'nav-two.png').is_file()
            assert await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})') == draft
            assert not errors and not browser_prompts, (errors, browser_prompts)
            assert not stub.submissions
            await browser.close()
    finally:
        await http.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: bulk favourites/deletion, permissions, duplicate guard, version pruning, Compare/Phone preservation, in-app confirmations and missing-original Clear Bin passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
