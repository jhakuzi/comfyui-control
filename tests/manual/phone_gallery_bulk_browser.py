"""Phone Gallery spacing, shared multi-selection and touch-hold gesture checks."""
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
    for name in ['a.png', 'b.png', 'c.png', 'd.png', 'e.png']:
        picture(images / name)
    originals = {p.name: p.read_bytes() for p in images.iterdir()}
    stub = ImageWorkflowStub()
    graph = {'text': dict(class_type='Prompt', inputs={'text': 'Keep this Phone draft'})}
    stub.saved['Phone Gallery.json'] = graph
    stub.object_info['Prompt'] = {'input': {}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), images)
    preset = service.presets.create('Phone Gallery', graph)
    preset = service.presets.map(preset['id'], [dict(node='text', input='text', role='positive', key='prompt', label='Prompt')])
    preset['comfy_source'] = 'Phone Gallery.json'
    save_json(service.presets.path(preset['id']), preset)
    await service.start()
    await until(lambda: service.online)
    http = TestServer(MobileHTTP(service).app())
    await http.start_server()
    errors, prompts, posts = [], [], []
    try:
        async with async_playwright() as pw:
            browser = await getattr(pw, engine).launch()
            context = await browser.new_context(viewport=dict(width=390, height=844), has_touch=True, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: (prompts.append(d.message), asyncio.create_task(d.dismiss())))
            page.on('request', lambda r: posts.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/actions') else None)
            await page.goto(str(http.make_url('/')))
            await page.wait_for_function('() => initialized && !recovering')
            await page.locator('#preset').select_option('saved:Phone Gallery.json')
            await page.locator('#gallery-tab').tap()
            await expect(page.locator('#gallery-grid > button')).to_have_count(5)
            draft = await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')
            select = page.locator('#select-gallery-images')
            menu = page.locator('#gallery-selection-menu')
            tile = lambda name: page.locator('#gallery-grid').get_by_role('button', name='View '+name, exact=True)
            # Keep 8px button spacing and 48px targets at narrow/landscape/tablet sizes.
            for width,height in [(390,844),(320,568),(430,932),(768,1024),(844,390),(390,844)]:
                await page.set_viewport_size(dict(width=width,height=height))
                await expect(page.locator('#gallery-page .eyebrow')).to_be_hidden()
                await expect(page.locator('#gallery-page h1')).to_have_text('Your gallery')
                await expect(page.locator('#gallery-page > .heading #select-gallery-images')).to_be_visible()
                ids = await page.locator('#gallery-page .gallery-library-tools > button').evaluate_all('els=>els.map(e=>e.id)')
                assert ids==['refresh-gallery','select-gallery-images','gallery-wastebin','gallery-favourites']
                boxes=[await page.locator('#'+id).bounding_box() for id in ids]
                assert all(b['width']>=48 and b['height']>=48 for b in boxes)
                assert all(b['x']-a['x']-a['width']>=7.9 for a,b in zip(boxes,boxes[1:]))
                assert max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<1
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert await page.locator('#select-gallery-images svg').is_visible()
                assert await page.locator('#gallery-page > .comparison-actions > button').count()==2
                heading=await page.locator('#gallery-page > .heading').bounding_box()
                compare=await page.locator('#gallery-page > .comparison-actions').bounding_box()
                grid=await page.locator('#gallery-grid').bounding_box()
                assert compare['y']-heading['y']-heading['height']<=8.1
                assert grid['y']-compare['y']-compare['height']<=8.1
            await page.screenshot(path=str(output/'phone-compact-gallery.png'))
            await tile('a.png').tap()
            await expect(page.locator('#image-dialog')).to_be_visible()
            await page.locator('#close-image').tap()
            await select.tap()
            for name in ['a.png','b.png','c.png']: await tile(name).tap()
            await expect(page.locator('.gallery-bulk-count')).to_have_text('3 selected')
            await expect(page.locator('#image-dialog')).to_be_hidden()
            await expect(select).to_have_attribute('aria-pressed','true')
            await expect(menu).to_be_hidden()
            target=tile('a.png')
            async def pointer(kind, dx=0, primary=True, pointer_id=8):
                box=await target.bounding_box()
                await target.dispatch_event(kind,dict(pointerId=pointer_id,pointerType='touch',isPrimary=primary,
                    clientX=box['x']+25+dx,clientY=box['y']+25,bubbles=True,button=0))
            # Movement, cancellation, multitouch and scroll cannot trigger a hold.
            for cancel in ['move','cancel','multitouch','scroll']:
                await pointer('pointerdown')
                if cancel=='move': await pointer('pointermove',dx=30)
                elif cancel=='cancel': await pointer('pointercancel')
                elif cancel=='multitouch': await pointer('pointerdown',primary=False,pointer_id=9)
                else: await page.evaluate('document.dispatchEvent(new Event("scroll"))')
                await page.wait_for_timeout(620)
                await expect(menu).to_be_hidden()
                await pointer('pointerup')
            # Chromium exercises a native held touchscreen contact; WebKit uses
            # PointerEvents (the browser API cannot send held touch contacts there).
            async def hold_selected():
                await target.scroll_into_view_if_needed()
                if engine=='chromium':
                    session=await context.new_cdp_session(page)
                    box=await target.bounding_box()
                    await session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[dict(x=box['x']+25,y=box['y']+25)]))
                    await expect(menu).to_be_visible()
                    await session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
                    await session.detach()
                else:
                    await pointer('pointerdown')
                    await expect(menu).to_be_visible()
                    await pointer('pointerup')
                    await target.dispatch_event('click',dict(bubbles=True,cancelable=True))
                await expect(target).to_have_attribute('aria-pressed','true')
                await expect(page.locator('.gallery-bulk-count')).to_have_text('3 selected')
                bounds=await menu.bounding_box()
                size=page.viewport_size
                assert bounds['x']>=0 and bounds['x']+bounds['width']<=size['width']
                assert bounds['y']>=0 and bounds['y']+bounds['height']<=size['height']
            await hold_selected()
            await page.screenshot(path=str(output/'phone-hold-selection-menu.png'))
            await page.locator('#favourite-gallery-selected').tap()
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('3 images added to Favourites')
            assert len(posts)==3 and all(p['keep'] is True for p in posts)
            for name in ['a.png','b.png','c.png']: await tile(name).tap()
            await hold_selected()
            await page.locator('#delete-gallery-selected').tap()
            await expect(page.locator('#image-confirm-message')).to_contain_text('3 selected images')
            await page.locator('#cancel-image-confirm').tap()
            assert len(posts)==3
            await hold_selected()
            await page.locator('#delete-gallery-selected').tap()
            await page.locator('#accept-image-confirm').tap()
            await expect(page.locator('#gallery-grid > button')).to_have_count(2)
            assert len(posts)==6 and len(service.image_library.entries(service.output_scope,None,shared=True))==3
            assert all((images/name).read_bytes()==data for name,data in originals.items())
            # Compare and ordinary viewing still work; mode/breakpoint changes reset selection.
            await page.locator('#select-compare').tap()
            await tile('d.png').tap(); await tile('e.png').tap()
            await expect(page.locator('#compare-images')).to_be_enabled()
            await select.tap()
            await tile('d.png').tap()
            await page.set_viewport_size(dict(width=1440,height=1000))
            await expect(page.locator('#gallery-page > .comparison-actions > #select-gallery-images')).to_be_visible()
            await expect(select).to_have_attribute('aria-pressed','false')
            await expect(page.locator('#select-gallery-images .gallery-select-label')).to_have_text('Select')
            await expect(page.locator('#select-gallery-images svg')).to_be_hidden()
            assert await page.locator('#gallery-page .gallery-library-tools > button').count()==3
            assert await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')==draft
            assert not errors and not prompts and not stub.submissions,(errors,prompts)
            await browser.close()
    finally:
        await http.close(); await service.stop(); await upstream.close()
    print(f'{engine}: compact Phone Gallery, icon placement/touch spacing, hold cancellation/release guard, shared bulk actions, confirmation, Compare/Desktop preservation passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
