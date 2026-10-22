"""Virtual Wastebin UI and deletion checks with local protocol fixtures, no NAS/GPU."""
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
from comfyui_control.mobile.workflows import suggested_mappings
from test_image_reuse import image_graph
from test_image_workflows import ImageWorkflowStub
from test_mobile_integration import until


async def check(browser, root, width, height):
    root.mkdir(parents=True)
    output = root / 'output'
    output.mkdir()
    originals = {}
    for name in ('restore.png', 'single.png', 'bulk.png', 'failed.png'):
        image = QImage(48, 64, QImage.Format.Format_RGB32)
        image.fill(0xff456b89)
        assert image.save(str(output / name))
        originals[name] = (output / name).read_bytes()
    stub = ImageWorkflowStub()
    graph = image_graph()
    for node in graph.values():
        stub.object_info.setdefault(node['class_type'], {'input': {}})
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
    preset = service.presets.create('Wastebin fixture', graph)
    service.presets.map(preset['id'], suggested_mappings(graph, stub.object_info))
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    context = await browser.new_context(viewport=dict(width=width, height=height), service_workers='block', reduced_motion='reduce')
    page = await context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
        if width < 1024:
            await page.locator('#gallery-tab').click()
        await expect(page.locator('#gallery-grid > button')).to_have_count(4)
        if width < 1024:
            await page.locator('#create-tab').click()
        await expect(page.locator('#open-wastebin')).to_be_visible()
        assert await page.evaluate("document.querySelector('#cleanup-vram').nextElementSibling.id") == 'open-wastebin'
        async def choose_delete(name):
            if width < 1024:
                await page.locator('#gallery-tab').click()
            await page.locator('#gallery-all').click()
            await page.get_by_role('button', name='View ' + name, exact=True).click()
            actions = page.locator('#selected-image-actions' if width >= 1024 else '#viewer-image-actions')
            button = actions.get_by_role('button', name='Delete', exact=True)
            await expect(button).to_be_enabled()
            page.once('dialog', lambda dialog: dialog.accept())
            await button.click()
            await expect(page.get_by_role('button', name='View ' + name, exact=True)).to_have_count(0)
            assert (output / name).read_bytes() == originals[name]
            if width < 1024:
                await page.locator('#create-tab').click()
            await page.locator('#open-wastebin').click()
        await choose_delete('restore.png')
        row = page.locator('.trash-entry').filter(has_text='restore.png')
        await expect(row).to_be_visible()
        await expect(row.locator('img')).to_be_visible()
        await expect(row.locator('img')).to_have_js_property('naturalWidth', 48)
        await page.reload()
        await expect(page.locator('.trash-entry')).to_have_count(1)
        await page.get_by_role('button', name='Restore', exact=True).click()
        await expect(page.locator('.trash-entry')).to_have_count(0)
        assert (output / 'restore.png').read_bytes() == originals['restore.png']
        await choose_delete('single.png')
        page.once('dialog', lambda dialog: dialog.dismiss())
        await page.get_by_role('button', name='Delete permanently', exact=True).click()
        assert (output / 'single.png').is_file()
        page.once('dialog', lambda dialog: dialog.accept())
        await page.get_by_role('button', name='Delete permanently', exact=True).click()
        await expect(page.locator('.trash-entry')).to_have_count(0)
        assert not (output / 'single.png').exists()
        await choose_delete('bulk.png')
        await choose_delete('failed.png')
        original_io = service.network_io
        async def failure(operation, data, **kwargs):
            if operation == 'delete' and data['image']['filename'] == 'failed.png':
                raise OSError('NFS permission denied (fixture)')
            return await original_io(operation, data, **kwargs)
        service.network_io = failure
        page.once('dialog', lambda dialog: dialog.dismiss())
        await page.locator('#empty-wastebin').click()
        assert (output / 'bulk.png').is_file() and (output / 'failed.png').is_file()
        page.once('dialog', lambda dialog: dialog.accept())
        await page.locator('#empty-wastebin').click()
        await expect(page.locator('.trash-entry')).to_have_count(1)
        await expect(page.locator('.trash-entry')).to_contain_text('permission denied')
        assert not (output / 'bulk.png').exists() and (output / 'failed.png').is_file()
        await page.reload()
        await expect(page.locator('.trash-entry')).to_contain_text('permission denied')
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await expect(page.locator('.trash-entry img')).to_have_js_property('naturalWidth', 48)
        await page.screenshot(path=str(root / 'wastebin-failure.png'), full_page=True)
        service.network_io = original_io
        page.once('dialog', lambda dialog: dialog.accept())
        await page.locator('#empty-wastebin').click()
        await expect(page.locator('.trash-entry')).to_have_count(0)
        assert not (output / 'failed.png').exists()
        assert (output / 'restore.png').read_bytes() == originals['restore.png']
        assert not errors, errors
        assert not stub.submissions
    except BaseException:
        await page.screenshot(path=str(root / 'failure.png'), full_page=True)
        print('page errors:', errors)
        print('page:', (await page.locator('body').inner_text())[:1800])
        raise
    finally:
        await context.close()
        await runner.cleanup()
        await service.stop()
        await upstream.close()


async def main(engine, output):
    async with async_playwright() as playwright:
        browser = await getattr(playwright, engine).launch()
        try:
            for width, height in ((1440, 900), (390, 844)):
                await check(browser, output / f'{width}x{height}', width, height)
        finally:
            await browser.close()
    print(f'{engine}: desktop/mobile virtual Delete, icon, thumbnail/filename, reload, Restore, permanent-delete confirmation, Empty Wastebin and retained failure/retry passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
