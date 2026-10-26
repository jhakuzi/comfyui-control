"""Actual stale-preview cause: a new file reuses a purged output filename."""
import argparse
import asyncio
import os
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings, save_json
from test_mobile_integration import ComfyStub, until


async def check(browser, engine, output, width, height, network):
    output.mkdir(parents=True)
    images = output / 'images'
    images.mkdir()
    def picture(name, colour):
        image = QImage(64,96,QImage.Format.Format_RGB32)
        image.fill(colour)
        assert image.save(str(images/name))
    picture('reused.png',0xff446688)
    picture('last.png',0xff228833)
    graph={'text':dict(class_type='Prompt',inputs={'text':'fixture'})}
    stub=ComfyStub(graph)
    stub.saved['Preview.json']=graph
    upstream=TestServer(stub.app())
    await upstream.start_server()
    service=MobileService(output/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),images,network_output=network)
    preset=service.presets.create('Preview',graph)
    preset=service.presets.map(preset['id'],[dict(key='text',node='text',input='text',role='positive')])
    preset['comfy_source']='Preview.json'
    save_json(service.presets.path(preset['id']),preset)
    mobile=TestServer(MobileHTTP(service).app())
    context=await browser.new_context(viewport=dict(width=width,height=height),service_workers='block')
    page=await context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        await service.start()
        await until(lambda:service.online)
        await mobile.start_server()
        await page.goto(str(mobile.make_url('/')))
        async def generate(name):
            count=len(stub.submissions)
            await expect(page.locator('#generate')).to_be_enabled()
            await page.locator('#generate').click()
            await until(lambda:len(stub.submissions)==count+1)
            job=list(service.jobs.values())[-1]
            entry=stub.pending.pop()
            stub.history[job['prompt_id']]=dict(prompt=entry,status=dict(status_str='success'),outputs={'save':{'images':[dict(filename=name,subfolder='',type='output')]}})
            await service.refresh()
            await expect(page.locator('#job-images img')).to_have_attribute('alt',name)
            await expect(page.locator('#generate')).to_be_enabled()
            return job
        first=await generate('reused.png')
        owner=first['owner']
        old=next(i for i in await service.gallery(owner) if i['filename']=='reused.png')
        result=await service.image_action(old['id'],owner,dict(action='trash',confirm=True,modified=old['modified']))
        await service.delete_permanently(owner,dict(confirm=True,tokens=[result['trash']['token']]))
        await generate('last.png')
        await page.locator('[data-role="positive"]').fill('Preserve my unsent edits')
        # Return a new pixel image at the same path as the purged first job.
        picture('reused.png',0xffdd8822)
        stamp=int(old['modified'])+100000000
        os.utime(images/'reused.png',ns=(stamp,stamp))
        await page.evaluate('window.dispatchEvent(new PageTransitionEvent("pagehide",{persisted:true}))')
        await page.evaluate('window.dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}))')
        newest=await generate('reused.png')
        async def orange_preview():
            await page.wait_for_function('''() => {
                const i=document.querySelector('#job-images img');
                return i?.complete && i.naturalWidth>0;
            }''')
            pixel=await page.locator('#job-images img').evaluate('''i=>{
                const c=document.createElement('canvas');c.width=c.height=1;
                const x=c.getContext('2d');x.drawImage(i,0,0,1,1);
                return Array.from(x.getImageData(0,0,1,1).data);
            }''')
            assert pixel[0]>190 and 100<pixel[1]<170 and pixel[2]<70,pixel
        await orange_preview()
        assert newest['images'][0]['modified']==str(stamp)
        assert service.public_job(first)['images']==[]
        await page.reload()
        await expect(page.locator('#job-images img')).to_have_attribute('alt','reused.png')
        await orange_preview()
        await page.locator('#gallery-tab').click()
        await expect(page.locator('#gallery-grid button')).to_have_count(2)
        await page.locator('#create-tab').click()
        await orange_preview()
        await expect(page.locator('[data-role="positive"]')).to_have_value('Preserve my unsent edits')
        assert len(stub.submissions)==3 and not errors,errors
        await page.screenshot(path=str(output/'new-result-after-reload.png'))
    finally:
        await context.close()
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine} {width}: new pixels at purged filename reach Preview before Gallery and survive reload; old tombstone/drafts remain intact')


async def main(engine,output):
    async with async_playwright() as pw:
        browser=await getattr(pw,engine).launch()
        try:
            await check(browser,engine,output/'desktop',1440,1000,True)
            await check(browser,engine,output/'phone',390,844,False)
        finally: await browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=['firefox','chromium','webkit'],default='firefox')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
