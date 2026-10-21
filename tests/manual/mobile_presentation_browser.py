"""Presentation isolation and live state continuity, with a ComfyUI simulator."""
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
from comfyui_control.mobile.workflows import suggested_mappings
from test_mobile_integration import ComfyStub, until
from test_generation_controls import generation_workflow
from test_resolution_controls import controlaltai_resolution


SIZES = [(390, 844), (430, 932), (768, 1024), (1280, 800), (1440, 900),
         (1920, 1080), (2560, 1440), (1024, 768), (768, 1024), (390, 844)]


async def main(engine, root):
    root.mkdir(parents=True, exist_ok=True)
    graph, info = generation_workflow.__wrapped__(controlaltai_resolution.__wrapped__())
    stub = ComfyStub(graph)
    stub.object_info = info
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root / 'out')
    preset = service.presets.create('Presentation isolation fixture', graph)
    service.presets.map(preset['id'], suggested_mappings(graph, info))
    await service.start()
    await until(lambda: service.online)
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce', service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/')
            await expect(page.locator('#generate')).to_be_enabled()
            await page.locator('[data-role="positive"]').fill('Keep this exact unsent draft through presentation changes')
            if engine == 'webkit':
                await page.locator('#settings-card > summary').evaluate('el => el.click()')
            else:
                await page.locator('#settings-card > summary').click()
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            await page.locator('#random-seed').evaluate('el => el.scrollIntoView({block: "center"})')
            if engine == 'webkit':
                await page.locator('#random-seed').evaluate('el => { if (el.checked) el.click(); }')
            else:
                await page.locator('#random-seed').uncheck()
            await page.locator('[data-role="seed"]').fill('18446744073709551600')
            await page.locator('#batch-count').fill('2')
            await page.evaluate('''() => {
                window.presentationNodes = [...document.querySelectorAll('#generate, #preset, #cancel, #job-metrics, [data-role="positive"], [data-role="seed"]')];
            }''')
            await page.locator('#generate').click(force=engine == 'webkit')
            await until(lambda: len(stub.submissions) == 2)
            stub.running, stub.pending = stub.pending[:1], stub.pending[1:]
            await service.refresh()
            job = list(service.jobs.values())[0]
            await stub.emit('execution_start', {'prompt_id': job['prompt_id']})
            await stub.emit('progress', {'prompt_id': job['prompt_id'], 'value': 3, 'max': 10})

            for width, height in SIZES:
                await page.set_viewport_size({'width': width, 'height': height})
                desktop = height >= 600 and (width >= 1440 or width >= 1024 and width / height >= 4/3)
                await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop' if desktop else 'mobile')
                await expect(page.locator('#generate-label')).to_have_text('Sampling · 30%')
                await expect(page.locator('[data-role="seed"]')).to_have_value('18446744073709551600')
                await expect(page.locator('[data-role="positive"]')).to_have_value('Keep this exact unsent draft through presentation changes')
                proof = await page.evaluate('''() => {
                    const ids = [...document.querySelectorAll('[id]')].map(el => el.id);
                    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
                    const connected = presentationNodes.every(el => el.isConnected && document.getElementById(el.id) === el);
                    const inactive = document.querySelector(`link[href="/presentation_${ComfyPresentation.desktop.matches ? 'mobile' : 'desktop'}.css"]`).sheet;
                    const snapshot = () => JSON.stringify([...document.querySelectorAll('body, body *')]
                        .filter(el => el.getClientRects().length).map(el => {
                            const css = getComputedStyle(el), box = el.getBoundingClientRect();
                            return [el.id, box.x, box.y, box.width, box.height, css.color, css.backgroundColor,
                                css.fontFamily, css.fontSize, css.borderRadius, css.display, css.position];
                        }));
                    const before = snapshot();
                    inactive.disabled = true;
                    const after = snapshot();
                    inactive.disabled = false;
                    return {duplicates, connected, isolated: before === after, overflow: document.documentElement.scrollWidth > innerWidth};
                }''')
                assert not proof['duplicates'] and proof['connected'] and proof['isolated'] and not proof['overflow'], proof
                assert len(stub.submissions) == 2
                assert len(service.jobs) == 2
            # A future desktop-only rearrangement must restore itself on mobile,
            # without adding a corresponding case to the mobile adapter.
            await page.set_viewport_size({'width': 1440, 'height': 900})
            await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop')
            await page.evaluate('ComfyPresentation.place(document.getElementById("settings-card"), document.getElementById("desktop-toolbar"))')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await expect(page.locator('#settings-stack > #settings-card')).to_have_count(1)
            await expect(page.locator('#settings-card')).to_have_js_property('open', True)
            await expect(page.locator('#generate-label')).to_have_text('Sampling · 30%')
            # Existing handlers still work after all the moves.
            await page.locator('#cancel-queue').click(force=engine == 'webkit')
            await expect(page.locator('#cancel-queue')).to_have_attribute('aria-expanded', 'true')
            await page.locator('#cancel-queue').click(force=engine == 'webkit')
            await until(lambda: not stub.pending and len(stub.interrupts) == 1)
            assert stub.interrupts == [{'prompt_id': job['prompt_id']}]
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: scoped sheet isolation, unique/live controls, draft/64-bit seed/job continuity, orientation and automatic restoration, generation and queue cancellation passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
