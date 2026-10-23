"""Saved-file-only picker and one reused-image snapshot; local protocol fixture."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import suggested_mappings
from test_mobile_integration import ComfyStub, until

async def main(engine, root):
    root.mkdir(parents=True)
    graph = {'text': dict(class_type='Prompt', inputs={'text':'Saved prompt'}),
             'sampler': dict(class_type='Sampler', inputs={'seed':42,'steps':20})}
    stub = ComfyStub(graph)
    stub.saved = {'VeryComfy.json': graph, 'folder/Other.json': graph}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root/'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root/'out')
    old = service.presets.create('Old duplicate',graph)
    old = service.presets.map(old['id'], suggested_mappings(graph))
    for i in range(3): service.presets.create('Old duplicate',graph)
    await service.start()
    await until(lambda: service.online)
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright,engine).launch()
            page = await browser.new_page(viewport=dict(width=1440,height=1000),service_workers='block')
            page.on('pageerror',lambda error: errors.append(str(error)))
            await page.goto(str(mobile.make_url('/')))
            picker = page.locator('#preset')
            await expect(picker.locator('optgroup option')).to_have_count(2)
            assert await picker.locator('option').all_text_contents() == ['Choose a workflow…','VeryComfy','folder/Other']
            await picker.select_option('saved:VeryComfy.json')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Saved prompt')
            await page.locator('[data-role="positive"]').fill('Keep unsent draft')
            await page.evaluate('window.workflowSelector=document.getElementById("preset"); window.savedOptions=[...workflowSelector.options]')
            for _ in range(3): await page.evaluate('loadSavedWorkflows()')
            assert await page.evaluate('savedOptions.every(option=>option.isConnected)')
            await expect(picker).to_have_value('saved:VeryComfy.json')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Keep unsent draft')
            await page.reload()
            await expect(picker).to_have_value('saved:VeryComfy.json')
            await expect(page.locator('[data-role="positive"]')).to_have_value('Keep unsent draft')
            async def reuse(identifier):
                await page.evaluate('''async id => {
                    const description=await api('/api/presets/'+id);
                    await reuseJob({preset:id,revision:description.revision,values:Object.fromEntries(description.fields.map(field=>[field.key,field.default])),disabled_loras:[]});
                }''', identifier)
            await reuse(old['id'])
            await expect(picker.locator('[data-reused-workflow]')).to_have_count(1)
            await expect(picker).to_have_value(old['id'])
            assert await picker.locator('option').first.text_content() == 'Reused image · Old duplicate'
            second = service.presets.create('Different image workflow',graph)
            second = service.presets.map(second['id'],suggested_mappings(graph))
            await reuse(second['id'])
            await expect(picker.locator('[data-reused-workflow]')).to_have_count(1)
            await expect(picker).to_have_value(second['id'])
            await page.reload()
            await expect(picker).to_have_value(second['id'])
            await page.set_viewport_size(dict(width=390,height=844))
            await picker.select_option('saved:folder/Other.json')
            await expect(picker.locator('[data-reused-workflow]')).to_have_count(0)
            await expect(picker).to_have_value('saved:folder/Other.json')
            stub.saved.pop('folder/Other.json')
            await page.evaluate('loadSavedWorkflows()')
            await expect(picker).to_have_value('')
            await expect(page.locator('#prompt-controls textarea')).to_have_count(0)
            assert service.presets.get(old['id'])['name']=='Old duplicate'
            assert not errors,errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: saved files only, no duplicates, stable refresh/draft, one replaced reused-image entry, reload and Phone selection passed')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
