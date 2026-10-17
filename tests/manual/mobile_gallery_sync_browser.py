"""Exercise sticky gallery controls and real file changes with a ComfyUI test double."""
import argparse
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage, QColor
from test_mobile_integration import ComfyStub
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings


async def main(browser_name):
    root = Path(tempfile.mkdtemp(prefix='mobile-gallery-sync-'))
    output = root / 'output'
    output.mkdir()
    def image(name, number=0):
        result = QImage(96, 128, QImage.Format.Format_RGB32)
        result.fill(QColor.fromHsv(number * 17 % 360, 130, 180))
        path = output / name
        assert result.save(str(path))
        os.utime(path, ns=(1700000000000000000 + number * 1000000000,) * 2)
    for number in range(60):
        image(f'image{number:03}.png', number)
    upstream = TestServer(ComfyStub({}).app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    await service.start()
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors, gallery_requests = [], []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, browser_name).launch(headless=True,
                **({'args': ['--no-sandbox']} if browser_name == 'chromium' else {}))
            context = await browser.new_context(viewport={'width': 390, 'height': 844},
                is_mobile=True, has_touch=True, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: gallery_requests.append(request.url)
                    if urlsplit(request.url).path == '/api/gallery' else None)
            await page.goto(url)
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#gallery-grid > button')).to_have_count(60)
            await page.evaluate('''() => {
                document.documentElement.style.setProperty('--safe-area-top', '59px');
                document.documentElement.style.setProperty('--safe-area-bottom', '34px');
                window.scrollTo(0, document.body.scrollHeight);
            }''')

            async def reachable(top=59, bottom=34, left=0, right=0):
                viewport = page.viewport_size
                for identifier in ('select-compare', 'compare-images'):
                    button = page.locator('#' + identifier)
                    bounds = await button.bounding_box()
                    assert bounds['y'] >= top and bounds['y'] + bounds['height'] <= viewport['height'] - bottom, bounds
                    assert bounds['x'] >= left and bounds['x'] + bounds['width'] <= viewport['width'] - right, bounds
                    assert bounds['height'] >= 44
                    assert await page.evaluate('''({id,x,y}) => !!document.elementFromPoint(x,y)?.closest('#'+id)''',
                        dict(id=identifier, x=bounds['x'] + bounds['width']/2, y=bounds['y'] + bounds['height']/2))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')

            await reachable()
            await page.locator('#select-compare').tap()
            await expect(page.locator('#select-compare')).to_have_text('Done selecting')
            await reachable()
            await page.get_by_role('button', name='View image000.png', exact=True).tap()
            await page.get_by_role('button', name='View image001.png', exact=True).tap()
            await reachable()
            await expect(page.locator('#compare-images')).to_have_text('Compare · 2/2')
            await page.locator('#select-compare').tap()
            await reachable()
            await page.screenshot(path=str(root / 'gallery-sticky-controls.png'))
            await page.locator('#compare-images').tap()
            await expect(page.locator('#compare-viewport')).to_be_visible()
            cached = await page.evaluate('[...comparison.images.values()].map(image => image.url)')
            # Keep references to unchanged DOM/image objects; reconciliation must
            # not reconstruct all thumbnails just because a file disappeared.
            await page.evaluate('window.unchangedTile = document.querySelector("#gallery-grid > button")')
            (output / 'image000.png').unlink()
            await expect(page.get_by_role('button', name='View image000.png', exact=True)).to_have_count(0, timeout=10000)
            await expect(page.locator('#compare-dialog')).not_to_be_visible()
            await expect(page.locator('#compare-images')).to_have_text('Compare · 1/2')
            assert await page.evaluate('window.unchangedTile === document.querySelector("#gallery-grid > button")')
            assert await page.evaluate('(url) => fetch(url).then(() => false, () => true)', cached[0])
            await expect(page.locator('#gallery-grid .missing')).to_have_count(0)
            # Selecting a surviving image uses its current index, not the index
            # captured before deletions. An open deleted image closes on sync.
            await page.get_by_role('button', name='View image001.png', exact=True).tap()
            await expect(page.locator('#image-caption')).to_have_text('image001.png')
            (output / 'image001.png').unlink()
            await expect(page.locator('#image-dialog')).not_to_be_visible(timeout=10000)
            await expect(page.locator('#compare-images')).to_have_text('Compare · 0/2')
            old_source = await page.get_by_role('button', name='View image002.png', exact=True).locator('img').get_attribute('src')
            image('image002.png', 70)
            image('added.png', 80)
            await expect(page.get_by_role('button', name='View added.png', exact=True)).to_have_count(1, timeout=10000)
            new_source = await page.get_by_role('button', name='View image002.png', exact=True).locator('img').get_attribute('src')
            assert new_source != old_source
            # Failed requests are not deletion evidence; retain the old gallery.
            await page.route('**/api/gallery?*', lambda route: route.abort('failed'))
            await page.locator('#refresh-gallery').click()
            await expect(page.locator('#gallery-grid > button')).to_have_count(59)
            await page.unroute('**/api/gallery?*')
            for width, height, top, bottom, left, right in (
                    (320, 568, 20, 0, 0, 0), (844, 390, 0, 21, 59, 59),
                    (390, 600, 59, 34, 0, 0), (1200, 844, 0, 0, 0, 0)):
                await page.set_viewport_size(dict(width=width, height=height))
                await page.evaluate('''insets => {
                    for(const [side,value] of Object.entries(insets))
                        document.documentElement.style.setProperty('--safe-area-'+side,value+'px');
                    window.scrollTo(0,document.body.scrollHeight);
                }''', dict(top=top, bottom=bottom, left=left, right=right))
                await reachable(top, bottom, left, right)
            # Switching away suspends recurring checks; opening Gallery forces
            # reconciliation immediately, including after foreground recovery.
            await page.locator('#create-tab').click()
            count = len(gallery_requests)
            await page.wait_for_timeout(5400)
            assert len(gallery_requests) == count
            (output / 'image003.png').unlink()
            await page.locator('#gallery-tab').click()
            await expect(page.get_by_role('button', name='View image003.png', exact=True)).to_have_count(0)
            await page.evaluate('pauseConnection()')
            count = len(gallery_requests)
            await page.wait_for_timeout(5400)
            assert len(gallery_requests) == count
            (output / 'image004.png').unlink()
            await page.evaluate('foreground()')
            await expect(page.get_by_role('button', name='View image004.png', exact=True)).to_have_count(0)
            assert not errors, errors
            print(f'PASS {browser_name}: safe-area sticky selection/Done/Compare at gallery bottom, real PC deletion, selected-pair eviction, open viewer reconciliation, stable thumbnails, replacement/new files, failed-network retention, paused checks and foreground recovery.')
            print('Screenshot:', root / 'gallery-sticky-controls.png')
            await browser.close()
    finally:
        await service.stop()
        await runner.cleanup()
        await upstream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    asyncio.run(main(parser.parse_args().browser))
