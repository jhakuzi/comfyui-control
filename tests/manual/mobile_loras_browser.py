"""LoRA picker UX in Chromium/WebKit using ComfyUI protocol fixtures, not inference."""
import argparse
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until
from test_mobile_loras import workflow, mapped


async def main(browser_name, root):
    root.mkdir(parents=True, exist_ok=True)
    stub = ComfyStub(workflow())
    stub.loras = ['portraits/one.safetensors', 'landscapes/new.safetensors']
    stub.object_info = {node['class_type']: {'input': {}} for node in workflow().values()}
    stub.object_info['CustomLoRA']['input'] = {'required': {'file': ['STRING']}}
    stub.object_info['ComboLoRA']['input'] = {'required': {'lora_name': [['two.safetensors', 'None']]}}
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(root/'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), root/'out')
    preset = mapped(service)
    original = deepcopy(preset)
    mobile = TestServer(MobileHTTP(service).app())
    errors = []
    try:
        await service.start()
        await until(lambda: service.online)
        await mobile.start_server()
        async with async_playwright() as playwright:
            browser = await getattr(playwright, browser_name).launch(headless=True,
                **({'args': ['--no-sandbox']} if browser_name == 'chromium' else {}))
            context = await browser.new_context(viewport=dict(width=390, height=844), is_mobile=True, has_touch=True)
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(str(mobile.make_url('/')))
            await page.locator('#lora-card').evaluate('el => el.open = true')
            first = page.locator('#control-first-name')
            second = page.locator('#control-second-name')
            await expect(first).to_have_value('portraits/one.safetensors')
            assert await first.evaluate('el => el.tagName') == 'SELECT'
            assert await second.evaluate('el => el.tagName') == 'SELECT'
            for width, height in ((390, 844), (1440, 900)):
                await page.set_viewport_size(dict(width=width, height=height))
                await first.select_option('landscapes/new.safetensors')
                await second.select_option('None')
                await expect(first).to_have_value('landscapes/new.safetensors')
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.locator('#control-first-strength').fill('0.65')
            await page.reload()
            await page.locator('#lora-card').evaluate('el => el.open = true')
            await expect(first).to_have_value('landscapes/new.safetensors')
            await expect(second).to_have_value('None')
            await expect(page.locator('#control-first-strength')).to_have_value('0.65')
            stub.loras.append('newly-installed.safetensors')
            await page.locator('#refresh-models').click()
            await expect(first.locator('option[value="newly-installed.safetensors"]')).to_have_count(1)
            await expect(first).to_have_value('landscapes/new.safetensors')
            # A removed file stays visible, rather than silently selecting the first LoRA.
            stub.loras.remove('landscapes/new.safetensors')
            await page.locator('#refresh-models').click()
            await expect(first.locator('option:checked')).to_have_text('landscapes/new.safetensors · unavailable')
            await expect(first).to_have_value('landscapes/new.safetensors')
            # Empty and unsupported catalogues do not destroy drafts or native combos.
            stub.loras = []
            await page.locator('#refresh-models').click()
            await expect(first).to_be_disabled()
            await expect(page.get_by_text('No installed LoRAs found.', exact=False)).to_be_visible()
            await expect(second).to_be_enabled()
            stub.loras = None
            await page.locator('#refresh-models').click()
            await expect(page.get_by_text('LoRA choices are unavailable.', exact=False)).to_be_visible()
            await expect(first).to_have_value('landscapes/new.safetensors')
            stub.loras = ['portraits/one.safetensors', 'landscapes/new.safetensors']
            await page.locator('#refresh-models').click()
            await expect(first).to_be_enabled()
            await expect(first).to_have_value('landscapes/new.safetensors')
            await page.locator('#lora-card').evaluate('el => el.open = true')
            await page.set_viewport_size(dict(width=390, height=844))
            await first.scroll_into_view_if_needed()
            assert (await first.bounding_box())['width'] > 250
            await page.screenshot(path=str(root/'lora-picker.png'))
            await page.locator('#generate').click()
            await expect(page.locator('#job-title')).to_have_text('In the queue')
            assert len(stub.submissions) == 1
            expected = workflow()
            expected['first']['inputs'].update(file='landscapes/new.safetensors', strength_model=.65)
            expected['second']['inputs']['lora_name'] = 'None'
            assert stub.submissions[0]['prompt'] == expected
            assert service.presets.get(preset['id']) == original
            assert not errors, errors
            print(f'PASS {browser_name}: phone/laptop LoRA dropdowns, native choices, catalogue fallback, refresh, deleted/empty/unavailable lists, draft recovery, strengths and exact submitted graph.')
            await browser.close()
    finally:
        await service.stop()
        await mobile.close()
        await upstream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    parser.add_argument('--output', type=Path, default=Path(tempfile.mkdtemp(prefix='lora-picker-')))
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
