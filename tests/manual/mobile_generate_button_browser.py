"""Theme-preserving Generate animation against real protocol events, without GPU."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until


async def check(browser, engine, url, service, stub, output, viewport):
    width, height = viewport
    output.mkdir(parents=True)
    context = await browser.new_context(viewport=dict(width=width,height=height),service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(10000)
    errors, requests = [], []
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:requests.append((request.method,request.url)))
    original_count = len(stub.submissions)
    try:
        await page.goto(url)
        button,label = page.locator('#generate'),page.locator('#generate-label')
        await expect(button).to_be_enabled()
        await expect(label).to_have_text('✦ Generate')
        prompt = page.locator('[data-role="positive"]')
        await prompt.fill('Keep this draft through progress and reconnect')
        before = await button.bounding_box()
        styles = await button.evaluate('''el => Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight',
            'letterSpacing','padding','borderRadius','borderWidth','boxShadow','minHeight'].map(key=>[key,getComputedStyle(el)[key]]))''')
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#e7f67b'
        assert await button.evaluate('el => getComputedStyle(el).backgroundColor') == 'rgb(231, 246, 123)'
        assert await label.evaluate('el=>getComputedStyle(el).fontSize') == styles['fontSize']
        await expect(page.locator('#selected-image-actions')).to_be_hidden()

        async def geometry():
            box=await button.bounding_box()
            assert abs(box['width']-before['width']) < .1 and abs(box['height']-before['height']) < .1,(before,box)
            assert await button.evaluate('''el => Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight',
                'letterSpacing','padding','borderRadius','borderWidth','boxShadow','minHeight'].map(key=>[key,getComputedStyle(el)[key]]))''') == styles
            await expect(prompt).to_have_value('Keep this draft through progress and reconnect')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        async def start():
            await expect(button).to_be_enabled()
            await button.click(force=engine=='webkit')
            await expect(label).to_have_text('Queued')
            await expect(button).to_have_attribute('data-progress','indeterminate')
            await expect(button).to_be_disabled()
            await geometry()
            # Let the enqueue status refresh finish before manually advancing
            # the fixture queue; an old snapshot must not race the next phase.
            await until(lambda:not service.refresh_task or service.refresh_task.done())
            return list(service.jobs.values())[-1]

        async def run(job):
            stub.running,stub.pending=stub.pending,[]
            await service.refresh()
            await stub.emit('execution_start',dict(prompt_id=job['prompt_id']))
            await stub.emit('executing',dict(prompt_id=job['prompt_id'],node='model'))
            await expect(label).to_have_text('Loading models')
            await expect(button).to_have_attribute('data-progress','indeterminate')
            assert await button.evaluate('el=>getComputedStyle(el,"::before").animationName') == 'generate-wait'
            assert await button.evaluate('el=>Number(getComputedStyle(el,"::before").opacity)') > .2

        async def finish(job,kind):
            message={'success':'execution_success','failed':'execution_error','cancelled':'execution_interrupted'}[kind]
            stub.history[job['prompt_id']]=dict(prompt=stub.running[0],outputs={},status=dict(
                status_str='success' if kind=='success' else 'error',
                messages=[] if kind=='success' else [[message,dict(exception_message='Fixture generation failure')]]))
            stub.running=[]
            await stub.emit(message,dict(prompt_id=job['prompt_id'],exception_message='Fixture generation failure'))

        job=await start()
        await page.screenshot(path=str(output/'queued.png'))
        await run(job)
        await page.screenshot(path=str(output/'loading.png'))
        for value in (40,99,100):
            await stub.emit('progress',dict(prompt_id=job['prompt_id'],value=value,max=100))
            await expect(label).to_have_text(f'Sampling · {value}%')
            await expect(button).to_have_attribute('data-progress','determinate')
            assert float(await button.evaluate('el=>el.style.getPropertyValue("--generation-progress")')) == value/100
            await page.wait_for_function('''expected => {
                const transform=getComputedStyle(document.getElementById('generate'),'::before').transform;
                return transform.startsWith('matrix(') && Math.abs(parseFloat(transform.slice(7))-expected)<.001;
            }''',arg=value/100)
            assert await button.evaluate('el=>getComputedStyle(el,"::before").backgroundColor') == 'rgb(231, 246, 123)'
            assert await button.evaluate('el=>Number(getComputedStyle(el,"::before").opacity)') > .2
            await geometry()
            await page.screenshot(path=str(output/f'sampling-{value}.png'))
        await stub.emit('progress_state',dict(prompt_id=job['prompt_id'],nodes={'sampler':dict(state='running',value=100,max=100)}))
        await expect(label).to_have_text('Sampling · 100%')
        await expect(button).to_have_attribute('data-progress','determinate')
        await stub.emit('executing',dict(prompt_id=job['prompt_id'],node='vae'))
        await expect(label).to_have_text('Processing')
        await expect(button).to_have_attribute('data-progress','indeterminate')
        await page.emulate_media(reduced_motion='reduce')
        assert await button.evaluate('el=>getComputedStyle(el,"::before").animationName') == 'none'
        assert await button.evaluate('el=>getComputedStyle(el,"::before").transitionDuration') == '0s'
        await page.emulate_media(reduced_motion='no-preference')
        await context.set_offline(True)
        await expect(button).to_have_attribute('data-progress','paused')
        await expect(label).to_have_text('Reconnecting')
        assert await button.evaluate('el=>getComputedStyle(el,"::before").animationName') == 'none'
        await geometry()
        await page.screenshot(path=str(output/'reconnect.png'))
        await context.set_offline(False)
        await expect(label).to_have_text('Processing')
        assert len(stub.submissions)==original_count+1
        await finish(job,'success')
        await expect(button).to_have_attribute('data-progress','success')
        await expect(label).to_have_text('✓ Complete')
        await geometry()
        await page.screenshot(path=str(output/'success.png'))
        settled=len(requests)
        await expect(button).to_have_attribute('data-progress','idle')
        assert len(requests)==settled,'Terminal feedback must not issue requests'
        await page.reload()
        await expect(button).to_be_enabled()
        await expect(label).to_have_text('✦ Generate')
        await expect(button).to_have_attribute('data-progress','idle')
        # Reduced motion retains actual fill, without animated interpolation.
        await page.emulate_media(reduced_motion='reduce')
        page.on('dialog',lambda dialog:dialog.accept())
        queued=await start()
        await page.locator('#cancel').click()
        await expect(button).to_have_attribute('data-progress','cancelled')
        await expect(label).to_have_text('Cancelled')
        await geometry()
        await page.screenshot(path=str(output/'cancelled.png'))
        await expect(button).to_have_attribute('data-progress','idle')
        running=await start()
        stub.running,stub.pending=stub.pending,[]
        await service.refresh()
        await stub.emit('progress',dict(prompt_id=running['prompt_id'],value=3,max=10))
        await expect(label).to_have_text('Sampling · 30%')
        assert await button.evaluate('el=>getComputedStyle(el,"::before").transitionDuration') == '0s'
        await page.locator('#cancel').click()
        await expect(label).to_have_text('Stopping')
        await expect(button).to_have_attribute('data-progress','indeterminate')
        await finish(running,'cancelled')
        # Main reports upstream interruptions as failed; presentation must follow
        # that existing mapping rather than changing backend cancellation here.
        await expect(label).to_have_text('Generation failed')
        await expect(button).to_have_attribute('data-progress','failed')
        assert service.jobs[running['id']]['status'] == 'failed'
        await page.screenshot(path=str(output/'running-interrupted.png'))
        await geometry()
        await expect(button).to_have_attribute('data-progress','idle')
        failed=await start()
        stub.running,stub.pending=stub.pending,[]
        await service.refresh()
        await stub.emit('progress',dict(prompt_id=failed['prompt_id'],value=2,max=10))
        await expect(label).to_have_text('Sampling · 20%')
        await finish(failed,'failed')
        await expect(label).to_have_text('Generation failed')
        await expect(button).to_have_attribute('data-progress','failed')
        await geometry()
        await page.screenshot(path=str(output/'failed.png'))
        await expect(button).to_have_attribute('data-progress','idle')
        async def reject(route):
            await route.fulfill(status=400,content_type='application/json',body='{"error":"Fixture invalid generation settings"}')
        await page.route('**/api/generate',reject)
        await button.click(force=engine=='webkit')
        await expect(label).to_have_text('Submission failed')
        await expect(page.locator('#notice')).to_contain_text('Fixture invalid generation settings')
        await expect(button).to_have_attribute('data-progress','idle')
        await page.unroute('**/api/generate',reject)
        # Completion while disconnected must reconcile once, without resubmission.
        offline=await start()
        stub.running,stub.pending=stub.pending,[]
        await service.refresh()
        await stub.emit('progress',dict(prompt_id=offline['prompt_id'],value=2,max=10))
        await expect(label).to_have_text('Sampling · 20%')
        await context.set_offline(True)
        await expect(button).to_have_attribute('data-progress','paused')
        await finish(offline,'success')
        await until(lambda: service.jobs[offline['id']]['status']=='complete')
        await context.set_offline(False)
        await expect(label).to_have_text('✓ Complete')
        await expect(button).to_have_attribute('data-progress','idle')
        assert len(stub.submissions)==original_count+5
        assert not errors,errors
    finally:
        await context.close()


async def main(engine,output):
    output.mkdir(parents=True)
    graph={'text':dict(class_type='Prompt',inputs={'text':'Protocol test'})}
    stub=ComfyStub(graph)
    upstream=TestServer(stub.app())
    await upstream.start_server()
    service=MobileService(output/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),output/'images')
    preset=service.presets.create('Generate fixture',graph)
    service.presets.map(preset['id'],[dict(key='prompt',node='text',input='text',role='positive',label='Prompt')])
    await service.start()
    await until(lambda:service.online)
    runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0)
    await site.start()
    try:
        async with async_playwright() as playwright:
            browser=await getattr(playwright,engine).launch()
            try:
                for viewport in ((1440,900),(390,844)):
                    await check(browser,engine,f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/',
                                service,stub,output/f'{viewport[0]}x{viewport[1]}',viewport)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: desktop/mobile actual fill at 40/99/100%, queue/loading/processing highlight, completion/failure/rejection, queued/running cancellation, reconnect/offline completion, geometry/theme and reduced motion passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
