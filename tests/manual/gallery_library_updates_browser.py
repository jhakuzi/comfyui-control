"""Frame stability, authenticated device sharing and confirmed Clear Bin; no GPU."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings, password_hash, save_json
from test_image_workflows import ImageWorkflowStub, picture
from test_mobile_integration import until


async def main(engine, output):
    output.mkdir(parents=True)
    images = output / 'images'
    for name in ['keep.png', 'a.png', 'b.png', 'later.png', 'normal.png']:
        picture(images / name)
    originals = {path.name: path.read_bytes() for path in images.iterdir()}
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Keep this draft'})}
    stub.saved['Library updates.json'] = graph
    stub.object_info['Prompt'] = {'input': {}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/')),
        require_auth=True, password=password_hash('fixture-device-password')), images)
    preset = service.presets.create('Library updates', graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt', label='Prompt')])
    preset['comfy_source'] = 'Library updates.json'
    save_json(service.presets.path(preset['id']), preset)
    await service.start()
    await until(lambda: service.online)
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    url = str(mobile.make_url('/'))
    origin = {'Origin': url.rstrip('/')}
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            desktop_context = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block')
            phone_context = await browser.new_context(viewport=dict(width=390, height=844), has_touch=True, service_workers='block')
            desktop, phone = await desktop_context.new_page(), await phone_context.new_page()
            for page in (desktop, phone):
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.goto(url)
                await page.locator('#password').fill('fixture-device-password')
                await page.locator('#login-form button[type="submit"]').click()
                await page.wait_for_function('() => initialized && !recovering')
                await page.locator('#preset').select_option('saved:Library updates.json')
                await expect(page.locator('[data-role="positive"]')).to_have_value('Keep this draft')
                await page.locator('#gallery-tab').click()
                await expect(page.locator('#gallery-grid > button')).to_have_count(5)
            draft = await desktop.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')
            tile = desktop.get_by_role('button', name='View keep.png', exact=True)
            await tile.click()
            heart = desktop.locator('#selected-image-actions [data-action="keep"]')
            await expect(heart).to_be_enabled()
            geometry = '''() => Object.fromEntries(['full-image','reuse-image','image-details'].map(id=>{
                const r=document.getElementById(id).getBoundingClientRect();return [id,{y:r.y,height:r.height}];}))'''
            before = await desktop.evaluate(geometry)
            started, release = asyncio.Event(), asyncio.Event()
            cap_reads = []
            desktop.on('request', lambda request: cap_reads.append(request.url)
                       if request.method == 'GET' and request.url.endswith('/actions') else None)
            async def hold_mark(route):
                if route.request.method == 'POST':
                    started.set()
                    await release.wait()
                await route.continue_()
            await desktop.route('**/api/images/*/actions', hold_mark)
            await heart.click()
            await asyncio.wait_for(started.wait(), 5)
            await expect(heart).to_have_attribute('aria-busy', 'true')
            for _ in range(6):
                await desktop.evaluate('() => new Promise(requestAnimationFrame)')
                assert await desktop.evaluate(geometry) == before
                await expect(desktop.locator('.image-action-status')).to_have_text('')
            release.set()
            await expect(heart).to_have_attribute('aria-pressed', 'true')
            await expect(heart).to_be_enabled()
            assert await desktop.evaluate(geometry) == before
            assert not cap_reads, cap_reads
            await desktop.unroute('**/api/images/*/actions', hold_mark)
            await desktop.locator('#close-image').click()
            loading, loaded = asyncio.Event(), asyncio.Event()
            async def hold_favourites(route):
                response = await route.fetch()
                loading.set()
                await loaded.wait()
                await route.fulfill(response=response)
            await desktop.route('**/api/gallery?favourites=*', hold_favourites)
            await desktop.locator('#gallery-favourites').click()
            await asyncio.wait_for(loading.wait(), 5)
            grid = desktop.locator('#gallery-library-dialog .image-grid')
            pending_box = await grid.bounding_box()
            await expect(desktop.locator('#gallery-library-dialog [role="status"]')).to_have_text('')
            loaded.set()
            await expect(grid.locator('button')).to_have_count(1)
            await expect(desktop.locator('#gallery-library-dialog')).to_have_attribute('aria-busy', 'false')
            assert await grid.bounding_box() == pending_box
            popup = await desktop.locator('#gallery-library-dialog').bounding_box()
            assert popup['width'] > 760 and popup['height'] > 680, popup
            await desktop.screenshot(path=str(output / 'larger-desktop-favourites.png'))
            await desktop.locator('#close-gallery-library').click()
            await desktop.unroute('**/api/gallery?favourites=*', hold_favourites)
            # The independently authenticated Phone sees the Desktop's mark.
            await phone.locator('#gallery-favourites').click()
            await expect(phone.locator('#gallery-library-dialog .image-grid > button')).to_have_count(1)
            phone_popup = await phone.locator('#gallery-library-dialog').bounding_box()
            assert phone_popup['width'] < 390 and phone_popup['height'] <= 680, phone_popup
            await phone.locator('#gallery-library-dialog .image-grid > button').click()
            phone_heart = phone.locator('#selected-image-actions [data-action="keep"]')
            await expect(phone_heart).to_have_attribute('aria-pressed', 'true')
            await phone_heart.click()
            await expect(phone.locator('#image-dialog')).to_be_hidden()
            await expect(phone.locator('#gallery-library-dialog [role="status"]')).to_contain_text('No favourites yet')
            await phone.locator('#close-gallery-library').click()
            await desktop.bring_to_front()
            await desktop.wait_for_function('() => connected && !recovering')
            await desktop.locator('#refresh-gallery').click()
            await expect(tile.locator('.gallery-image-heart')).to_have_count(0)
            await phone.get_by_role('button', name='View keep.png', exact=True).click()
            await expect(phone_heart).to_be_enabled()
            await phone_heart.click()
            await expect(phone_heart).to_have_attribute('aria-pressed', 'true')
            await phone.locator('#close-image').click()
            await desktop.bring_to_front()
            await desktop.wait_for_function('() => connected && !recovering')
            await desktop.locator('#refresh-gallery').click()
            await expect(tile.locator('.gallery-image-heart')).to_have_count(1)

            async def mark_deleted(name):
                catalogue = await (await desktop.request.get(url + 'api/gallery?refresh=1')).json()
                item = next(item for item in catalogue if item['filename'] == name)
                response = await desktop.request.post(url + f'api/images/{item["id"]}/actions', headers=origin,
                    data=dict(action='delete', confirm=True, modified=item['modified']))
                assert response.status == 200, await response.text()
                return (await response.json())['trash']['token']
            first, failed = await mark_deleted('a.png'), await mark_deleted('b.png')
            await phone.locator('#gallery-wastebin').click()
            await expect(phone.locator('#gallery-library-dialog .image-grid > button')).to_have_count(2)
            clear = phone.locator('#clear-gallery-bin')
            clears = []
            phone.on('request', lambda request: clears.append(request.post_data_json)
                     if request.url.endswith('/api/trash/empty') else None)
            await clear.click()
            await phone.locator('#cancel-image-confirm').click()
            assert not clears and (images / 'a.png').exists() and (images / 'b.png').exists()
            original_io = service.network_io
            async def partial_failure(operation, data, **kwargs):
                if operation == 'delete' and data['token'] == failed:
                    raise OSError('Fixture read-only storage')
                return await original_io(operation, data, **kwargs)
            service.network_io = partial_failure
            later = []
            await clear.click()
            await expect(phone.locator('#image-confirm-message')).to_contain_text('2 images')
            await expect(phone.locator('#image-confirm-message')).to_contain_text('cannot be undone')
            later.append(await mark_deleted('later.png'))
            await phone.locator('#accept-image-confirm').click()
            status = phone.locator('#gallery-library-dialog [role="status"]')
            await expect(status).to_contain_text('Fixture read-only storage')
            await expect(phone.locator('#gallery-library-dialog .image-grid > button')).to_have_count(2)
            assert set(clears[0]['tokens']) == {first, failed} and later[0] not in clears[0]['tokens']
            assert clears[0]['confirm'] is True
            assert not (images / 'a.png').exists() and (images / 'b.png').exists() and (images / 'later.png').exists()
            await phone.screenshot(path=str(output / 'phone-partial-clear.png'))
            service.network_io = original_io
            # Retry from Desktop, holding the request to prove duplicate guards.
            await desktop.locator('#gallery-wastebin').click()
            await expect(desktop.locator('#gallery-library-dialog .image-grid > button')).to_have_count(2)
            await desktop.screenshot(path=str(output / 'larger-desktop-wastebin.png'))
            clear_started, clear_release = asyncio.Event(), asyncio.Event()
            attempts = []
            async def hold_clear(route):
                attempts.append(route.request.post_data_json)
                clear_started.set()
                await clear_release.wait()
                await route.continue_()
            await desktop.route('**/api/trash/empty', hold_clear)
            await desktop.locator('#clear-gallery-bin').click()
            await desktop.locator('#accept-image-confirm').click()
            await asyncio.wait_for(clear_started.wait(), 5)
            await expect(desktop.locator('#clear-gallery-bin')).to_be_disabled()
            await expect(desktop.locator('#refresh-gallery-library')).to_be_disabled()
            await desktop.evaluate('galleryLibrary.clearBin()')
            assert len(attempts) == 1
            clear_release.set()
            await expect(desktop.locator('#gallery-library-dialog [role="status"]')).to_have_text('Wastebin is empty.')
            await expect(desktop.locator('#clear-gallery-bin')).to_be_disabled()
            assert not (images / 'b.png').exists() and not (images / 'later.png').exists()
            await desktop.unroute('**/api/trash/empty', hold_clear)
            await phone.locator('#refresh-gallery-library').click()
            await expect(phone.locator('#gallery-library-dialog [role="status"]')).to_have_text('Wastebin is empty.')
            await expect(phone.locator('#clear-gallery-bin')).to_be_disabled()
            # A lost response after deletion is not automatically retried. A read
            # reconciles the result without risking a newly created replacement.
            picture(images / 'uncertain.png')
            await mark_deleted('uncertain.png')
            await desktop.locator('#refresh-gallery-library').click()
            await expect(desktop.locator('#gallery-library-dialog .image-grid > button')).to_have_count(1)
            lost_attempts = []
            async def lose_reply(route):
                lost_attempts.append(route.request.post_data_json)
                response = await route.fetch()
                assert response.ok
                await route.abort('failed')
            await desktop.route('**/api/trash/empty', lose_reply)
            await desktop.locator('#clear-gallery-bin').click()
            await desktop.locator('#accept-image-confirm').click()
            await expect(desktop.locator('#gallery-library-dialog [role="status"]')).to_contain_text('Use Refresh to check Wastebin')
            assert len(lost_attempts) == 1 and not (images / 'uncertain.png').exists()
            await desktop.unroute('**/api/trash/empty', lose_reply)
            await desktop.locator('#refresh-gallery-library').click()
            await expect(desktop.locator('#gallery-library-dialog [role="status"]')).to_have_text('Wastebin is empty.')
            await expect(desktop.locator('#clear-gallery-bin')).to_be_disabled()
            assert all((images / name).read_bytes() == originals[name] for name in ['keep.png', 'normal.png'])
            assert await desktop.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})') == draft
            assert not stub.submissions
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: stable heart/popup frames, larger Desktop dialogs, authenticated device sharing, cancel/snapshot/partial-failure Clear Bin, duplicate guard and preserved drafts passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
