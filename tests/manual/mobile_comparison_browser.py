"""Gallery comparison checks against local image fixtures, not GPU generation."""
import asyncio
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage, QColor
from test_mobile_integration import ComfyStub
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.server import MobileHTTP


async def main():
    root=Path(tempfile.mkdtemp(prefix='mobile-comparison-'))
    output=root/'output'; output.mkdir()
    def image(name,width,height,steps,seed,color):
        graph={'model':{'class_type':'Loader','inputs':{'unet_name':'flux.gguf'}},
               'sample':{'class_type':'Sampler','inputs':{'sampler_name':'euler','steps':steps,'cfg':3.5,'seed':seed,'width':width,'height':height}},
               'text':{'class_type':'Text','inputs':{'text':'private prompt'}}}
        result=QImage(width,height,QImage.Format.Format_RGB32)
        result.fill(QColor(color))
        result.setText('prompt',json.dumps(graph))
        assert result.save(str(output/name))
        return graph
    graph=image('A.png',64,128,20,123,'#a04060')
    image('B.png',128,64,30,456,'#40a0b0')
    for i in range(10): image(f'C{i}.png',64,64,20,i,'#607040')
    originals={p.name:p.read_bytes() for p in output.iterdir()}
    stub=ComfyStub(graph)
    upstream=TestServer(stub.app()); await upstream.start_server()
    service=MobileService(root/'data',MobileSettings(comfy_url=str(upstream.make_url('/'))),output)
    await service.start()
    runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
    url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors=[]; full_requests=[]
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def requested(request):
            parsed=urlsplit(request.url)
            if re.fullmatch(r'/api/images/[a-f0-9]{32}',parsed.path) and not parsed.query: full_requests.append(parsed.path)
        page.on('request',requested)
        await page.goto(url)
        await page.locator('#gallery-tab').click()
        await page.get_by_role('button',name='View A.png',exact=True).wait_for()
        assert not full_requests
        await page.locator('#select-compare').click()
        await page.get_by_role('button',name='View A.png',exact=True).click()
        assert await page.locator('#compare-images').is_disabled()
        await page.get_by_role('button',name='View B.png',exact=True).click()
        await expect(page.locator('#compare-images')).to_be_enabled()
        await page.get_by_role('button',name='View C0.png',exact=True).click()
        await expect(page.locator('#compare-images')).to_have_text('Compare · 2/2')
        await page.evaluate('window.scrollTo(0,500)')
        scroll=await page.evaluate('window.scrollY')
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-dialog')).to_be_visible()
        await expect(page.locator('#compare-slider')).to_have_value('50')
        await page.wait_for_function('document.querySelector("#compare-a").naturalWidth===64 && document.querySelector("#compare-b").naturalWidth===128')
        assert len(full_requests)==2
        await expect(page.locator('#compare-parameters')).to_contain_text('Steps')
        await expect(page.locator('#compare-parameters tr.parameter-difference')).not_to_have_count(0)
        assert 'private prompt' not in await page.locator('#compare-parameters').inner_text()
        await page.locator('#compare-slider').focus()
        await page.keyboard.press('ArrowRight')
        await expect(page.locator('#compare-slider')).to_have_value('51')
        await page.keyboard.press('Home')
        await expect(page.locator('#compare-slider')).to_have_value('0')
        await page.locator('#reset-compare').click()
        await expect(page.locator('#compare-slider')).to_have_value('50')
        box=await page.locator('#compare-viewport').bounding_box()
        await page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
        await page.mouse.down()
        await page.mouse.move(box['x']+box['width']*.8,box['y']+box['height']*.5,steps=5)
        await page.mouse.up()
        assert int(await page.locator('#compare-slider').input_value())>=79
        cdp=await context.new_cdp_session(page)
        def touch(fraction): return [{'x':box['x']+box['width']*fraction,'y':box['y']+box['height']*.5}]
        await cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':touch(.2)})
        await cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':touch(.7)})
        await cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        assert int(await page.locator('#compare-slider').input_value())>=69
        before=await page.locator('#compare-a').get_attribute('src')
        await page.locator('#swap-compare').click()
        assert await page.locator('#compare-b').get_attribute('src')==before
        for width in (320,390,768,1200):
            await page.set_viewport_size({'width':width,'height':844})
            assert await page.locator('#compare-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        await page.set_viewport_size({'width':390,'height':844})
        await page.screenshot(path=str(root/'comparison.png'))
        await page.locator('#close-compare').click()
        await page.wait_for_function('(position)=>Math.abs(window.scrollY-position)<3',arg=scroll)
        assert abs(await page.evaluate('window.scrollY')-scroll)<3,(scroll,await page.evaluate('window.scrollY'),await page.evaluate('comparison.scroll'))
        assert await page.locator('#gallery-grid [aria-pressed="true"]').count()==2
        await page.route('**/api/images/*',lambda route:route.fulfill(status=404,body='Unavailable') if '/parameters' not in route.request.url and not urlsplit(route.request.url).query else route.continue_())
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-error')).to_be_visible()
        await page.locator('#close-compare').click()
        assert {p.name:p.read_bytes() for p in output.iterdir()}==originals
        assert not errors,errors
        print('PASS: exactly-two selection, lazy full images, mouse/touch/keyboard divider, swap/reset, metadata differences, aspect ratios, missing images, and preserved gallery state.')
        print('Screenshot:',root/'comparison.png')
        await browser.close()
    finally:
        await service.stop(); await runner.cleanup(); await upstream.close()

asyncio.run(main())
