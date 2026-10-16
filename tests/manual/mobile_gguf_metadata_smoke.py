"""Check the mobile GGUF selector against a real plugin; never queue or load a model."""
import argparse
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import aiohttp
from aiohttp import web
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.client import ComfyClient
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import render


async def check(url, loader):
    async with aiohttp.ClientSession() as session:
        info = await ComfyClient(session, url).request('GET', '/object_info')
    schema = info[loader]['input']['required']
    model_input = 'gguf_name' if 'gguf_name' in schema else 'unet_name'
    choices = schema[model_input][0]
    assert len(choices) >= 2, 'This check needs two GGUF filenames visible to the loader.'
    inputs = {}
    for name, definition in schema.items():
        if isinstance(definition[0], list):
            inputs[name] = definition[0][0]
        else:
            inputs[name] = definition[1]['default']
    graph = {'loader': {'class_type': loader, 'inputs': inputs}}
    original = deepcopy(graph)
    with tempfile.TemporaryDirectory(prefix='mobile-real-gguf-') as temporary:
        service = MobileService(Path(temporary), MobileSettings(comfy_url=url), Path(temporary)/'out')
        preset = service.presets.create('Real GGUF loader', graph)
        service.presets.map(preset['id'], [{'node':'loader','input':model_input,'role':'advanced','key':'gguf-model'}])
        service.settings.default_preset = preset['id']
        await service.start()
        runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
                page = await browser.new_page(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
                await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
                select = page.get_by_label('Diffusion model', exact=True)
                await expect(select).to_be_visible()
                assert await select.locator('option').all_text_contents() == choices
                await select.select_option(choices[1])
                await page.reload()
                await expect(page.get_by_label('Diffusion model', exact=True)).to_have_value(choices[1])
                draft = await page.evaluate('(id) => JSON.parse(localStorage.getItem("comfy-mobile-draft-" + id))', preset['id'])
                changed, _ = render(service.presets.get(preset['id']), draft['values'], info=info)
                assert changed['loader']['inputs'][model_input] == choices[1]
                assert service.presets.get(preset['id'])['graph'] == original
                await browser.close()
            print(f'PASS: real {loader} metadata supplies {len(choices)} choices; mobile selector, reload and rendered model value verified.')
            print('Metadata/UI check only: no prompt was queued and no GGUF model was loaded.')
        finally:
            await service.stop()
            await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-url', default='http://127.0.0.1:8188')
    parser.add_argument('--loader', default='UnetLoaderGGUF', choices=['UnetLoaderGGUF','UnetLoaderGGUFAdvanced','LoaderGGUF','LoaderGGUFAdvanced'])
    args = parser.parse_args()
    asyncio.run(check(args.comfy_url, args.loader))
