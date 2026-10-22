"""Compare main and the feature backend without loading staged UI components.

Use an exported main tree as --baseline-root. A separate isolated page checks
that the staged Generate animation preserves button geometry and main's palette.
Protocol fixtures only; no GPU, real NAS, or physical devices are exercised.
"""
import argparse
import asyncio
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


async def serve(source, output):
    sys.path[:0] = [str(source), str(source / 'tests')]
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from PySide6.QtGui import QImage
    from comfyui_control.mobile.server import MobileHTTP
    from comfyui_control.mobile.service import MobileService
    from comfyui_control.mobile.settings import MobileSettings
    from test_mobile_integration import ComfyStub, until
    output.mkdir(parents=True)
    folder = output / 'images'
    folder.mkdir()
    for index in range(3):
        image = QImage(96, 128, QImage.Format.Format_RGB32)
        image.fill(0xff446688 + index * 16)
        assert image.save(str(folder / f'example-{index}.png'))
    graph = {'text':dict(class_type='Prompt',inputs=dict(text='Baseline prompt')),
             'sample':dict(class_type='Sampler',inputs=dict(steps=20,seed=42))}
    stub = ComfyStub(graph)
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(output / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), folder)
    preset = service.presets.create('Existing main workflow', graph)
    service.presets.map(preset['id'], [dict(node='text',input='text',role='positive',key='p'),
                                      dict(node='sample',input='steps',role='steps',key='steps')])
    await service.start()
    await until(lambda: service.online)
    app = MobileHTTP(service).app()
    async def running(request):
        owner = hashlib.sha256(request.cookies['mobile_client'].encode()).hexdigest()
        stub.running = [[0, 'fixture-prompt', graph, {}, []]]
        service.jobs['fixture-job'] = dict(id='fixture-job',owner=owner,status='running',phase='sampling',
            preset_name='Existing main workflow',prompt_id='fixture-prompt',images=[],created=1,
            progress=dict(value=8,max=20),seconds_per_iteration=1.2)
        service.broadcast()
        return web.json_response({'ok':True})
    app.router.add_post('/__fixture__/running', running)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    print(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/', flush=True)
    try:
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()


def same_pixels(first, second):
    from PySide6.QtGui import QImage
    left, right = QImage(str(first)), QImage(str(second))
    assert left.size() == right.size(), (first, left.size(), right.size())
    if left == right:
        return
    # One-channel rounding permits compositor antialiasing, never layout shifts.
    left = left.convertToFormat(QImage.Format.Format_RGBA8888)
    right = right.convertToFormat(QImage.Format.Format_RGBA8888)
    different = sum(abs(a-b)>1 for a,b in zip(bytes(left.constBits()),bytes(right.constBits())))
    assert not different, (first, second, different)


async def main(engine, output, baseline):
    from playwright.async_api import async_playwright, expect
    output.mkdir(parents=True)
    children, pages, contexts, errors = [], [], [], []
    try:
        urls = []
        for name, source in [('baseline',baseline), ('ported',ROOT)]:
            child = await asyncio.create_subprocess_exec(sys.executable, __file__, '--serve', '--source', str(source),
                '--output',str(output / name), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            children.append(child)
            urls.append((await asyncio.wait_for(child.stdout.readline(),20)).decode().strip())
            assert urls[-1].startswith('http://'), urls[-1]
        async with async_playwright() as playwright:
            browser = await getattr(playwright,engine).launch()
            for url in urls:
                context = await browser.new_context(service_workers='block',reduced_motion='reduce',viewport=dict(width=1440,height=900))
                contexts.append(context)
                page = await context.new_page()
                pages.append(page)
                page.on('pageerror',lambda error:errors.append(str(error)))
                await page.goto(url)
                await expect(page.locator('[data-role="positive"]')).to_be_visible()
                await page.locator('[data-role="positive"]').fill('Unsent main draft')
                await expect(page.locator('#connection')).to_have_text('ComfyUI online')
                assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#e7f67b'
                assert not await page.evaluate('Object.keys(window).some(key => key.startsWith("ComfyGenerate") || key.startsWith("ComfySavedImage") || key.startsWith("ComfyImageFeature"))')
            sizes = [(390,844),(430,932),(768,1024),(1024,1366),(1280,800),(1440,900),(1920,1080),(2560,1440),(844,390)]
            for state in ('create','gallery','running'):
                for index,page in enumerate(pages):
                    if state == 'gallery':
                        await page.locator('#gallery-tab').click()
                        await expect(page.locator('#gallery-grid > button')).to_have_count(3)
                    elif state == 'running':
                        await page.locator('#create-tab').click()
                        response = await page.request.post(urls[index]+'__fixture__/running',data={},
                            headers={'Origin':urls[index].rstrip('/'),'Content-Type':'application/json'})
                        assert response.ok
                        await expect(page.locator('#job-title')).to_have_text('Creating your image')
                for width,height in sizes:
                    screenshots=[]
                    for index,page in enumerate(pages):
                        await page.set_viewport_size(dict(width=width,height=height))
                        await page.evaluate('window.scrollTo(0,0)')
                        await expect(page.locator('[data-role="positive"]')).to_have_value('Unsent main draft')
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        # Let main's existing ResizeObservers finish dock placement.
                        await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                        target=output/f'{state}-{width}x{height}-{index}.png'
                        await page.screenshot(path=str(target),full_page=True,animations='disabled')
                        screenshots.append(target)
                    same_pixels(*screenshots)
            # The animation is activated only on this independent fixture page.
            fixture=await contexts[1].new_page()
            await fixture.set_content('<div class="generate-bar" style="width:300px;position:static"><button class="primary" id="generate"><span data-generate-label>✦ Generate</span></button></div>')
            await fixture.add_style_tag(content=(ROOT/'comfyui_control/mobile/web/style.css').read_text())
            await fixture.add_style_tag(content=(ROOT/'comfyui_control/mobile/web/feature_generate.css').read_text())
            await fixture.add_script_tag(content=(ROOT/'comfyui_control/mobile/web/feature_generate.js').read_text())
            await fixture.evaluate('window.feedback = new ComfyGenerateFeedback()')
            original=await fixture.locator('#generate').bounding_box()
            for state in ['queued','running','complete','failed','cancelled']:
                await fixture.evaluate('''status => {
                  const view=feedback.update({jobs:[{id:'one',status,progress:status==='running'?{value:8,max:20}:null}]});
                  ComfyGenerateFeedback.paint(document.querySelector('#generate'),document.querySelector('[data-generate-label]'),view);
                }''',state)
                assert await fixture.locator('#generate').bounding_box() == original
            assert await fixture.locator('#generate').evaluate('el=>getComputedStyle(el,"::before").animationName') == 'none'
            assert not errors,errors
            await browser.close()
    finally:
        for child in children:
            if child.returncode is None:
                child.stdin.write(b'\n')
                await child.stdin.drain()
                await asyncio.wait_for(child.wait(),10)
    print(f'{engine}: main pixels/layout/navigation match in create/gallery/running at nine sizes; staged animation geometry and reduced motion passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-root',type=Path)
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    asyncio.run(serve(args.source,args.output) if args.serve else main(args.browser,args.output,args.baseline_root))
