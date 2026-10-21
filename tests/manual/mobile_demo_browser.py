"""Browser checks of the shipped demo entrypoint; no desktop setup or inference."""
import argparse
import asyncio
import os
from pathlib import Path
import signal
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from playwright.async_api import async_playwright, expect
from test_headless import Running, unused_port, wait


async def main(engine, output):
    output.mkdir(parents=True, exist_ok=True)
    port = unused_port()
    runner = Running([sys.executable, '-m', 'comfyui_control.cli', '--demo-webui', '--demo-port', str(port)],
                     {**os.environ, 'XDG_CONFIG_HOME': str(output / 'unused-settings')})
    try:
        await asyncio.to_thread(wait, lambda: 'Demo WebUI:' in runner.text or runner.process.poll() is not None)
        assert runner.process.poll() is None, runner.text
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch(headless=True,
                **({'args': ['--no-sandbox']} if engine == 'chromium' else {}))
            page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{port}/')
            await expect(page.locator('#demo-notice')).to_be_visible()
            await expect(page.locator('#generate')).to_be_enabled()
            await page.locator('[data-role="positive"]').fill('Demo draft retained after refresh')
            for width, height in ((1440, 1000), (1024, 768), (390, 844), (320, 568)):
                await page.set_viewport_size({'width': width, 'height': height})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.locator('#lora-card').evaluate('element => element.open = true')
            await expect(page.locator('[data-role="lora_model"]')).to_have_value('sample-detail.safetensors')
            await page.locator('[data-role="lora_model"]').select_option('sample-style.safetensors')
            await page.reload()
            await expect(page.locator('[data-role="positive"]')).to_have_value('Demo draft retained after refresh')
            await expect(page.locator('[data-role="lora_model"]')).to_have_value('sample-style.safetensors')
            await page.locator('#generate').click()
            await expect(page.locator('#job-title')).to_have_text('Your image is ready', timeout=15000)
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await expect(page.locator('#selected-image-name')).to_contain_text('demo-')
            await page.locator('#selected-image-actions [data-action="keep"]').click()
            await page.wait_for_function('''() => {
                const images = [...document.querySelectorAll('#gallery-grid img')];
                return images.length >= 6 && images.slice(0, 6).every(image => image.complete && image.naturalWidth > 0);
            }''')
            await page.screenshot(path=str(output / 'desktop.png'), full_page=True)
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.screenshot(path=str(output / 'phone.png'), full_page=True)
            assert not errors, errors
            await browser.close()
        assert not (output / 'unused-settings').exists(), 'Demo touched the saved-settings directory'
    finally:
        assert await asyncio.to_thread(runner.stop, signal.SIGINT) == 0, runner.text
    print(f'{engine}: demo startup, responsive layout, LoRA/draft refresh, simulated result and Keep passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
