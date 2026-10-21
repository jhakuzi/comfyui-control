"""Desktop gallery bounds and prompt-history layout; fixture data, no inference."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QColor, QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until

SIZES = [(1280, 800), (1440, 900), (1920, 1080), (2560, 1440)]


async def main(engine, root):
    root.mkdir(parents=True)
    output = root / 'output'
    output.mkdir()
    for number in range(110):
        image = QImage(96, 144, QImage.Format.Format_RGB32)
        image.fill(QColor.fromHsv(number * 3 % 360, 130, 170))
        assert image.save(str(output / f'image-{number:03}.png'))
    graph = {key: dict(class_type='Text', inputs={'text': value})
             for key, value in [('positive', 'A landscape'), ('negative', 'blur')]}
    stub = ComfyStub(graph)
    stub.object_info = {'Text': {'input': {'required': {'text': ['STRING']}}}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    preset = service.presets.create('Desktop gallery fixture', graph)
    mappings = [dict(key=role, node=role, input='text', role=role, label=role.title())
                for role in ['positive', 'negative']]
    service.presets.map(preset['id'], mappings)
    await service.start()
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            page = await browser.new_page(viewport={'width':1440, 'height':900}, reduced_motion='reduce', service_workers='block')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
            await expect(page.locator('#generate')).to_be_enabled()
            await expect(page.locator('#gallery-grid > button')).to_have_count(110)
            assert await page.locator('button, .button').evaluate_all("els => els.every(el => getComputedStyle(el).textAlign === 'center')")
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 1)
            job = next(iter(service.jobs.values()))
            await page.locator('#cancel').click()
            await expect(page.locator('#generate')).to_be_enabled()
            for number in range(14):
                service.prompts.record(job['owner'], mappings, {
                    'positive': f'Saved prompt {number}: ' + 'Clear light over a quiet landscape. ' * 35,
                    'negative': 'Unwanted artifacts, blur. ' * 8})
            for width, height in SIZES:
                await page.set_viewport_size({'width':width, 'height':height})
                await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop')
                await page.locator('#gallery-page').scroll_into_view_if_needed()
                await page.wait_for_function("parseFloat(getComputedStyle(document.getElementById('gallery-grid')).maxHeight) > 0")
                await page.locator('#gallery-grid').evaluate('el => el.scrollTop=0')
                geometry = await page.evaluate('''() => {
                    const grid = document.getElementById('gallery-grid'), css = getComputedStyle(grid);
                    const box = grid.getBoundingClientRect(), tiles = [...grid.children].map(el => el.getBoundingClientRect());
                    const columns = css.gridTemplateColumns.split(' ').length;
                    const first = tiles[0], last = tiles[columns-1];
                    const entryHeight = first.height, gap = parseFloat(css.rowGap);
                    const expected = entryHeight * 8 + gap * 7 + parseFloat(css.paddingTop) + parseFloat(css.paddingBottom);
                    return {columns, expected, height:grid.clientHeight, scrollHeight:grid.scrollHeight,
                        entryWidth:first.width, rightGap:box.left + grid.clientWidth - parseFloat(css.paddingRight) - last.right,
                        rowEight:tiles[columns*8-1].bottom, rowNine:tiles[columns*8].top, bottom:box.bottom,
                        advanced:document.getElementById('advanced').getBoundingClientRect().top,
                        galleryBottom:document.getElementById('gallery-page').getBoundingClientRect().bottom};
                }''')
                assert geometry['entryWidth'] >= 200 and abs(geometry['rightGap']) < 1, geometry
                assert abs(geometry['height'] - geometry['expected']) <= 1, geometry
                assert geometry['scrollHeight'] > geometry['height'], geometry
                assert geometry['rowEight'] <= geometry['bottom'] and geometry['rowNine'] >= geometry['bottom'], geometry
                assert geometry['advanced'] >= geometry['galleryBottom'], geometry
                await expect(page.locator('#gallery-jobs')).not_to_be_visible()
                for identifier in ['select-compare', 'compare-images']:
                    await expect(page.locator('.library-filters > #' + identifier)).to_have_count(1)
                skins = await page.evaluate('''() => ['gallery-kept','select-compare'].map(id => {
                    const css=getComputedStyle(document.getElementById(id));
                    return [css.fontSize,css.backgroundColor,css.borderRadius,css.padding,css.textAlign,css.justifyContent];
                })''')
                assert skins[0] == skins[1] and skins[0][-2:] == ['center', 'center'], skins
                await page.screenshot(path=str(root / f'gallery-{width}.png'))
                await page.locator('#gallery-grid').evaluate('el => el.scrollTop=el.scrollHeight')
                await page.locator('#gallery-grid > button').last.scroll_into_view_if_needed()
                await expect(page.locator('#gallery-grid > button').last).to_be_in_viewport()
                await page.locator('#gallery-grid > button').last.click()
                await expect(page.locator('#generation-panel')).to_have_attribute('data-inspect', 'true')
                await expect(page.locator('#selected-image-name')).to_have_text('image-000.png')
                await page.locator('#prompt-history').click()
                await expect(page.locator('#prompt-history-dialog')).to_be_visible()
                await expect(page.locator('.prompt-entry')).to_have_count(15)
                await page.locator('#prompt-history-list').evaluate('el => el.scrollTop=0')
                history = await page.evaluate('''() => {
                    const list=document.getElementById('prompt-history-list'), b=list.getBoundingClientRect();
                    const cards=[...list.children].map(el => el.getBoundingClientRect());
                    const card=list.firstElementChild, box=card.getBoundingClientRect();
                    const remove=card.querySelector('.actions button').getBoundingClientRect();
                    return {width:document.getElementById('prompt-history-dialog').getBoundingClientRect().width,
                        top:b.top,bottom:b.bottom, firstHeight:cards[0].height,sixth:cards[5].bottom,seventh:cards[6].top,
                        overflow:list.scrollHeight > list.clientHeight, deleteInside:remove.top >= box.top && remove.right <= box.right,
                        deleteTop:remove.top-box.top,deleteRight:box.right-remove.right};
                }''')
                assert 1079 <= history['width'] <= 1081, history
                assert history['firstHeight'] > 64 and history['sixth'] <= history['bottom']+1, history
                assert history['seventh'] >= history['bottom']-1 and history['overflow'], history
                assert history['deleteInside'] and 0 <= history['deleteTop'] <= 9 and 0 <= history['deleteRight'] <= 9, history
                await page.screenshot(path=str(root / f'history-{width}.png'))
                await page.locator('#close-prompt-history').click()
            await page.locator('#select-compare').click()
            await page.locator('#gallery-grid').evaluate('el => el.scrollTop=0')
            await page.locator('#gallery-grid > button').nth(0).click()
            await page.locator('#gallery-grid > button').nth(1).click()
            await expect(page.locator('#compare-images')).to_be_enabled()
            await page.locator('#compare-images').click()
            await expect(page.locator('#compare-dialog')).to_be_visible()
            await expect(page.locator('#compare-a')).to_have_js_property('complete', True)
            await page.locator('#close-compare').click()
            await page.locator('#select-compare').click()
            await page.locator('#prompt-history').click()
            await page.locator('#prompt-history-search').fill('Saved prompt 13:')
            await expect(page.locator('.prompt-entry')).to_have_count(1)
            await page.locator('.prompt-entry .actions button').click()
            await expect(page.locator('.prompt-entry')).to_have_count(0)
            assert len(service.prompts.list(job['owner'])) == 14
            await page.locator('#prompt-history-search').fill('Saved prompt 12:')
            await expect(page.locator('.prompt-entry')).to_have_count(1)
            await page.locator('.prompt-reuse').click()
            await expect(page.locator('[data-role="positive"]')).to_have_value('Saved prompt 12: ' + 'Clear light over a quiet landscape. ' * 35)
            assert len(stub.submissions) == 1
            # Check the restored mobile controls and state after every new placement.
            await page.set_viewport_size({'width':390,'height':844})
            await expect(page.locator('html')).to_have_attribute('data-presentation','mobile')
            await expect(page.locator('[data-role="positive"]')).to_have_attribute('placeholder','Describe your image…')
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#gallery-jobs')).to_be_visible()
            await expect(page.locator('.comparison-actions > #select-compare')).to_have_count(1)
            assert not await page.locator('[data-role="positive"]').evaluate("el => el.parentElement.classList.contains('desktop-scroll-frame')")
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: full-width larger tiles, eight-row gallery scrolling, unified bar, Advanced below gallery, six larger prompt cards, delete/search/reuse and mobile restoration passed')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
