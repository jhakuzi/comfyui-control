"""Desktop hidden-folder header switch with Phone/layout and stale-read guards."""
import argparse
import asyncio
import hashlib
import time
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.settings import save_json
from test_batch_count import setup, ALICE
from test_image_actions import picture


async def main(engine, output):
    output.mkdir(parents=True)
    service, stub, upstream, graph, _ = await setup(output)
    for name in ['public.png', '.filename.png', 'normal.with.dot/plain.png', '.private/hidden.png', 'normal/.nested/deep.png', '.private/binned.png']:
        picture(service.output_dir / name)
    items = await service.gallery(ALICE)
    hidden = next(i for i in items if i['filename'] == 'hidden.png')
    await service.image_action(hidden['id'], ALICE, dict(action='keep', keep=True, modified=hidden['modified']))
    binned = next(i for i in items if i['filename'] == 'binned.png')
    await service.image_action(binned['id'], ALICE, dict(action='trash', confirm=True, modified=binned['modified']))
    stub.saved['Batch fixture.json'] = graph
    preset = service.presets.get(service.presets.list()[0]['id'])
    preset['comfy_source'] = 'Batch fixture.json'
    save_json(service.presets.path(preset['id']), preset)
    mobile = TestServer(MobileHTTP(service).app())
    errors = []
    try:
        await mobile.start_server()
        async with async_playwright() as pw:
            browser = await getattr(pw, engine).launch()
            context = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(str(mobile.make_url('/')))
            await expect(page.locator('#generate')).to_be_enabled()
            toggle = page.get_by_role('switch', name='Show images in hidden folders')
            await expect(toggle).to_have_attribute('aria-checked', 'false')
            brand = await page.locator('.brand').bounding_box()
            rect = await toggle.bounding_box()
            assert 0 <= rect['x'] - brand['x'] - brand['width'] <= 16, (brand, rect)
            await page.locator('#gallery-tab').click()
            grid = page.locator('#gallery-grid button')
            await expect(grid).to_have_count(3)
            assert set(await page.locator('#gallery-grid img').evaluate_all('els => els.map(e => e.alt)')) == {'public.png', '.filename.png', 'plain.png'}
            await page.screenshot(path=str(output / 'desktop-off.png'))
            await toggle.click()
            await expect(toggle).to_have_attribute('aria-checked', 'true')
            await expect(grid).to_have_count(5)
            await page.screenshot(path=str(output / 'desktop-on.png'))
            # A filter change drops selection for images no longer displayed.
            await page.locator('#select-gallery-images').click()
            await page.get_by_role('button', name='View hidden.png', exact=True).click()
            await toggle.click()
            await expect(grid).to_have_count(3)
            assert await page.evaluate('galleryBulk.selected.size') == 0
            await page.locator('#gallery-favourites').click()
            await expect(page.locator('#gallery-library-dialog .image-grid button')).to_have_count(0)
            await page.locator('#close-gallery-library').click()
            await page.locator('#gallery-wastebin').click()
            await expect(page.locator('#gallery-library-dialog .image-grid button')).to_have_count(1)
            await page.locator('#close-gallery-library').click()
            # Late results for the old switch setting must not repaint hidden items.
            entered, release, handled = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def delayed(route):
                if 'include_hidden=0' in route.request.url:
                    await route.continue_()
                    return
                response = await route.fetch()
                entered.set()
                await release.wait()
                await route.fulfill(response=response)
                handled.set()
            await page.route('**/api/gallery?**', delayed)
            await toggle.click()
            await entered.wait()
            await toggle.click()
            await expect(grid).to_have_count(3)
            release.set()
            await handled.wait()
            await page.unroute('**/api/gallery?**', delayed)
            await page.wait_for_timeout(150)
            await expect(grid).to_have_count(3)
            # Phone always retains the original unfiltered Gallery and brand placement.
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(toggle).to_be_hidden()
            await expect(grid).to_have_count(5)
            assert await page.locator('.brand').evaluate("e => e.parentElement.classList.contains('masthead')")
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output / 'phone.png'))
            await page.set_viewport_size(dict(width=1000, height=700))
            await expect(toggle).to_be_visible()
            await expect(grid).to_have_count(3)
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await toggle.focus()
            await page.keyboard.press('Space')
            await expect(grid).to_have_count(5)
            await page.reload()
            await expect(toggle).to_have_attribute('aria-checked', 'true')
            await expect(grid).to_have_count(5)
            await page.locator('#gallery-favourites').click()
            await expect(page.locator('#gallery-library-dialog .image-grid button')).to_have_count(1)
            await page.locator('#close-gallery-library').click()
            cookie = next(c['value'] for c in await context.cookies() if c['name'] == 'mobile_client')
            owner = hashlib.sha256(cookie.encode()).hexdigest()
            service.jobs['header-progress'] = dict(id='header-progress', owner=owner, scope=service.output_scope,
                status='running', phase='sampling', progress={'value':1, 'max':20}, prompt_id=None,
                preset=preset['id'], preset_name='Header layout check', created=time.time(), images=[])
            service.broadcast()
            await expect(page.locator('#header-generation')).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            brand = await page.locator('.brand').bounding_box()
            rect = await toggle.bounding_box()
            assert 0 <= rect['x'] - brand['x'] - brand['width'] <= 16
            await page.screenshot(path=str(output / 'desktop-active-header.png'))
            assert not errors, errors
            await context.close()
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: Desktop header placement, nested-folder filtering, persisted switch/keyboard, stale responses, selection, collections and unchanged Phone visibility passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['chromium', 'webkit', 'firefox'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
