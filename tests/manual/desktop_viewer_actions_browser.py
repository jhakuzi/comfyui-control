"""Same image controls in regular/enlarged desktop previews; protocol fixtures only."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
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
from comfyui_control.mobile.workflows import suggested_mappings
from test_image_reuse import image_graph
from test_image_workflows import ImageWorkflowStub
from test_mobile_integration import until

CONTROLS = ['#previous-image', '#download-image', '#next-image',
            '#selected-image-actions [data-action="edit"]', '#selected-image-actions [data-action="upscale"]', '#desktop-show-details',
            '#selected-image-actions [data-action="trash"]', '#reuse-selected-image', '#vary-selected-image']


async def main(engine, root):
    root.mkdir(parents=True)
    output = root / 'output'
    output.mkdir()
    graph = image_graph()
    originals = {}
    for name, width, height, metadata in [('portrait.png', 640, 960, True),
                                         ('landscape.png', 1200, 800, True),
                                         ('foreign.png', 640, 960, True),
                                         ('plain.png', 640, 960, False)]:
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor('#456b89'))
        if metadata:
            image.setText('prompt', json.dumps(graph))
        assert image.save(str(output / name))
        originals[name] = (output / name).read_bytes()
    stub = ImageWorkflowStub()
    for node in graph.values():
        stub.object_info.setdefault(node['class_type'], {'input': {}})
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/')),
                            share_image_settings=True), output)
    preset = service.presets.create('Viewer actions fixture', graph)
    service.presets.map(preset['id'], suggested_mappings(graph, stub.object_info))
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    errors, posts = [], []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport={'width':1440,'height':900},
                                                service_workers='block', reduced_motion='reduce')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: posts.append((request.url, request.post_data_json))
                    if request.method == 'POST' and '/api/images/' in request.url else None)
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
            await expect(page.locator('#gallery-grid > button')).to_have_count(4)
            cookie = next(item['value'] for item in await context.cookies() if item['name']=='mobile_client')
            owner = hashlib.sha256(cookie.encode()).hexdigest()
            for image in service.images.values():
                service.image_owners[service.image_ownership_key(image)] = 'other-browser' if image['filename']=='foreign.png' else owner

            async def choose(name, enlarged):
                if await page.locator('#desktop-image-zoom').is_visible():
                    await page.locator('#desktop-close-zoom').click()
                await page.get_by_role('button', name='View ' + name, exact=True).click()
                await expect(page.locator('#selected-image-name')).to_have_text(name)
                await expect(page.locator('#desktop-selected-stage .image-heart')).to_be_enabled()
                if enlarged:
                    await page.locator('#selected-image-preview').dblclick()
                    await expect(page.locator('#desktop-image-zoom')).to_be_visible()

            async def skins(reset=True):
                if reset:
                    await page.mouse.move(0, 0)
                return await page.evaluate('''selectors => selectors.map(selector => {
                    const el=document.querySelector(selector), css=getComputedStyle(el);
                    return Object.fromEntries(['color','backgroundColor','backgroundImage','borderColor',
                        'borderWidth','borderRadius','height','minHeight','padding','fontFamily','fontSize',
                        'fontWeight','lineHeight','gap','boxShadow','transition'].map(key=>[key,css[key]]));
                })''', CONTROLS)

            # Every original node must survive repeated opening, navigation and closing.
            await choose('portrait.png', False)
            await page.evaluate('selectors => window.originalControls=selectors.map(s=>document.querySelector(s))', CONTROLS)
            regular_skins = await skins()
            await page.locator('#selected-image-actions [data-action="edit"]').hover()
            regular_hover = await skins(False)
            await page.screenshot(path=str(root/'regular-preview.png'), full_page=True)
            await page.locator('#selected-image-preview').dblclick()
            enlarged_skins = await skins()
            assert enlarged_skins == regular_skins, [(CONTROLS[i], key, value, enlarged_skins[i][key])
                for i, skin in enumerate(regular_skins) for key, value in skin.items() if value!=enlarged_skins[i][key]]
            assert await page.evaluate('selectors => selectors.every((s,i)=>document.querySelector(s)===originalControls[i])', CONTROLS)
            await page.locator('#selected-image-actions [data-action="edit"]').hover()
            assert await skins(False) == regular_hover
            await page.mouse.move(0,0)
            for width, height in [(1280,800),(1440,900),(1920,1080),(2560,1440)]:
                await page.set_viewport_size({'width':width,'height':height})
                viewer = page.locator('#desktop-image-zoom > .viewer')
                await viewer.evaluate('el=>el.scrollTop=0')
                geometry = await page.evaluate('''() => {
                    const rect=id=>document.getElementById(id).getBoundingClientRect();
                    const img=rect('selected-image-preview'), tools=rect('desktop-zoom-controls');
                    const save=rect('download-image'), previous=rect('previous-image'), next=rect('next-image');
                    const rows=[document.querySelector('#image-browse-tools > .actions'),
                        document.querySelector('#selected-image-actions .saved-image-buttons'),
                        document.querySelector('.selected-image-reuse')].map(el=>el.getBoundingClientRect());
                    const viewer=document.querySelector('#desktop-image-zoom > .viewer');
                    const frame=rect('desktop-image-zoom'), viewport=viewer.getBoundingClientRect();
                    return {insets:[viewport.top-frame.top,frame.bottom-viewport.bottom,img.left-frame.left,frame.right-img.right],
                        imageHeight:img.height,controlsTop:tools.top,controlsRight:tools.right,controlsBottom:tools.bottom,imageTop:img.top,imageRight:img.right,saveWidth:save.width,
                        previous:previous.width,next:next.width,firstRow:rows[0].top,imageBottom:img.bottom,
                        rowGaps:[rows[1].top-rows[0].bottom,rows[2].top-rows[1].bottom],
                        scroll:viewer.scrollHeight>viewer.clientHeight,noHorizontal:viewer.scrollWidth<=viewer.clientWidth+1};
                }''')
                assert abs(geometry['controlsTop']-geometry['imageTop']-8)<1, geometry
                assert abs(geometry['imageRight']-geometry['controlsRight']-8)<1 and geometry['controlsBottom']<geometry['imageBottom'], geometry
                assert geometry['firstRow']>=geometry['imageBottom']+5, geometry
                assert max(geometry['insets'])-min(geometry['insets'])<1, geometry
                assert geometry['previous']==44 and geometry['next']==44 and geometry['saveWidth']>200, geometry
                assert all(abs(gap-6)<1 for gap in geometry['rowGaps']) and geometry['scroll'] and geometry['noHorizontal'], geometry
                assert geometry['imageHeight']>height*.75, geometry
                await page.screenshot(path=str(root / f'viewer-image-{width}.png'))
                await viewer.evaluate('el=>el.scrollTop=el.scrollHeight')
                await expect(page.locator('#vary-selected-image')).to_be_in_viewport()
                bottom_inset = await page.evaluate('''() => {
                    const frame=document.getElementById('desktop-image-zoom').getBoundingClientRect();
                    const row=document.querySelector('.selected-image-reuse').getBoundingClientRect();
                    return frame.bottom-row.bottom;
                }''')
                assert abs(bottom_inset-geometry['insets'][0])<1, (bottom_inset, geometry)
                await page.screenshot(path=str(root / f'viewer-actions-{width}.png'))
            await page.set_viewport_size({'width':1440,'height':900})
            await page.locator('#desktop-close-zoom').click()

            for enlarged in [False, True]:
                label = 'enlarged' if enlarged else 'regular'
                await choose('portrait.png', enlarged)
                await expect(page.locator('#reuse-selected-image')).to_be_enabled()
                ordering = await page.evaluate('selectedImageItems().map(item=>item.filename)')
                index = ordering.index('portrait.png')
                steps=(ordering.index('landscape.png')-index)%len(ordering)
                for offset in range(1,steps+1):
                    await page.locator('#next-image').click()
                    await expect(page.locator('#selected-image-name')).to_have_text(ordering[(index+offset)%len(ordering)])
                if enlarged:
                    await expect(page.locator('#desktop-image-zoom')).to_be_visible()
                    await page.wait_for_function("""() => {
                        const image=document.getElementById('selected-image-preview'), box=image.getBoundingClientRect();
                        return image.complete && Math.abs(box.width/box.height-1.5)<.01;
                    }""")
                async with page.expect_download() as downloaded:
                    await page.locator('#download-image').click()
                download = await downloaded.value
                assert download.suggested_filename == 'landscape.png'
                await download.save_as(str(root / f'{label}-download.png'))
                assert QImage(str(root / f'{label}-download.png')).size()==QImage(str(output / 'landscape.png')).size()
                for action, dialog in [('edit','edit-image-dialog'),('upscale','upscale-image-dialog')]:
                    await page.locator('#selected-image-actions [data-action="'+action+'"]').click()
                    await expect(page.locator('#'+dialog)).to_be_visible()
                    await expect(page.locator('#'+action+'-image-source')).to_have_text('landscape.png')
                    await page.keyboard.press('Escape')
                for offset in range(1,steps+1):
                    if enlarged:
                        await page.locator('#desktop-close-zoom').focus()
                        await page.keyboard.press('ArrowLeft')
                    else:
                        await page.locator('#previous-image').click()
                    await expect(page.locator('#selected-image-name')).to_have_text(ordering[(ordering.index('landscape.png')-offset)%len(ordering)])
                await expect(page.locator('#selected-image-name')).to_have_text('portrait.png')
                await page.locator('#desktop-show-details').click()
                await expect(page.locator('#desktop-image-details')).to_be_visible()
                await expect(page.locator('#image-metadata')).to_contain_text('18446744073709551600')
                await page.keyboard.press('ArrowRight')
                await expect(page.locator('#selected-image-name')).to_have_text('portrait.png')
                await page.keyboard.press('Escape')
                for action, dialog in [('edit','edit-image-dialog'),('upscale','upscale-image-dialog')]:
                    await page.locator('#selected-image-actions [data-action="'+action+'"]').click()
                    await expect(page.locator('#'+dialog)).to_be_visible()
                    input_id = '#edit-image-prompt' if action=='edit' else '#upscale-image-multiplier'
                    await page.locator(input_id).fill('A bounded edit instruction' if action=='edit' else '1.5')
                    await page.keyboard.press('ArrowLeft')
                    await expect(page.locator('#selected-image-name')).to_have_text('portrait.png')
                    await page.keyboard.press('Escape')
                assert not stub.submissions and not stub.uploads
                if enlarged:
                    await expect(page.locator('#desktop-image-zoom')).to_be_visible()
                heart = page.locator('#desktop-selected-stage > .image-heart, #desktop-zoom-controls > .image-heart')
                await heart.click()
                await expect(heart).to_have_attribute('aria-pressed','true')
                await expect(heart).to_be_enabled()
                if enlarged:
                    await page.locator('#desktop-close-zoom').click()
                await page.locator('#gallery-kept').click()
                if enlarged:
                    await page.locator('#selected-image-preview').dblclick()
                await expect(page.locator('#previous-image')).to_be_disabled()
                await expect(page.locator('#next-image')).to_be_disabled()
                if enlarged:
                    await page.locator('#desktop-close-zoom').focus()
                    await page.keyboard.press('ArrowRight')
                    await expect(page.locator('#selected-image-name')).to_have_text('portrait.png')
                    await page.locator('#desktop-close-zoom').click()
                await page.locator('#gallery-all').click()
                await choose('portrait.png', enlarged)
                await heart.click()
                await expect(heart).to_have_attribute('aria-pressed','false')
                for action in ['reuse-selected-image','vary-selected-image']:
                    await choose('portrait.png', enlarged)
                    await page.locator('#'+action).click()
                    await expect(page.locator('#desktop-image-zoom')).not_to_be_visible()
                    await expect(page.locator('textarea.positive')).to_have_value(graph['prompt']['inputs']['text'])
                    if action=='vary-selected-image':
                        await expect(page.locator('#random-seed')).to_be_checked()
                    else:
                        await expect(page.locator('#random-seed')).not_to_be_checked()
                    if action=='reuse-selected-image':
                        await expect(page.locator('[data-role="seed"]')).to_have_value(str(graph['sampler']['inputs']['seed']))
                    assert not stub.submissions
                await choose('foreign.png', enlarged)
                before = len(posts)
                await page.locator('#selected-image-actions [data-action="trash"]').click()
                await expect(page.locator('#selected-image-actions .image-action-status')).to_contain_text('Only the browser')
                assert len(posts)==before
                service.settings=replace(service.settings,share_image_settings=False)
                await page.evaluate('loadGallery(true)')
                await expect(page.locator('#reuse-selected-image')).to_be_disabled()
                await expect(page.locator('#vary-selected-image')).to_be_disabled()
                disabled_skins=await skins()
                if enlarged:
                    await page.locator('#desktop-close-zoom').click()
                    assert await skins()==disabled_skins
                    await page.locator('#selected-image-preview').dblclick()
                else:
                    await page.locator('#selected-image-preview').dblclick()
                    assert await skins()==disabled_skins
                    await page.locator('#desktop-close-zoom').click()
                service.settings=replace(service.settings,share_image_settings=True)
                await page.evaluate('loadGallery(true)')
                await choose('plain.png', enlarged)
                await page.locator('#reuse-selected-image').click()
                await expect(page.locator('#selected-reuse-status')).to_contain_text('no usable ComfyUI')
                await expect(page.locator('#reuse-selected-image')).to_be_enabled()
                await expect(page.locator('#vary-selected-image')).to_be_enabled()
                await choose('landscape.png', enlarged)
                before = len(posts)
                page.once('dialog',lambda dialog: dialog.dismiss())
                await page.locator('#selected-image-actions [data-action="trash"]').click()
                assert len(posts)==before and (output/'landscape.png').is_file()
                page.once('dialog',lambda dialog: dialog.accept())
                await page.locator('#selected-image-actions [data-action="trash"]').click()
                await expect(page.locator('#desktop-image-zoom')).not_to_be_visible()
                await expect(page.get_by_role('button',name='View landscape.png',exact=True)).to_have_count(0)
                await page.locator('#gallery-trash').click()
                await page.locator('#trash-list button').click()
                await expect(page.locator('#trash-status')).to_contain_text('empty')
                assert (output/'landscape.png').read_bytes()==originals['landscape.png']
                await page.locator('#gallery-all').click()

            # A slow favourite response must not replace the image navigated to
            # inside the popup, or leave its newly loaded controls disabled.
            await choose('portrait.png', True)
            posted, release=asyncio.Event(), asyncio.Event()
            async def delayed_keep(route):
                if route.request.method!='POST':
                    await route.continue_()
                    return
                response=await route.fetch()
                posted.set()
                await release.wait()
                await route.fulfill(response=response)
            await page.route('**/api/images/*/actions',delayed_keep)
            await page.locator('#desktop-zoom-controls .image-heart').click()
            await asyncio.wait_for(posted.wait(),5)
            await page.locator('#next-image').click()
            selected_after_navigation=await page.locator('#selected-image-name').text_content()
            assert selected_after_navigation!='portrait.png'
            release.set()
            await expect(page.locator('#desktop-zoom-controls .image-heart')).to_be_enabled()
            await expect(page.locator('#selected-image-name')).to_have_text(selected_after_navigation)
            await page.unroute('**/api/images/*/actions',delayed_keep)
            await choose('portrait.png',True)
            await expect(page.locator('#desktop-zoom-controls .image-heart')).to_have_attribute('aria-pressed','true')
            await page.locator('#desktop-zoom-controls .image-heart').click()
            await expect(page.locator('#desktop-zoom-controls .image-heart')).to_have_attribute('aria-pressed','false')
            await expect(page.locator('#desktop-zoom-controls .image-heart')).to_be_enabled()
            await page.set_viewport_size({'width':390,'height':844})
            await expect(page.locator('#desktop-image-zoom')).not_to_be_visible()
            await expect(page.locator('#selected-image-tools')).not_to_have_count(0)
            await page.locator('#gallery-tab').click()
            await page.get_by_role('button',name='View portrait.png',exact=True).click()
            await expect(page.locator('#image-dialog')).to_be_visible()
            await expect(page.locator('#viewer-image-actions [data-action="edit"]')).to_be_enabled()
            mobile_heart=page.locator('#viewer-image-actions .image-heart')
            await mobile_heart.click()
            await expect(mobile_heart).to_have_attribute('aria-pressed','true')
            await expect(mobile_heart).to_be_enabled()
            await mobile_heart.click()
            await expect(mobile_heart).to_have_attribute('aria-pressed','false')
            await expect(mobile_heart).to_be_enabled()
            await page.screenshot(path=str(root/'mobile-viewer.png'))
            assert all((output/name).read_bytes()==original for name,original in originals.items())
            assert not stub.submissions and not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: identical control nodes/styles, scrolling rows, collection navigation, Save, Details, edit/upscale dialogs, favourites, Trash/restore, exact reuse/variation and mobile restoration passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
