"""Desktop viewer shortcuts share Gallery selection and confirmed actions."""
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
            context = await browser.new_context(viewport=dict(width=1440, height=1000), has_touch=True, service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: (prompts.append(d.message), asyncio.create_task(d.dismiss())))
            page.on('request', lambda r: posts.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/actions') else None)
            await page.goto(str(http.make_url('/')))
            await page.wait_for_function('() => initialized && !recovering')
            await page.locator('#preset').select_option('saved:Phone Gallery.json')
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#gallery-grid > button')).to_have_count(5)
            draft = await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')
            tile=lambda name: page.locator('#gallery-grid').get_by_role('button',name='View '+name,exact=True)
            await tile('c.png').click()
            image=page.locator('#full-image')
            caption=page.locator('#image-caption')
            menu=page.locator('#gallery-selection-menu')
            await expect(caption).to_have_text('c.png')
            await page.keyboard.press('ArrowRight')
            await expect(caption).to_have_text('b.png')
            await page.keyboard.press('ArrowLeft')
            await expect(caption).to_have_text('c.png')
            # Space accumulates selections through navigation, without scrolling.
            scroll=await page.evaluate('scrollY')
            for name in ['c.png','b.png','a.png']:
                await expect(caption).to_have_text(name)
                await page.keyboard.press('Space')
                await expect(image).to_have_class('viewer-image-selected')
                if name!='a.png': await page.keyboard.press('ArrowRight')
            assert await page.evaluate('galleryBulk.selected.size')==3
            assert await page.evaluate('scrollY')==scroll
            await page.keyboard.press('ArrowRight')
            await expect(caption).to_have_text('e.png')  # Existing wrap behavior.
            await page.keyboard.press('ArrowLeft')
            await expect(caption).to_have_text('a.png')
            await page.keyboard.press('Space')
            assert await page.evaluate('galleryBulk.selected.size')==2
            await page.keyboard.press('Space')
            await image.click(button='right')
            await expect(page.locator('#image-dialog > #gallery-selection-menu')).to_be_visible()
            assert await menu.evaluate('el=>!el.closest("[inert]")')
            await page.screenshot(path=str(output/'desktop-viewer-selection-menu.png'))
            # Menu arrow keys must not navigate the image underneath it.
            await page.keyboard.press('ArrowDown')
            await expect(page.locator('#delete-gallery-selected')).to_be_focused()
            await expect(caption).to_have_text('a.png')
            await page.keyboard.press('Escape')
            await expect(menu).to_be_hidden()
            await expect(page.locator('#image-dialog')).to_be_visible()
            await image.click(button='right')
            await page.locator('#favourite-gallery-selected').click()
            await expect(page.locator('.gallery-bulk-status')).to_contain_text('3 images added to Favourites')
            assert len(posts)==3 and all(p['keep'] is True for p in posts)
            assert await page.evaluate('galleryBulk.selected.size')==0
            # Backspace confirms only the current image; cancellation sends nothing.
            await image.focus()
            trash=page.locator('#selected-image-actions [data-action="trash"]')
            await expect(trash).to_be_enabled()
            await page.keyboard.press('Backspace')
            await expect(page.locator('#image-confirm-message')).to_contain_text('a.png')
            await page.locator('#cancel-image-confirm').click()
            assert len(posts)==3
            await image.focus()
            await page.keyboard.press('Backspace')
            await page.locator('#accept-image-confirm').click()
            await expect(caption).not_to_have_text('a.png')
            assert len(posts)==4
            assert posts[-1]['action']=='delete' and posts[-1]['confirm'] is True
            # Entering text in an Edit dialog cannot trigger viewer shortcuts.
            # Use a temporary editable viewer field to test the actual event guard
            # independently of which optional Edit workflow is installed.
            await page.evaluate('''() => {
                const t=document.createElement('textarea');t.id='fixture-viewer-input';
                document.querySelector('#image-dialog .viewer').append(t);t.focus();
            }''')
            before=await caption.text_content()
            await page.locator('#fixture-viewer-input').fill('abc')
            await page.keyboard.press('Backspace')
            await page.keyboard.press('Space')
            await page.keyboard.press('ArrowLeft')
            await expect(page.locator('#fixture-viewer-input')).to_have_value('ab ')
            await expect(caption).to_have_text(before)
            assert len(posts)==4
            await page.locator('#fixture-viewer-input').evaluate('el=>el.remove()')
            await image.focus()
            # A context menu without a selection selects the current image.
            await image.click(button='right')
            assert await page.evaluate('galleryBulk.selected.size')==1
            await page.locator('#delete-gallery-selected').click()
            await page.locator('#cancel-image-confirm').click()
            assert len(posts)==4
            # Select more than one image via Space, then use the same bulk deletion.
            await image.focus()
            await page.keyboard.press('ArrowLeft')
            await page.keyboard.press('Space')
            assert await page.evaluate('galleryBulk.selected.size')==2
            await image.click(button='right')
            await page.locator('#delete-gallery-selected').click()
            await expect(page.locator('#image-confirm-message')).to_contain_text('2 selected images')
            await page.locator('#accept-image-confirm').click()
            await page.wait_for_function('()=>!galleryBulk.pending')
            assert len(posts)==6
            assert len(service.image_library.entries(service.output_scope,None,shared=True))==3
            assert all((images/name).read_bytes()==data for name,data in originals.items())
            await expect(page.locator('#image-dialog')).to_be_visible()
            # Closing/reopening retains the one shared selection; Phone gets no shortcuts.
            await image.focus()
            await page.keyboard.press('Space')
            await page.locator('#close-image').click()
            assert await page.evaluate('galleryBulk.selected.size')==1
            await page.evaluate('galleryBulk.reset()')
            await tile('e.png').click()
            await page.set_viewport_size(dict(width=390,height=844))
            await expect(page.locator('html')).to_have_attribute('data-presentation','mobile')
            before=await caption.text_content()
            await page.keyboard.press('ArrowRight')
            await expect(caption).to_have_text(before)
            assert not await image.get_attribute('aria-keyshortcuts')
            assert await page.evaluate('JSON.stringify({draft,preset:preset.id,selectedJob,randomSeed})')==draft
            assert not errors and not prompts and not stub.submissions,(errors,prompts)
            await browser.close()
    finally:
        await http.close(); await service.stop(); await upstream.close()
    print(f'{engine}: Desktop viewer navigation, Space accumulation, modal context menu, confirmed single/bulk Delete, typing/Phone guards and drafts passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
