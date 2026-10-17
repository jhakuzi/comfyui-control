"""Optional Chromium/WebKit UX checks with protocol fixtures, not GPU inference."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import tempfile

from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage

sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import suggested_mappings
from test_mobile_integration import ComfyStub, until


async def main(browser_name,root):
    root.mkdir(parents=True,exist_ok=True)
    output=root/'output'; output.mkdir(exist_ok=True)
    graph={
        'p':dict(class_type='CustomText',inputs=dict(text='A forest')),
        'n':dict(class_type='CustomText',inputs=dict(text='noise')),
        'gguf':dict(class_type='CustomGGUF',inputs=dict(gguf_name='flux.gguf')),
        'vae':dict(class_type='CustomVAE',inputs=dict(vae_name='vae.safetensors')),
        'clip':dict(class_type='CustomEncoder',inputs=dict(clip_name='text.gguf')),
        'lora-a':dict(class_type='CustomLoRA',inputs=dict(lora_name='one.safetensors',strength_model=.7,strength_clip=.8)),
        'lora-b':dict(class_type='OtherLoRA',inputs=dict(lora_name='two.safetensors',strength_model=.4)),
        'sample':dict(class_type='Sampler',inputs=dict(positive=['p',0],negative=['n',0],seed=18446744073709551600,
                    steps=20,cfg=3.5,sampler_name='euler',scheduler='simple',width=768,height=1024)),
        'custom':dict(class_type='Upscale',inputs=dict(overlap=64,api_key='do-not-expose-this')),
    }
    stub=ComfyStub(graph)
    info={node['class_type']:{'input':{}} for node in graph.values()}
    info['CustomGGUF']={'output':['MODEL'],'input':{'required':{'gguf_name':[['flux.gguf','other.gguf']]}}}
    stub.object_info=info
    upstream=TestServer(stub.app()); await upstream.start_server()
    settings=MobileSettings(comfy_url=str(upstream.make_url('/')))
    data_dir=Path(tempfile.mkdtemp(prefix='data-',dir=root))
    service=MobileService(data_dir,settings,output)
    preset=service.presets.create('Custom GGUF and two LoRAs',graph)
    mappings=suggested_mappings(graph,info)
    # Preserve a user's existing Advanced mapping while presenting a model selector.
    next(item for item in mappings if item['node']=='gguf')['role']='advanced'
    preset=service.presets.map(preset['id'],mappings)
    original_preset=deepcopy(preset)
    await service.start()
    runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
    port=site._server.sockets[0].getsockname()[1]
    url=f'http://127.0.0.1:{port}/'
    errors=[]
    def image(name,workflow):
        data=QImage(64,96,QImage.Format.Format_RGB32); data.fill(0)
        if workflow: data.setText('prompt',json.dumps(workflow))
        assert data.save(str(output/name))
    async def start_again():
        nonlocal service,runner,site
        await service.stop(); await runner.cleanup()
        service=MobileService(data_dir,settings,output)
        await service.start()
        runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
        await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',port); await site.start()
    try:
      async with async_playwright() as playwright:
        browser=await getattr(playwright,browser_name).launch(headless=True,**({'args':['--no-sandbox']} if browser_name=='chromium' else {}))
        context=await browser.new_context(viewport=dict(width=390,height=844),is_mobile=True,has_touch=True,accept_downloads=True)
        if browser_name=='chromium': await context.grant_permissions(['clipboard-read','clipboard-write'])
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(url)
        await page.locator('[data-role="positive"]').fill('A luminous city at dusk')
        await page.locator('#negative-controls').evaluate('(el)=>el.open=true')
        assert await page.locator('#negative-controls label:not(.visually-hidden)').count()==0
        await expect(page.get_by_role('textbox',name='Negative prompt',exact=True)).to_be_visible()
        # Refresh actions follow history and precede the model fields, with real
        # button backgrounds/borders and touch targets instead of link styling.
        for width in (320,390,768):
            await page.set_viewport_size(dict(width=width,height=844))
            history=await page.locator('#prompt-history').bounding_box()
            assert history['height']>=44
            assert await page.locator('#prompt-history').evaluate("el=>getComputedStyle(el).borderTopStyle==='solid' && getComputedStyle(el).backgroundColor!=='rgba(0, 0, 0, 0)'")
            models=await page.locator('#model-controls').bounding_box()
            for action in ('refresh-models','refresh-workflows'):
                box=await page.locator('#'+action).bounding_box()
                assert box and box['y']>=history['y']+history['height']
                assert box['height']>=44 and box['y']+box['height']<=models['y']
                assert await page.locator('#'+action).evaluate("el=>getComputedStyle(el).borderTopStyle==='solid' && getComputedStyle(el).backgroundColor!=='rgba(0, 0, 0, 0)'")
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.set_viewport_size(dict(width=390,height=844))
        await page.screenshot(path=str(root/'prompt-controls.png'))
        await page.locator('[data-role="negative"]').fill('blur, noise')
        await page.locator('[data-role="diffusion_model"]').select_option('other.gguf')
        await page.locator('#lora-card').evaluate('(el)=>el.open=true')
        await page.get_by_role('checkbox',name='one.safetensors',exact=True).uncheck()
        await page.locator('#generate').click()
        await expect(page.locator('#job-title')).to_have_text('In the queue')
        await expect(page.locator('#reuse-last')).to_be_visible()
        assert await page.locator('#reuse-last').evaluate("el=>getComputedStyle(el).borderTopStyle==='solid' && getComputedStyle(el).backgroundColor!=='rgba(0, 0, 0, 0)'")
        assert len(stub.submissions)==1
        await until(lambda:service.monitoring_active)
        service.update_hardware(dict(utilization=72,vram_used=6*2**30))
        await expect(page.locator('#stat-vram')).to_have_text('6.0 GiB')
        await expect(page.locator('#stat-iteration')).to_have_text('--')
        job=list(service.jobs.values())[-1]
        stub.running,stub.pending=stub.pending,[]
        await stub.emit('execution_start',dict(prompt_id=job['prompt_id']))
        await stub.emit('progress',dict(prompt_id=job['prompt_id'],value=1,max=20))
        await until(lambda:(job.get('progress') or {}).get('value')==1)
        await asyncio.sleep(.08)
        await stub.emit('progress',dict(prompt_id=job['prompt_id'],value=2,max=20))
        await expect(page.locator('#stat-iteration')).to_have_text(re.compile(r'\d+\.\d+'))
        for width,height in ((320,568),(390,844),(844,390),(768,1024)):
            await page.set_viewport_size(dict(width=width,height=height))
            await page.evaluate('window.scrollTo(0,10000)')
            stats=await page.locator('#generation-stats').bounding_box()
            assert stats and 0<=stats['y'] and stats['y']+stats['height']<=height
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.set_viewport_size(dict(width=390,height=844))
        await page.screenshot(path=str(root/'statistics.png'))
        await page.locator('[data-role="positive"]').fill('Unsent draft survives')
        await page.evaluate('window.dispatchEvent(new PageTransitionEvent("pagehide",{persisted:true}))')
        await stub.emit('progress',dict(prompt_id=job['prompt_id'],value=3,max=20))
        await page.evaluate('window.dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}))')
        await expect(page.locator('#progress')).to_have_js_property('value',3)
        await expect(page.locator('[data-role="positive"]')).to_have_value('Unsent draft survives')
        await page.locator('#prompt-history').click()
        await expect(page.locator('.prompt-entry')).to_have_count(1)
        await expect(page.locator('.prompt-entry')).to_contain_text('A luminous city at dusk')
        await expect(page.locator('.prompt-entry')).to_contain_text('blur, noise')
        await page.get_by_role('button',name='☆ Favorite',exact=True).click()
        await page.locator('#history-favorites').click()
        await expect(page.locator('.prompt-entry')).to_have_count(1)
        await page.locator('#prompt-history-search').fill('no matching sentence')
        await expect(page.locator('.prompt-entry')).to_have_count(0)
        await page.locator('#prompt-history-search').fill('luminous')
        await expect(page.locator('.prompt-entry')).to_have_count(1)
        await page.screenshot(path=str(root/'history.png'))
        await page.get_by_role('button',name='Reuse prompt',exact=True).click()
        await expect(page.locator('[data-role="positive"]')).to_have_value('A luminous city at dusk')
        await expect(page.locator('[data-role="negative"]')).to_have_value('blur, noise')
        assert len(stub.submissions)==1
        await start_again()
        await page.reload()
        await expect(page.locator('#progress')).to_have_js_property('value',3)
        await page.locator('#prompt-history').click()
        await page.locator('#history-favorites').click()
        await expect(page.locator('.prompt-entry')).to_have_count(1)
        await page.locator('#close-prompt-history').click()
        # Completion while disconnected still restores images and unsent fields.
        await context.set_offline(True)
        image('mobile.png',stub.submissions[0]['prompt'])
        direct=deepcopy(graph); direct['p']['inputs']['text']='Generated in ComfyUI directly'
        image('direct.png',direct); image('plain.png',None)
        originals={p.name:p.read_bytes() for p in output.iterdir()}
        stub.history[job['prompt_id']]=dict(prompt=stub.running[0],status=dict(status_str='success'),
            outputs={'save':{'images':[dict(filename='mobile.png',subfolder='',type='output')]}})
        stub.running=[]
        await stub.emit('execution_success',dict(prompt_id=job['prompt_id']))
        await context.set_offline(False)
        await expect(page.locator('#job-title')).to_have_text('Your image is ready')
        await page.locator('#gallery-tab').click()
        await page.get_by_role('button',name='View mobile.png',exact=True).click()
        await page.locator('#image-details > summary').click()
        await expect(page.locator('#image-metadata')).to_contain_text('A luminous city at dusk')
        await page.get_by_text('Models & LoRAs',exact=True).click()
        await expect(page.locator('#image-metadata')).to_contain_text('other.gguf')
        await expect(page.locator('#image-metadata')).to_contain_text('one.safetensors')
        await expect(page.locator('#image-metadata')).to_contain_text('two.safetensors')
        assert 'do-not-expose-this' not in await page.locator('#image-metadata').text_content()
        await page.locator('#copy-image-prompt').click()
        await expect(page.locator('#copy-prompt-status')).to_have_text('Prompt copied.')
        await page.screenshot(path=str(root/'details.png'))
        await page.locator('#close-image').click()
        await page.get_by_role('button',name='View direct.png',exact=True).click()
        await expect(page.locator('#image-metadata')).to_contain_text('Generated in ComfyUI directly')
        await expect(page.locator('#image-metadata')).to_contain_text('18446744073709551600')
        await page.locator('#close-image').click()
        await page.get_by_role('button',name='View plain.png',exact=True).click()
        await expect(page.locator('#image-metadata')).to_contain_text('No generation metadata')
        for width in (320,390,768):
            await page.set_viewport_size(dict(width=width,height=844))
            assert await page.locator('#image-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        await page.locator('#close-image').click()
        other=await browser.new_context(viewport=dict(width=390,height=844),is_mobile=True,has_touch=True)
        phone=await other.new_page(); await phone.goto(url)
        await phone.locator('#prompt-history').click()
        await expect(phone.locator('.prompt-entry')).to_have_count(0)
        await phone.locator('#close-prompt-history').click()
        await phone.locator('#gallery-tab').click()
        await phone.get_by_role('button',name='View mobile.png',exact=True).click()
        await phone.locator('#image-details > summary').click()
        await expect(phone.locator('#image-metadata')).to_contain_text('unavailable for this browser session')
        assert 'A luminous city at dusk' not in await phone.locator('#image-metadata').text_content()
        await other.close()
        await page.locator('#create-tab').click()
        await page.locator('#prompt-history').click()
        await page.get_by_role('button',name='Delete',exact=True).click()
        await expect(page.locator('.prompt-entry')).to_have_count(0)
        assert service.presets.get(preset['id'])==original_preset
        assert originals=={p.name:p.read_bytes() for p in output.iterdir()}
        assert len(stub.submissions)==1 and not errors,errors
        print(f'PASS {browser_name}: pinned live statistics, prompt search/favorites/reuse/persistence/isolation, lazy PNG/mobile metadata, clipboard, exact seeds, custom GGUF/two LoRAs, recovery and unchanged image files.')
        await browser.close()
    finally:
        await service.stop(); await runner.cleanup(); await upstream.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','webkit'),default='chromium')
    parser.add_argument('--output',type=Path,default=Path(tempfile.mkdtemp(prefix='mobile-extras-')))
    args=parser.parse_args()
    asyncio.run(main(args.browser,args.output))
