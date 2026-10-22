"""Desktop-only integration with actual shared APIs and protocol fixtures; no GPU."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_workflows import IMAGE_WORKFLOWS, ImageWorkflowStub, picture
from test_mobile_integration import until


async def main(engine, output):
    output.mkdir(parents=True)
    images = output / 'images'
    picture(images / 'first.png', 0xffaa7733)
    picture(images / 'second.png', 0xff446688)
    originals = {file.name:file.read_bytes() for file in sorted(images.iterdir())}
    stub = ImageWorkflowStub()
    graph = {'text':dict(class_type='Prompt',inputs={'text':'Saved prompt'}),
             'sampler':dict(class_type='Sampler',inputs={'seed':18446744073709551600,'steps':20,'cfg':5.5})}
    stub.object_info.update({node['class_type']:{'input':{}} for node in graph.values()})
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),images)
    preset = service.presets.create('Main workflow',graph)
    preset = service.presets.map(preset['id'],[dict(node=node,input=field,role=role,key=role,label=role.title())
        for node,field,role in [('text','text','positive'),('sampler','seed','seed'),('sampler','steps','steps'),('sampler','cfg','cfg')]])
    await service.start()
    await until(lambda:service.online)
    runner = web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner,'127.0.0.1',0)
    await site.start()
    errors, calls = [], []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright,engine).launch()
            context = await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
            page = await context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:calls.append((request.method,request.url,request.post_data)))
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
            prompt = page.locator('[data-role="positive"]')
            await expect(prompt).to_have_value('Saved prompt')
            await page.locator('#settings-card').evaluate('el=>el.open=true')
            await page.locator('#random-seed').uncheck()
            await page.locator('#generate').click()
            await until(lambda:len(stub.submissions)==1)
            job = list(service.jobs.values())[-1]
            stub.history[job['prompt_id']] = dict(prompt=stub.pending[0],outputs={'save':{'images':[
                dict(filename=name,subfolder='',type='output') for name in originals]}},status=dict(status_str='success',messages=[]))
            stub.pending=[]
            await service.refresh()
            actions = page.locator('#selected-image-actions')
            heart = actions.locator('[data-action="keep"]')
            edit = actions.locator('[data-action="edit"]')
            upscale = actions.locator('[data-action="upscale"]')
            delete = actions.locator('[data-action="trash"]')
            await expect(edit).to_be_enabled()
            await expect(page.locator('#same-seed')).to_have_text('Reuse settings')
            await prompt.fill('An unsent draft')
            await page.locator('[data-role="steps"]').fill('33')
            saved_form = await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')
            for width in (1280,1440,1920,2560):
                await page.set_viewport_size({'width':width,'height':1000})
                boxes=[await button.bounding_box() for button in (heart,edit,upscale,delete)]
                assert len({box['y'] for box in boxes})==1,boxes
                assert max(box['width'] for box in boxes)-min(box['width'] for box in boxes)<1
                reuse,vary=[await page.locator('#'+name).bounding_box() for name in ('same-seed','variation')]
                assert reuse['y']==vary['y'] and reuse['y']>=boxes[0]['y']+boxes[0]['height']
                assert abs(reuse['width']-vary['width'])<1
                await page.screenshot(path=str(output/f'preview-{width}.png'))
            await page.set_viewport_size({'width':1440,'height':1000})
            native_styles = '''el=>Object.fromEntries(['backgroundColor','fontFamily','fontSize','borderRadius','padding','minHeight'].map(key=>[key,getComputedStyle(el)[key]]))'''
            assert await edit.evaluate(native_styles)==await page.locator('#variation').evaluate(native_styles)
            await heart.click()
            await expect(heart).to_have_attribute('aria-pressed','true')
            await page.reload()
            await expect(heart).to_have_attribute('aria-pressed','true')
            await expect(prompt).to_have_value('An unsent draft')
            first,second = [item['id'] for item in job['images']]
            await page.locator('#job-images > button').nth(1).click()
            await expect(page.locator('#image-caption')).to_have_text('second.png')
            await expect(heart).to_have_attribute('aria-pressed','false')
            await heart.click()
            await expect(heart).to_have_attribute('aria-pressed','true')
            await page.locator('#previous-image').click()
            await expect(page.locator('#image-caption')).to_have_text('first.png')
            await expect(heart).to_have_attribute('aria-pressed','true')
            # A delayed favourite response must never paint its old selection.
            release,started = asyncio.Event(),asyncio.Event()
            async def delay(route):
                if route.request.method=='POST':
                    started.set()
                    await release.wait()
                await route.continue_()
            await page.route(f'**/api/images/{first}/actions',delay)
            await heart.click()
            await asyncio.wait_for(started.wait(),5)
            await expect(edit).to_be_disabled()
            await page.locator('#next-image').click()
            await expect(page.locator('#image-caption')).to_have_text('second.png')
            release.set()
            await expect(edit).to_be_enabled()
            await expect(heart).to_have_attribute('aria-pressed','true')
            await page.unroute(f'**/api/images/{first}/actions',delay)
            # Dialog cancellation preserves every generation setting and job.
            saved_form = await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')
            for action,button in [('edit',edit),('upscale',upscale)]:
                await button.click()
                await expect(page.locator(f'#{action}-image-source')).to_have_text('second.png')
                await page.locator(f'#cancel-{action}-image').click()
                await expect(button).to_be_enabled()
                assert await page.evaluate('JSON.stringify({draft,preset:preset.id,randomSeed,selectedJob})')==saved_form
                assert len(stub.submissions)==1
            # Reuse in Preview restores the whole record, including an exact seed.
            await page.locator('#close-image').click()
            reuse_release,reuse_started=asyncio.Event(),asyncio.Event()
            async def delay_reuse(route):
                reuse_started.set()
                await reuse_release.wait()
                await route.continue_()
            await page.route(f'**/api/presets/{preset["id"]}',delay_reuse)
            await page.locator('#same-seed').click()
            await asyncio.wait_for(reuse_started.wait(),5)
            await page.locator('#job-images > button').nth(0).click()
            reuse_release.set()
            await expect(edit).to_be_enabled()
            await expect(prompt).to_have_value('An unsent draft')
            await page.unroute(f'**/api/presets/{preset["id"]}',delay_reuse)
            await page.locator('#close-image').click()
            await page.locator('#same-seed').click()
            await expect(prompt).to_have_value('Saved prompt')
            await expect(page.locator('[data-role="steps"]')).to_have_value('20')
            await page.locator('#settings-card').evaluate('el=>el.open=true')
            await expect(page.locator('[data-role="seed"]')).to_have_value('18446744073709551600')
            await expect(page.locator('#random-seed')).not_to_be_checked()
            assert len(stub.submissions)==1
            async def original():
                await page.evaluate('''async id=>{selectedJob=id;applyState(await api('/api/state'));}''',job['id'])
                await expect(edit).to_be_enabled()
                await prompt.fill('Keep this generation draft')
                await page.locator('#job-images > button').nth(1).click()
            # Actual shared edit/upscale submissions target the second image.
            for action,button in [('edit',edit),('upscale',upscale)]:
                await original()
                await button.click()
                if action=='edit':
                    await page.locator('#edit-image-prompt').fill('Golden light')
                else:
                    await page.locator('#upscale-image-multiplier').fill('1.5')
                await page.locator(f'#{action}-image-form button[type="submit"]').click()
                await expect(page.locator(f'#{action}-image-dialog')).to_be_hidden()
                await until(lambda:len(stub.uploads)==(1 if action=='edit' else 2))
                await expect(page.locator('#image-dialog')).to_be_hidden()
                await expect(prompt).to_have_value('Keep this generation draft')
                assert QImage.fromData(stub.uploads[-1]['pixels']).pixelColor(0,0)==QImage(str(images/'second.png')).pixelColor(0,0)
                graph_sent=stub.submissions[-1]['prompt']
                if action=='edit': assert graph_sent['89']['inputs']['prompt']=='Golden light'
                else: assert graph_sent['custom']['inputs']['scale_multiplier']==1.5
            assert len(stub.submissions)==3
            # Missing saved workflows remain disabled with the backend's reason.
            await original()
            name=IMAGE_WORKFLOWS['upscale']['name']+'.json'
            saved_workflow=stub.saved.pop(name)
            service.workflow_names_time=0
            await page.evaluate('syncSelectedImageActions(true)')
            await expect(upscale).to_be_disabled()
            await expect(actions.locator('.image-workflow-status')).to_contain_text('not configured')
            assert len(stub.submissions)==3
            stub.saved[name]=saved_workflow
            service.workflow_names_time=0
            await page.evaluate('syncSelectedImageActions(true)')
            await expect(upscale).to_be_enabled()
            await page.locator('#close-image').click()
            # A lost response before submission retains the action's journal;
            # Generate retries the same endpoint and UUID rather than normal T2I.
            for identifier in list(service.jobs):
                if identifier != job['id']: await service.cancel(identifier)
            await original()
            attempted=[]
            async def lose_once(route):
                if route.request.method=='POST':
                    attempted.append(route.request.post_data_json)
                    if len(attempted)==1:
                        await route.abort('failed')
                        return
                await route.continue_()
            await page.route(f'**/api/images/{second}/actions',lose_once)
            await edit.click()
            await page.locator('#edit-image-prompt').fill('Retry this instruction once')
            await page.locator('#edit-image-form button[type="submit"]').click()
            await expect(actions.locator('.image-action-status')).to_contain_text('Connection lost')
            pending=await page.evaluate('readStore("pending",null)')
            assert pending['action']['image_id']==second
            await page.locator('#close-image').click()
            await expect(page.locator('#generate-label')).to_have_text('Retry submission')
            await page.locator('#generate').click()
            await until(lambda:len(stub.submissions)==4)
            assert attempted[0]==attempted[1]
            assert attempted[0]['request_id']==pending['request_id']
            await expect(page.locator('#generate-label')).to_have_text('Queued')
            assert await page.evaluate('readStore("pending",null)') is None
            await page.unroute(f'**/api/images/{second}/actions',lose_once)
            await page.locator('#gallery-tab').click()
            await expect(page.locator('#desktop-image-controls')).to_be_hidden()
            await page.locator('#create-tab').click()
            # HTTP failures retain selection, form and confirmed favourite state.
            await original()
            async def fail(route):
                if route.request.method=='POST':
                    await route.fulfill(status=400,content_type='application/json',body='{"error":"Fixture action denied"}')
                else: await route.continue_()
            await page.route(f'**/api/images/{second}/actions',fail)
            await heart.click()
            await expect(actions.locator('.image-action-status')).to_have_text('Fixture action denied')
            await expect(heart).to_have_attribute('aria-pressed','true')
            await page.unroute(f'**/api/images/{second}/actions',fail)
            # Delete cancellation and confirmation use the existing Wastebin.
            page.once('dialog',lambda dialog:dialog.dismiss())
            await delete.click()
            assert not service.image_library.deleted
            page.once('dialog',lambda dialog:dialog.accept())
            await delete.click()
            await until(lambda:bool(service.image_library.deleted))
            await expect(page.locator('#image-caption')).to_have_text('first.png')
            assert all((images/name).read_bytes()==data for name,data in originals.items())
            # No new phone controls, requests, changed labels or open action forms.
            await edit.click()
            await page.set_viewport_size({'width':390,'height':844})
            await expect(page.locator('#edit-image-dialog')).to_be_hidden()
            await expect(actions).to_be_hidden()
            await expect(page.locator('#same-seed')).to_have_text('Same seed')
            await page.locator('#close-image').click()
            await page.screenshot(path=str(output/'phone-after-desktop.png'))
            before=sum('/actions' in url for _,url,_ in calls)
            await page.reload()
            await expect(page.locator('#same-seed')).to_have_text('Same seed')
            await expect(actions).to_be_hidden()
            assert sum('/actions' in url for _,url,_ in calls)==before
            assert not errors,errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: desktop selection, favourite persistence/races, native two-row layout, dialog cancellation, exact full reuse, real edit/upscale, failures, virtual Delete and Phone isolation passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
