"""Five persistent optional LoRAs using real shared import/submission APIs; no GPU."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until
from test_mobile_workflow_sources import configurable_loras, flux_saved


async def main(engine, root):
    root.mkdir(parents=True)
    editor, info = configurable_loras.__wrapped__(flux_saved.__wrapped__())
    for field in ('strength_model', 'strength_clip'):
        info['AdapterLoader']['input']['required'][field] = ['FLOAT', dict(min=-100, max=100, step=.05)]
    stub = ComfyStub({})
    stub.object_info = info
    stub.saved = {'Five optional LoRAs.json': editor}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root/'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root/'out')
    await service.start()
    await until(lambda: service.online)
    await service.import_saved_workflow('Five optional LoRAs.json')
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()
            context = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(str(mobile.make_url('/')))
            await expect(page.locator('#generate')).to_be_enabled()
            await page.locator('#lora-card').evaluate('el => el.open = true')
            toggles = page.locator('#lora-controls > .lora-group > .check-label input')
            await expect(toggles).to_have_count(5)
            for i in range(5): await expect(toggles.nth(i)).not_to_be_checked()
            sliders = page.locator('#lora-controls input[type="range"]')
            strengths = page.locator('#lora-controls input[data-role="lora_strength"]')
            for slider in await sliders.all():
                await expect(slider).to_have_attribute('min', '-2')
                await expect(slider).to_have_attribute('max', '2')
            await expect(strengths.first).to_have_attribute('min', '-100')
            await expect(strengths.first).to_have_attribute('max', '100')
            for value in ('-2', '0', '2'):
                await sliders.first.fill(value)
                await expect(strengths.first).to_have_value(value)
            await strengths.first.fill('0.7')
            await expect(sliders.first).to_have_value('0.7')
            groups = page.locator('#lora-controls > .lora-group')
            assert (await groups.first.bounding_box())['height'] < 180
            labels = page.locator('#lora-controls .control > label')
            assert await labels.first.evaluate('el => getComputedStyle(el).clipPath') == 'inset(50%)'
            for section_id in ('lora-card', 'settings-card', 'resolution-card', 'advanced'):
                await page.locator('#' + section_id).evaluate('el => el.open=true')
                marker = await page.locator('#' + section_id + ' > summary').evaluate('el => getComputedStyle(el, "::before").transform')
                assert marker == 'matrix(0, -1, 1, 0, 0, 0)', (section_id, marker)
                if section_id != 'lora-card':
                    await page.locator('#' + section_id).evaluate('el => el.open=false')
            await page.screenshot(path=str(root / 'compact-loras-desktop.png'))
            await toggles.nth(2).check()
            await page.reload()
            await expect(toggles.nth(2)).to_be_checked()
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 1)
            graph = stub.submissions[-1]['prompt']
            assert [key for key in graph if key.startswith('lora-')] == ['lora-2']
            assert graph['lora-2']['inputs']['strength_model'] == .7
            assert graph['sampler']['inputs']['model'] == ['lora-2', 0]
            await until(lambda: list(service.jobs.values())[-1]['status'] == 'queued')
            await service.cancel(list(service.jobs)[-1])
            await expect(page.locator('#generate')).to_be_enabled()
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(page.locator('.desktop-section-content')).to_have_count(0)
            await expect(sliders.first).to_have_attribute('min', '-100')
            await expect(sliders.first).to_have_attribute('max', '2')
            await expect(strengths.first).to_have_value('0.7')
            await page.set_viewport_size(dict(width=1440, height=1000))
            await expect(sliders.first).to_have_attribute('min', '-2')
            await expect(sliders.first).to_have_value('0.7')
            await page.set_viewport_size(dict(width=390, height=844))
            await expect(sliders.first).to_have_attribute('min', '-100')
            assert await labels.first.evaluate('el => getComputedStyle(el).clipPath') == 'none'
            assert (await groups.first.bounding_box())['height'] > 180
            await toggles.nth(2).uncheck()
            for i in range(5): await expect(toggles.nth(i)).not_to_be_checked()
            await page.locator('#generate').click()
            await until(lambda: len(stub.submissions) == 2)
            graph = stub.submissions[-1]['prompt']
            assert not any(key.startswith('lora-') for key in graph)
            assert graph['sampler']['inputs']['model'] == ['diff', 0]
            await until(lambda: list(service.jobs.values())[-1]['status'] == 'queued')
            await service.cancel(list(service.jobs)[-1])
            await expect(page.locator('#generate')).to_be_enabled()
            await toggles.nth(2).check()
            strength = page.locator('#lora-controls [data-role="lora_strength"]').nth(4)
            await expect(strength).to_have_value('0.7')
            assert not errors, errors
            await browser.close()
    finally:
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine}: five bypassed LoRAs visible/unchecked; activation, saved draft/reload, true bypass submission and restored strengths on Desktop/Phone passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
