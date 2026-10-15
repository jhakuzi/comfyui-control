"""Optional manual browser check. Requires Playwright and Chromium. No real model inference."""
import asyncio
import argparse
import tempfile
import json
from pathlib import Path
import sys
import struct
import time
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.settings import MobileSettings, password_hash, lan_address
from test_mobile_integration import ComfyStub

parser = argparse.ArgumentParser(description='Exercise the mobile frontend against a simulated ComfyUI backend, not inference.')
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()
OUT = args.output or Path(tempfile.mkdtemp(prefix='comfy-mobile-browser-'))
OUT.mkdir(parents=True, exist_ok=True)
async def main():
    graph = {
      'text': {'class_type':'CustomPrompt', 'inputs':{'text':'A quiet mountain lake'}},
      'model': {'class_type':'QuantizedModel', 'inputs':{'file':'model.gguf'}},
      'lora1': {'class_type':'LoRA', 'inputs':{'model':['model',0], 'name':'detail.safetensors', 'strength':0.7, 'clip':0.8}},
      'lora2': {'class_type':'OtherLoRA', 'inputs':{'model':['lora1',0], 'strength':0.4}},
      'sampler': {'class_type':'Sampler', 'inputs':{'prompt':['text',0], 'seed':18446744073709551600, 'steps':20, 'cfg':5.5, 'width':768, 'height':1024, 'batch':1}},
    }
    stub = ComfyStub(graph)
    upstream = TestServer(stub.app())
    await upstream.start_server()
    output = OUT/'output'; output.mkdir(exist_ok=True)
    settings = MobileSettings(bind='0.0.0.0', password=password_hash('browser testing password'), comfy_url=str(upstream.make_url('/')))
    service = MobileService(Path(tempfile.mkdtemp(prefix='state-', dir=OUT)), settings, output)
    # Fresh test state each time.
    service.jobs = {}
    preset = service.presets.create('Custom quantized workflow', graph)
    mappings = []
    for node,input_name,role,label in [('text','text','positive','Prompt'),('model','file','model','Model'),('lora1','name','lora_model','LoRA'),('lora1','strength','lora_strength','Model strength'),('lora1','clip','lora_strength','CLIP strength'),('lora2','strength','lora_strength','Second LoRA'),('sampler','seed','seed','Seed'),('sampler','steps','steps','Steps'),('sampler','cfg','cfg','CFG'),('sampler','width','width','Width'),('sampler','height','height','Height'),('sampler','batch','batch','Batch size')]:
        mappings.append({'node':node,'input':input_name,'role':role,'label':label,'key':f'm-{len(mappings)}'})
    preset = service.presets.map(preset['id'], mappings)
    await service.start()
    runner=web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup(); site=web.TCPSite(runner,'0.0.0.0',0); await site.start()
    settings.port=site._server.sockets[0].getsockname()[1]
    url=f'http://127.0.0.1:{settings.port}/'
    errors=[]
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True,accept_downloads=True)
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        response = await page.goto(url)
        assert response.status == 200

        await page.locator('#password').fill('browser testing password')
        await page.get_by_role('button',name='Connect',exact=True).click()
        await page.locator('#workspace').wait_for(state='visible')
        await page.locator('#preset').select_option(preset['id'])
        await page.locator('textarea').first.wait_for()
        await page.locator('textarea').first.fill('A luminous library in the mountains')
        await page.screenshot(path=str(OUT/'mobile-create.png'),full_page=True)
        for width in (320,375,390,430,768,1200):
          await page.set_viewport_size({'width':width,'height':900})
          assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('window.isSecureContext'), 'Browser treats loopback as a secure context'
        await page.locator('#generate').click()
        await page.wait_for_function("document.querySelector('#job-title').textContent === 'In the queue'")
        assert len(stub.submissions)==1
        assert stub.submissions[0]['prompt']['sampler']['inputs']['seed']==18446744073709551600
        # Click cannot accidentally submit twice while the request is active.
        assert await page.locator('#generate').is_disabled()
        stub.running,stub.pending=stub.pending,[]
        job=list(service.jobs.values())[-1]
        await stub.emit('execution_start',{'prompt_id':job['prompt_id']})
        await stub.emit('progress',{'prompt_id':job['prompt_id'],'value':4,'max':20})
        png=(REPO/'comfyui_control/assets/comfyui-control.png').read_bytes()
        for ws in stub.sockets: await ws.send_bytes(struct.pack('>II',1,2)+png)
        await page.locator('#preview').wait_for(state='visible')
        await page.screenshot(path=str(OUT/'mobile-progress.png'),full_page=True)
        (output/'generated.png').write_bytes(png)
        stub.history[job['prompt_id']]={'prompt':stub.running[0],'status':{'status_str':'success'},'outputs':{'upscaler':{'images':[{'filename':'generated.png','subfolder':'','type':'output'}]}}}
        stub.running=[]
        await stub.emit('execution_success',{'prompt_id':job['prompt_id']})
        await page.locator('#job-images img').wait_for()
        await page.reload()
        await page.locator('#job-images img').wait_for()
        await page.locator('#gallery-tab').click()
        await page.locator('#gallery-grid img').wait_for()
        await page.locator('#gallery-grid button').first.click()
        async with page.expect_download() as info: await page.locator('#download-image').click()
        download=await info.value
        assert download.suggested_filename=='generated.png'
        await page.locator('#reuse-image').click()
        await page.locator('textarea').first.wait_for()
        assert await page.locator('textarea').first.input_value()=='A luminous library in the mountains'
        await page.locator('#advanced').evaluate('(el)=>el.open=true')
        await page.locator('#mapping').evaluate('(el)=>el.open=true')
        await page.screenshot(path=str(OUT/'mobile-mapping.png'),full_page=True)
        assert not errors,errors
        print(json.dumps({'browser':'Chromium','viewport_widths':[320,375,390,430,768,1200],'connection':'loopback HTTP, not a physical LAN/VPN test','generation':'protocol test double','large_seed':'preserved exactly','queue_preview_completion_restore_gallery_download_reuse':'passed','javascript_errors':errors}))
        await browser.close()
    finally:
      await service.stop(); await runner.cleanup(); await upstream.close()
asyncio.run(main())
print('Screenshots and test state:', OUT)
