"""Gallery comparison checks against local image fixtures, not GPU generation."""
import asyncio
import argparse
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


async def main(browser_name):
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
        browser=await getattr(p,browser_name).launch(headless=True,**({'args':['--no-sandbox']} if browser_name=='chromium' else {}))
        # Match ordinary LAN HTTP (no service worker), and let Playwright control
        # individual downloads/offline transitions in both browser engines.
        context=await browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block')
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def requested(request):
            parsed=urlsplit(request.url)
            if re.fullmatch(r'/api/images/[a-f0-9]{32}',parsed.path) and "thumbnail=" not in parsed.query and "download=" not in parsed.query: full_requests.append(parsed.path)
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
        b_id=await page.get_by_role('button',name='View B.png',exact=True).get_attribute('data-image-id')
        release_b=asyncio.Event()
        async def slow_b(route):
            await release_b.wait()
            await route.continue_()
        await page.route('**/api/images/'+b_id+'?*',slow_b)
        await page.evaluate('window.scrollTo(0,500)')
        scroll=await page.evaluate('window.scrollY')
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-dialog')).to_be_visible()
        await expect(page.locator('#compare-loading')).to_have_text('Loading images · 1/2 ready…')
        await expect(page.locator('#compare-viewport')).to_be_hidden()
        await expect(page.locator('#compare-slider')).to_be_disabled()
        release_b.set()
        await expect(page.locator('#compare-viewport')).to_be_visible()
        await expect(page.locator('#compare-slider')).to_be_enabled()
        await page.unroute('**/api/images/'+b_id+'?*',slow_b)
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
        if browser_name=='chromium':
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
        # Desktop WebKit has zero notch insets. Supply explicit safe-area values
        # to exercise the same CSS used by iPhone Safari/home-screen mode.
        for width,height,top,right,bottom,left,font in (
                (390,844,59,0,34,0,16), (320,568,20,0,0,0,16),
                (844,390,0,59,21,59,16), (390,600,59,0,34,0,16),
                (390,844,59,0,34,0,24), (1200,844,0,0,0,0,16)):
            await page.set_viewport_size({'width':width,'height':height})
            await page.evaluate('size=>document.documentElement.style.fontSize=size+"px"',font)
            await page.evaluate('insets=>{for(const [side,value] of Object.entries(insets)) document.documentElement.style.setProperty("--safe-area-"+side,value+"px")}',dict(top=top,right=right,bottom=bottom,left=left))
            for position in ('top','bottom'):
                await page.locator('#compare-dialog').evaluate('(el,position)=>el.scrollTop=position==="top"?0:el.scrollHeight',position)
                bounds=await page.locator('#close-compare').bounding_box()
                assert bounds and bounds['y']>=top and bounds['y']+bounds['height']<=height-bottom,(browser_name,width,height,position,bounds)
                assert bounds['x']>=left and bounds['x']+bounds['width']<=width-right
                assert bounds['height']>=44 and bounds['width']>=44
                center=dict(x=bounds['x']+bounds['width']/2,y=bounds['y']+bounds['height']/2)
                assert await page.evaluate('point=>!!document.elementFromPoint(point.x,point.y)?.closest("#close-compare")',center)
            assert await page.locator('#compare-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            if (width,height,font)==(390,844,16):
                await page.screenshot(path=str(root/'comparison-safe-area-scrolled.png'))
                await page.locator('#compare-dialog').evaluate('(el)=>el.scrollTop=0')
                await page.screenshot(path=str(root/'comparison-safe-area.png'))
        await page.evaluate('()=>document.documentElement.style.removeProperty("font-size")')
        # Close from the scrolled position, then reopen without losing the pair.
        await page.set_viewport_size({'width':390,'height':844})
        await page.locator('#close-compare').click()
        await page.wait_for_function('(position)=>Math.abs(window.scrollY-position)<3',arg=scroll)
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-viewport')).to_be_visible()
        assert await page.locator('#compare-dialog').evaluate('(el)=>el.scrollTop')==0
        assert len(full_requests)==2
        await page.evaluate('()=>{for(const side of ["top","right","bottom","left"]) document.documentElement.style.removeProperty("--safe-area-"+side)}')
        await page.set_viewport_size({'width':390,'height':844})
        await page.screenshot(path=str(root/'comparison.png'))
        await page.locator('#close-compare').click()
        await page.wait_for_function('(position)=>Math.abs(window.scrollY-position)<3',arg=scroll)
        assert abs(await page.evaluate('window.scrollY')-scroll)<3,(scroll,await page.evaluate('window.scrollY'),await page.evaluate('comparison.scroll'))
        assert await page.locator('#gallery-grid [aria-pressed="true"]').count()==2
        # Reopen and swap entirely offline: no full-image or metadata downloads.
        count=len(full_requests)
        await context.set_offline(True)
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-viewport')).to_be_visible()
        await expect(page.locator('#compare-slider')).to_be_enabled()
        await page.locator('#swap-compare').click()
        await page.wait_for_function('document.querySelector("#compare-a").naturalWidth===64 && document.querySelector("#compare-b").naturalWidth===128')
        assert len(full_requests)==count
        await page.locator('#close-compare').click()
        await context.set_offline(False)
        # Keep B cached, replace A with C0, interrupt its download, and retry.
        await page.get_by_role('button',name='View A.png',exact=True).click()
        await page.get_by_role('button',name='View C0.png',exact=True).click()
        c_id=await page.get_by_role('button',name='View C0.png',exact=True).get_attribute('data-image-id')
        attempts=0
        async def interrupted(route):
            nonlocal attempts
            attempts+=1
            if attempts==1: await route.abort('failed')
            else: await route.continue_()
        await page.route('**/api/images/'+c_id+'?*',interrupted)
        await page.locator('#compare-images').click()
        await expect(page.locator('#retry-compare')).to_be_visible()
        await expect(page.locator('#compare-loading')).to_contain_text('1/2 images ready')
        await expect(page.locator('#compare-viewport')).to_be_hidden()
        await page.locator('#retry-compare').click()
        await expect(page.locator('#compare-viewport')).to_be_visible()
        assert attempts==2 and full_requests.count('/api/images/'+b_id)==1
        assert await page.evaluate('comparison.images.size')==2
        await page.locator('#close-compare').click()
        await page.unroute('**/api/images/'+c_id+'?*',interrupted)
        # A newly selected missing image reports an error, with cached B kept.
        evicted=await page.evaluate('(id)=>comparison.images.get(id).url',c_id)
        await page.get_by_role('button',name='View C0.png',exact=True).click()
        assert await page.evaluate('(url)=>fetch(url).then(()=>false,()=>true)',evicted)
        await page.get_by_role('button',name='View C1.png',exact=True).click()
        await page.route('**/api/images/*',lambda route:route.fulfill(status=404,body='Unavailable') if '/parameters' not in route.request.url and 'thumbnail=' not in urlsplit(route.request.url).query else route.continue_())
        await page.locator('#compare-images').click()
        await expect(page.locator('#compare-error')).to_be_visible()
        await page.locator('#close-compare').click()
        cached=await page.evaluate('[...comparison.images.values()][0].url')
        await page.evaluate('showLogin()')
        assert await page.evaluate('comparison.images.size')==0
        assert await page.evaluate('(url)=>fetch(url).then(()=>false,()=>true)',cached)
        assert {p.name:p.read_bytes() for p in output.iterdir()}==originals
        assert not errors,errors
        print(f'PASS {browser_name}: safe-area Close at top/after scroll, rotation/viewport resize/large text, reopen resets dialog scroll, two-image readiness, offline cache/swap, interrupted-download retry, eviction/auth clearing, divider, metadata, missing images, preserved gallery/files.')
        print('Screenshot:',root/'comparison.png')
        await browser.close()
    finally:
        await service.stop(); await runner.cleanup(); await upstream.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','webkit'),default='chromium')
    asyncio.run(main(parser.parse_args().browser))
