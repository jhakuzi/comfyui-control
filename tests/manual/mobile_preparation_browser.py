"""Cold-start indication, seed defaults/reuse and repeated requests; protocol fixtures only."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from test_mobile_integration import ComfyStub
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings


async def main():
    root=Path(tempfile.mkdtemp(prefix='mobile-preparation-'))
    output=root/'output'; output.mkdir()
    png=(Path(__file__).resolve().parents[2]/'comfyui_control/assets/comfyui-control.png').read_bytes()
    (output/'result.png').write_bytes(png)
    fixed=18446744073709551600
    graph={'text':{'class_type':'Text','inputs':{'text':'A mountain'}},
           'sampler':{'class_type':'Sampler','inputs':{'seed':fixed,'steps':8}}}
    stub=ComfyStub(graph)
    upstream=TestServer(stub.app()); await upstream.start_server()
    service=MobileService(root/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),output)
    preset=service.presets.create('Cold start',graph)
    preset=service.presets.map(preset['id'],[
        {'node':'text','input':'text','role':'positive','key':'prompt'},
        {'node':'sampler','input':'seed','role':'seed','key':'seed'}])
    await service.start()
    runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
    url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors=[]
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(url)
        await page.locator('#preset').select_option(preset['id'])
        await expect(page.locator('#random-seed')).to_be_checked()
        await expect(page.locator('[data-role="seed"]')).to_be_disabled()
        # Older saved drafts adopt the new default without losing unsent edits.
        legacy={'revision':revision(preset),'values':{'prompt':'Keep this unsent edit','seed':str(fixed)},'randomSeed':False}
        await page.add_init_script('if (!sessionStorage.getItem("seed-default-migration-check")) {'
            'localStorage.setItem('+json.dumps('comfy-mobile-draft-'+preset['id'])+','+json.dumps(json.dumps(legacy))+');'
            'sessionStorage.setItem("seed-default-migration-check","done");}')
        await page.reload()
        await expect(page.locator('#random-seed')).to_be_checked()
        await expect(page.locator('[data-role="positive"]')).to_have_value('Keep this unsent edit')

        async def submit(expected):
            await page.locator('#generate').click()
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            assert len(stub.submissions)==expected
            assert await page.locator('#progress').evaluate('(el)=>el.matches(":indeterminate")')
            job=list(service.jobs.values())[-1]
            stub.running,stub.pending=stub.pending,[]
            await stub.emit('execution_start',{'prompt_id':job['prompt_id']})
            await stub.emit('executing',{'prompt_id':job['prompt_id'],'node':'model'})
            await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
            await expect(page.locator('#generation-dock #progress')).to_be_visible()
            await expect(page.locator('#generate')).to_be_disabled()
            return job

        async def complete(job):
            stub.history[job['prompt_id']]={'prompt':stub.running[0],'status':{'status_str':'success'},
                'outputs':{'save':{'images':[{'filename':'result.png','subfolder':'','type':'output'}]}}}
            stub.running=[]
            await stub.emit('execution_success',{'prompt_id':job['prompt_id']})
            await expect(page.locator('#job-title')).to_have_text('Your image is ready')
            await expect(page.locator('#generate')).to_be_enabled()
            await expect(page.locator('#job-images img')).to_be_visible()
            await expect(page.locator('#progress')).to_be_hidden()

        first=await submit(1)
        await page.reload()
        await expect(page.locator('#job-title')).to_have_text('Preparing / loading models…')
        await expect(page.locator('#generation-dock #progress')).to_be_visible()
        assert await page.locator('#progress').evaluate('(el)=>el.matches(":indeterminate")')
        await page.screenshot(path=str(root/'preparing.png'))
        await stub.emit('progress',{'prompt_id':first['prompt_id'],'value':2,'max':8})
        await expect(page.locator('#job-title')).to_have_text('Creating your image')
        await expect(page.locator('#progress')).to_have_js_property('value',2)
        await stub.emit('executing',{'prompt_id':first['prompt_id'],'node':'decode'})
        await expect(page.locator('#job-title')).to_have_text('Processing workflow…')
        assert await page.locator('#progress').evaluate('(el)=>el.matches(":indeterminate")')
        await complete(first)
        second=await submit(2)
        assert first['values']['seed']!=second['values']['seed']
        assert first['prompt_id']!=second['prompt_id']
        await complete(second)
        # Same seed is still explicit and persists, including across refreshes.
        await page.locator('#same-seed').click()
        await expect(page.locator('#random-seed')).not_to_be_checked()
        await expect(page.locator('[data-role="seed"]')).to_have_value(str(second['values']['seed']))
        await page.reload()
        await expect(page.locator('#random-seed')).not_to_be_checked()
        await page.locator('#settings-card').evaluate('(el)=>el.open=true')
        await page.locator('[data-role="seed"]').fill(str(fixed))
        fixed_job=await submit(3)
        assert fixed_job['values']['seed']==fixed
        await complete(fixed_job)
        # A fully cached execution can finish without any sampling progress.
        cached=await submit(4)
        await stub.emit('execution_cached',{'prompt_id':cached['prompt_id'],'nodes':['text','sampler']})
        assert cached['values']['seed']==fixed
        await complete(cached)
        await page.locator('#variation').click()
        await expect(page.locator('#random-seed')).to_be_checked()
        assert not errors,errors
        assert service.presets.get(preset['id'])['graph']==graph
        await browser.close()
        print('PASS: cold-start/reconnection indicator, sampling/next-stage transition, fresh random default, legacy draft migration, consecutive jobs, fixed 64-bit seed/cache completion, and Same seed/variation. No real inference.')
        print('Screenshot:',root/'preparing.png')
    finally:
        await service.stop(); await runner.cleanup(); await upstream.close()


asyncio.run(main())
