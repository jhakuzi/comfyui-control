"""Desktop/Phone Batch Count UI and exact submitted one-image workflows."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QImage
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.settings import save_json
from test_batch_count import setup
from test_mobile_integration import until


async def check(browser, engine, output, width, height):
    output.mkdir(parents=True)
    service, stub, upstream, graph, _ = await setup(output)
    service.output_dir.mkdir()
    stub.saved['Batch fixture.json'] = graph
    preset = service.presets.get(service.presets.list()[0]['id'])
    preset['comfy_source'] = 'Batch fixture.json'
    save_json(service.presets.path(preset['id']), preset)
    mobile = TestServer(MobileHTTP(service).app())
    await mobile.start_server()
    context = await browser.new_context(viewport=dict(width=width, height=height), service_workers='block')
    page = await context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        await page.goto(str(mobile.make_url('/')))
        await expect(page.locator('#generate')).to_be_enabled()
        await page.locator('#settings-card').evaluate('el => el.open = true')
        count = page.get_by_label('Batch Count', exact=True)
        await expect(count).to_have_attribute('max', '20')
        await count.fill('3')
        await page.locator('[data-role="positive"]').fill('Three separate runs')
        await page.locator('#generate').click()
        await until(lambda: len(stub.submissions) == 3)
        await expect(page.locator('#job-detail')).to_contain_text('Run 1 of 3')
        await expect(page.locator('#generate')).to_be_disabled()
        assert all(s['prompt']['latent']['inputs']['batch_size'] == 1 for s in stub.submissions)
        assert len({s['prompt']['sampler']['inputs']['seed'] for s in stub.submissions}) == 3
        # Advance the real queue/history fixture one independent run at a time.
        for index in range(3):
            entry = stub.pending.pop(0)
            stub.running = [entry]
            await service.refresh()
            await stub.emit('progress', dict(prompt_id=entry[1], value=1, max=2))
            await expect(page.locator('#job-detail')).to_contain_text(f'Run {index + 1} of 3')
            await expect(page).to_have_title('50% · comfyui-control Mobile')
            name = f'run-{index + 1}.png'
            image = QImage(64, 96, QImage.Format.Format_RGB32)
            image.fill(0xff446688 + index * 32)
            assert image.save(str(service.output_dir / name))
            stub.history[entry[1]] = dict(prompt=entry, outputs={'save': {'images': [dict(filename=name, subfolder='', type='output')]}}, status=dict(status_str='success'))
            stub.running = []
            await service.refresh()
        await expect(page.locator('#job-images img')).to_have_attribute('alt', 'run-3.png')
        await expect(page.locator('#generate')).to_be_enabled()
        await expect(page).to_have_title('comfyui-control Mobile')
        await expect(count).to_have_value('3')
        await page.reload()
        await expect(page.locator('#generate')).to_be_enabled()
        await page.locator('#settings-card').evaluate('el => el.open = true')
        await expect(page.get_by_label('Batch Count', exact=True)).to_have_value('3')
        await page.get_by_label('Batch Count', exact=True).fill('2')
        await page.locator('#random-seed').uncheck()
        await page.locator('[data-role="seed"]').fill('18446744073709551600')
        await page.locator('#generate').click()
        await until(lambda: len(stub.submissions) == 5)
        assert [s['prompt']['sampler']['inputs']['seed'] for s in stub.submissions[-2:]] == [18446744073709551600] * 2
        assert all(s['prompt']['latent']['inputs']['batch_size'] == 1 for s in stub.submissions[-2:])
        await expect(page.locator('#cancel')).to_be_visible()
        page.once('dialog', lambda dialog: dialog.accept())
        await page.locator('#cancel').click()
        await expect(page.locator('#generate')).to_be_enabled()
        assert not stub.pending and not stub.interrupts
        assert len(stub.submissions) == 5 and not errors, errors
        await page.screenshot(path=str(output / 'batch-count.png'))
    finally:
        await context.close()
        await mobile.close()
        await service.stop()
        await upstream.close()
    print(f'{engine} {width}: Batch Count queues individual one-image workflows, random/fixed seeds, run progression/results, draft reload and group cancellation passed')


async def main(engine, output):
    async with async_playwright() as pw:
        browser = await getattr(pw, engine).launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                await check(browser, engine, output / str(width), width, height)
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output))
