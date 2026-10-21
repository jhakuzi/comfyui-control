"""Desktop flow/overflow checks with protocol data; optional mobile visual baseline.

No real inference or physical devices. --baseline-web takes the pre-change web/
directory to check mobile pixels and layout restoration after desktop resizing.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from PySide6.QtGui import QColor, QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.workflows import suggested_mappings
from test_mobile_integration import ComfyStub, until
from test_generation_controls import generation_workflow
from test_resolution_controls import controlaltai_resolution


SIZES = [(1280, 800), (1440, 900), (1512, 982), (1920, 1080), (2560, 1440)]


async def main(engine, root, baseline, desktop_redesign=False):
    root.mkdir(parents=True, exist_ok=True)
    graph, info = generation_workflow.__wrapped__(controlaltai_resolution.__wrapped__())
    graph['negative'] = dict(class_type='Text', inputs={'text': 'Negative prompt'})
    graph['3']['inputs']['negative'] = ['negative', 0]
    for key, input_name, role in [('diffusion', 'unet_name', 'diffusion_model'),
                                   ('vae', 'vae_name', 'vae'), ('encoder', 'clip_name', 'text_encoder')]:
        filename = f'{key}/' + 'long_model_filename_with_quantization_and_revision_' * 5 + '.safetensors'
        graph[key] = dict(class_type=key, inputs={input_name: filename})
        info[key] = {'input': {'required': {input_name: [[filename, 'other.safetensors']]}}}
    # Extra encoder slots force an actual toolbar wrap on laptop widths.
    for name in ['clip_name1', 'clip_name2', 'text_encoder_name']:
        graph['encoder']['inputs'][name] = graph['encoder']['inputs']['clip_name']
        info['encoder']['input']['required'][name] = info['encoder']['input']['required']['clip_name']
    graph['lora'] = dict(class_type='LoraLoader', inputs={'lora_name': 'Layout fixture.safetensors', 'strength_model': .7})
    info['LoraLoader'] = {'input': {'required': {'lora_name': [['Layout fixture.safetensors']], 'strength_model': ['FLOAT']}}}
    stub = ComfyStub(graph)
    stub.object_info = info
    upstream = TestServer(stub.app())
    await upstream.start_server()
    output = root / 'output'
    output.mkdir()
    for name, width, height in [('portrait', 640, 960), ('landscape', 960, 640)]:
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor('#456b89'))
        image.setText('prompt', json.dumps(graph))
        assert image.save(str(output / f'{name}.png'))
    service = MobileService(root / 'data', MobileSettings(comfy_url=str(upstream.make_url('/')), share_image_settings=True), output)
    preset = service.presets.create('A long saved workflow name for responsive layout checks', graph)
    mappings = [field for field in suggested_mappings(graph, info) if field['node'] != 'negative']
    mappings.append(dict(node='negative', input='text', role='negative', key='negative', label='Negative prompt'))
    service.presets.map(preset['id'], mappings)
    await service.start()
    await until(lambda: service.online)
    await service.gallery()
    for item in service.images.values():
        service.image_owners[service.image_ownership_key(item)] = 'other-browser'
    runner = web.AppRunner(MobileHTTP(service).app(), access_log=None, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors, action_posts = [], []
    try:
        async with async_playwright() as playwright:
            browser = await getattr(playwright, engine).launch()

            async def open_page(width, height, old=False):
                context = await browser.new_context(viewport={'width': width, 'height': height}, service_workers='block', reduced_motion='reduce')
                page = await context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: action_posts.append(request.url) if request.method == 'POST' and '/api/images/' in request.url and request.url.endswith('/actions') else None)
                if old:
                    async def assets(route):
                        path = urlsplit(route.request.url).path
                        file = baseline / ('index.html' if path == '/' else path.lstrip('/'))
                        if not path.startswith('/api/') and file.is_file():
                            await route.fulfill(path=file)
                        else:
                            await route.continue_()
                    await page.route('**/*', assets)
                await page.goto(url)
                await expect(page.locator('[data-role="positive"]')).to_be_visible()
                await expect(page.locator('#generate')).to_be_enabled()
                await page.locator('[data-role="positive"]').fill('A populated positive prompt. ' * 40)
                if width >= 1280:
                    await page.locator('[data-role="negative"]').fill('A populated negative prompt. ' * 20)
                await page.evaluate('closeEvents()')
                return context, page

            context, page = await open_page(1280, 800)
            await page.evaluate('window.scrollTo(0, 0)')
            await page.wait_for_function('() => gallery.length === 2')
            images = await page.evaluate('gallery')
            assert len(images) == 2

            reports = {}
            baseline_view = False

            async def check(state_name, image=None):
                await page.evaluate('''({name, image}) => {
                    selectSavedImage(null);
                    selectedJob = null;
                    const active = name === 'running';
                    const job = {id: 'layout-job', prompt_id: 'layout-prompt', created: 1,
                        preset: preset.id, preset_name: preset.name, values: {}, controls: [],
                        status: active ? 'running' : 'complete', phase: 'sampling',
                        progress: active ? {value: 6, max: 20} : null, images: image ? [image] : []};
                    applyState({...state, version: state.version + 1, online: name !== 'offline',
                        jobs: active || image ? [job] : [], preview: null});
                    if (image) selectSavedImage(image);
                    window.scrollTo(0, 0);
                }''', dict(name=state_name, image=image))
                if image:
                    await expect(page.locator('#selected-image-preview')).to_be_visible()
                    await expect(page.locator('#selected-image-preview')).to_have_js_property('complete', True)
                    # Compare settled skins, not different moments of the same
                    # existing 1.4s completion feedback animation.
                    await expect(page.locator('#generate')).to_have_attribute('data-progress', 'idle')
                # Compare neutral component skins, not a pointer left over a
                # differently positioned control by the previous interaction.
                await page.mouse.move(0, 0)
                await page.evaluate('document.activeElement?.blur()')
                report = await page.evaluate('''() => {
                    const rect = id => document.getElementById(id)?.getBoundingClientRect().toJSON();
                    const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
                    const overflow = [...document.querySelectorAll('#workspace button, #workspace input, #workspace select, #workspace textarea')]
                        .filter(visible).filter(el => {const r = el.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1 || r.width < 1;})
                        .map(el => el.id || el.textContent);
                    const loaders = [...document.querySelectorAll('#desktop-toolbar .control, #workflow-picker, #desktop-toolbar .model-tools')]
                        .filter(visible).map(el => el.getBoundingClientRect().toJSON());
                    const overlap = loaders.some((a, i) => loaders.slice(i + 1).some(b =>
                        Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
                        Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1));
                    const panel = document.getElementById('generation-panel');
                    return {overflow, overlap, pageWidth: document.documentElement.scrollWidth, width: innerWidth,
                        panel: rect('generation-panel'), stack: rect('settings-stack'), gallery: rect('gallery-page'),
                        toolbar: rect('desktop-toolbar'), prompts: rect('prompt-controls'), actions: rect('desktop-generate-slot'),
                        panels: ['settings-card', 'resolution-card', 'lora-card'].map(rect), advanced: rect('advanced'),
                        generate: rect('generate'), cancelSlot: rect('desktop-cancel-slot'), preview: rect('preview-stage'),
                        settingsGap: parseFloat(getComputedStyle(document.getElementById('settings-stack')).rowGap),
                        panelOverflow: getComputedStyle(panel).overflowY, panelPosition: getComputedStyle(panel).position};
                }''')
                report['skins'] = await page.evaluate('''() => ['#generate', '#preset', '[data-role="positive"]', '#settings-card', '#generation-panel'].map(selector => {
                    const input = document.querySelector(selector);
                    const css = getComputedStyle(input.closest('.desktop-scroll-frame') || input);
                    return [css.color, css.backgroundColor, css.fontFamily, css.fontSize, css.fontWeight,
                        css.borderRadius, css.borderColor, css.boxShadow];
                })''')
                key = (page.viewport_size['width'], state_name)
                if baseline_view:
                    if desktop_redesign:
                        # Geometry is intentionally new; component skins and the
                        # mobile pixel comparison below must still match exactly.
                        assert reports[key]['skins'] == report['skins'], (key, reports[key]['skins'], report['skins'])
                    else:
                        assert reports[key] == report, (key, reports[key], report)
                else:
                    reports[key] = report
                assert not report['overflow'] and not report['overlap'], report
                if report['pageWidth'] > report['width']:
                    report['wide'] = await page.evaluate('''() => [...document.querySelectorAll('body *')].filter(el => el.getClientRects().length && el.getBoundingClientRect().right > innerWidth + 1).map(el => ({id:el.id, tag:el.tagName, cls:el.className, width:el.getBoundingClientRect().width, right:el.getBoundingClientRect().right, overflow:getComputedStyle(el).overflowX})).slice(0,20)''')
                assert report['pageWidth'] <= report['width'], report
                assert report['panelPosition'] == 'static' and report['panelOverflow'] == 'visible', report
                assert abs(report['panel']['y'] - report['stack']['y']) < 1, report
                assert report['panel']['x'] >= report['stack']['right'] + 12, report
                assert report['gallery']['y'] >= max(report['panel']['bottom'], report['stack']['bottom']), report
                if baseline_view:
                    assert (report['gallery']['y'] >= report['advanced']['bottom']
                            or report['advanced']['y'] >= report['gallery']['bottom']), report
                else:
                    assert report['advanced']['y'] >= report['gallery']['bottom'], report
                assert report['prompts']['y'] >= report['toolbar']['bottom'], report
                assert report['actions']['x'] >= report['prompts']['right'] + 12, report
                for a, b in zip(report['panels'], report['panels'][1:]):
                    assert abs(b['top'] - a['bottom'] - report['settingsGap']) < 1, report
                if not baseline_view:
                    # Bounded controls, both prompts above the settings, and an
                    # unobscured Generate are meaningful redesign requirements.
                    assert report['stack']['width'] <= 680, report
                    assert report['toolbar']['height'] < 240, report
                    assert report['prompts']['height'] <= 120, report
                    assert abs(report['generate']['top'] - report['prompts']['top']) < 1, report
                    assert abs(report['actions']['bottom'] - report['prompts']['bottom']) < 1, report
                    assert report['advanced']['top'] >= max(report['panel']['bottom'], report['stack']['bottom']), report
                    if image:
                        assert abs(report['panel']['bottom'] - report['stack']['bottom']) < 1, report
                    if state_name == 'running':
                        assert 300 <= report['panel']['height'] <= 400, report
                        assert report['preview']['bottom'] <= report['panel']['bottom'], report
                        idle = reports[(report['width'], 'online-empty')]
                        assert report['generate'] == idle['generate'], (idle, report)
                        assert report['toolbar'] == idle['toolbar'], (idle, report)
                    prompt_boxes = await page.locator('[data-role="positive"], [data-role="negative"]').evaluate_all(
                        'els => els.map(el => el.getBoundingClientRect().toJSON())')
                    assert abs(prompt_boxes[0]['y'] - prompt_boxes[1]['y']) < 1, prompt_boxes
                    assert prompt_boxes[1]['x'] >= prompt_boxes[0]['right'] + 12, prompt_boxes
                    await expect(page.locator('#generate')).to_be_in_viewport()
                if state_name in {'online-empty', 'offline'}:
                    assert report['panel']['height'] < 240, report
                if image:
                    ratio = await page.locator('#selected-image-preview').evaluate('el => ({w:el.clientWidth,h:el.clientHeight,nw:el.naturalWidth,nh:el.naturalHeight})')
                    assert ratio['nw'] > 0 and abs(ratio['w'] / ratio['h'] - ratio['nw'] / ratio['nh']) < .01, ratio
                if image and not baseline_view:
                    await expect(page.locator('#selected-image-actions .image-action-status')).to_be_empty()
                    await page.locator('#selected-image-actions [data-action="trash"]').click()
                    await expect(page.locator('#selected-image-actions .image-action-status')).to_contain_text('Only the browser')
                    await page.locator('#desktop-show-details').click()
                    await expect(page.locator('#desktop-image-details')).to_be_visible()
                    await expect(page.locator('#image-metadata')).to_contain_text('Image resolution')
                    await page.evaluate("""() => {
                        Object.defineProperty(navigator, 'clipboard', {configurable:true, value:undefined});
                        document.execCommand = () => {window.copiedDetails = document.activeElement.value; return true;};
                    }""")
                    await page.locator('#desktop-copy-details').click()
                    await expect(page.locator('#desktop-copy-status')).to_have_text('Details copied.')
                    copied = await page.evaluate('copiedDetails')
                    assert all(value in copied for value in ['Image resolution', 'Negative prompt', '18446744073709551600', 'long_model_filename']), copied
                    if page.viewport_size['width'] == 1440:
                        await page.screenshot(path=str(root / f'details-{state_name}.png'))
                    await page.keyboard.press('Escape')
                    await expect(page.locator('#desktop-image-details')).not_to_be_visible()
                    await expect(page.locator('#desktop-show-details')).to_be_focused()
                    if page.viewport_size['width'] == 1440 and 'portrait' in state_name:
                        await page.evaluate("window.detailsNode = document.getElementById('image-details')")
                        await page.locator('#desktop-show-details').click()
                        await page.set_viewport_size({'width':390, 'height':844})
                        await expect(page.locator('html')).to_have_attribute('data-presentation', 'mobile')
                        await expect(page.locator('#desktop-image-details')).not_to_be_visible()
                        await expect(page.locator('#image-browse-tools > #image-details')).to_have_count(1)
                        await expect(page.locator('[data-role="positive"]')).to_have_attribute('placeholder', 'Describe your image…')
                        await page.set_viewport_size({'width':1440, 'height':900})
                        await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop')
                        assert await page.evaluate("detailsNode === document.getElementById('image-details')")
                        await expect(page.locator('[data-role="positive"]')).to_have_attribute('placeholder', 'Describe your image')
                if not baseline_view and state_name == 'online-empty':
                    # Expansion must preserve the whole workspace footprint and the
                    # same live textarea while painting above the settings below.
                    await page.evaluate('window.scrollTo(0,0)')
                    await page.evaluate("window.promptNode = document.querySelector('textarea.positive')")
                    measure = """() => Object.fromEntries(
                        ['#workflow-card','#negative-controls','#desktop-generate-slot',
                         '#settings-stack','#generation-panel','#gallery-page','#advanced'].map(selector => {
                            const b=document.querySelector(selector).getBoundingClientRect();
                            return [selector,[b.x,b.y,b.width,b.height]];
                        }))"""
                    before = await page.evaluate(measure)
                    toggle = page.locator('.prompt-editor-toggle')
                    await toggle.click()
                    await expect(toggle).to_have_attribute('aria-expanded', 'true')
                    assert await page.evaluate(measure) == before, 'Expand moved the desktop workspace'
                    overlay = await page.evaluate("""() => {
                        const input=window.promptNode, frame=input.parentElement, b=frame.getBoundingClientRect();
                        const settings=document.getElementById('settings-stack').getBoundingClientRect();
                        const hit=document.elementFromPoint(b.left+20,settings.top+10);
                        return {shadow:getComputedStyle(frame).boxShadow,
                            overlaps:b.bottom>settings.top+10, onTop:frame.contains(hit),
                            same:input===document.querySelector('textarea.positive'),
                            ratio:input.clientWidth/document.querySelector('textarea.negative').clientWidth};
                    }""")
                    assert overlay['overlaps'] and overlay['onTop'] and overlay['same'], overlay
                    assert overlay['shadow'] != 'none' and overlay['ratio'] > 2, overlay
                    await page.screenshot(path=str(root / f'{page.viewport_size["width"]}-expanded-prompt.png'))
                    # Editing the floating original is reflected immediately after Collapse.
                    draft = await page.locator('textarea.positive').input_value()
                    await page.locator('textarea.positive').fill(draft + ' Edited while expanded.')
                    if page.viewport_size['width'] == 1440:
                        await page.set_viewport_size({'width':390, 'height':844})
                        await expect(page.locator('html')).to_have_attribute('data-presentation', 'mobile')
                        assert await page.locator('textarea.positive').evaluate(
                            "el => el === window.promptNode && !el.parentElement.classList.contains('desktop-scroll-frame')")
                        await expect(toggle).to_have_attribute('aria-expanded', 'true')
                        await page.set_viewport_size({'width':1440, 'height':900})
                        await expect(page.locator('html')).to_have_attribute('data-presentation', 'desktop')
                        await page.evaluate('window.scrollTo(0,0)')
                        assert await page.evaluate(measure) == before
                    await toggle.click()
                    await expect(toggle).to_have_attribute('aria-expanded', 'false')
                    await expect(page.locator('textarea.positive')).to_have_value(draft + ' Edited while expanded.')
                    assert await page.evaluate(measure) == before, 'Collapse moved the desktop workspace'
                    await page.locator('textarea.positive').fill(draft)
                for selector in ['#generate', '#advanced > summary', '#gallery-all']:
                    await page.locator(selector).scroll_into_view_if_needed()
                    await expect(page.locator(selector)).to_be_in_viewport()
                await page.evaluate('window.scrollTo(0,0)')
                await page.screenshot(path=str(root / f'{"baseline-" if baseline_view else ""}{page.viewport_size["width"]}-{state_name}.png'), full_page=True)

            for baseline_view in ([False, True] if baseline else [False]):
                if baseline_view:
                    context, page = await open_page(1280, 800, old=True)
                    await page.wait_for_function('() => gallery.length === 2')
                for width, height in SIZES:
                    await page.set_viewport_size({'width': width, 'height': height})
                    for state_name in ['online-empty', 'offline', 'running']:
                        await check(state_name)
                    for image in images:
                        await check('generated-' + image['filename'].split('.')[0], image)
                await context.close()
            if baseline:
                for width, height in [(390, 844), (430, 932), (768, 1024), (834, 1194), (1024, 1366)]:
                    captures = []
                    for old in [True, False]:
                        mobile_context, mobile = await open_page(width, height, old)
                        if not old:
                            await mobile.set_viewport_size({'width': 1440, 'height': 900})
                            await expect(mobile.locator('html')).to_have_attribute('data-presentation', 'desktop')
                            await expect(mobile.locator('#workspace')).to_have_attribute('data-layout', 'studio')
                            await mobile.set_viewport_size({'width': width, 'height': height})
                            await expect(mobile.locator('html')).to_have_attribute('data-presentation', 'mobile')
                            await expect(mobile.locator('#workspace')).to_have_attribute('data-layout', 'compact')
                            await expect(mobile.locator('#generation-dock > #generate')).to_have_count(1)
                        # Textarea caret scrolling changes naturally with width;
                        # compare the same unfocused content position in both shells.
                        await mobile.evaluate('''() => {
                            document.activeElement?.blur();
                            document.querySelectorAll('textarea').forEach(el => {el.scrollTop = 0; el.scrollLeft = 0;});
                            window.scrollTo(0,0);
                        }''')
                        path = root / f'mobile-{width}-{"before" if old else "after"}.png'
                        await mobile.screenshot(path=str(path), full_page=True, animations='disabled', caret='hide')
                        captures.append(QImage(str(path)))
                        await mobile_context.close()
                    assert captures[0].size() == captures[1].size(), f'Mobile dimensions changed at {width}x{height}'
                    before, after = (bytes(image.constBits()) for image in captures)
                    # A compositor change after rotation can round antialiasing
                    # by one channel level; positions/content must still match.
                    assert max(abs(a - b) for a, b in zip(before, after)) <= 1, f'Mobile pixels changed at {width}x{height}'
            assert not errors, errors
            assert not stub.submissions
            assert not action_posts, action_posts
            await browser.close()
    finally:
        await runner.cleanup()
        await service.stop()
        await upstream.close()
    print(f'{engine}: all five desktop sizes; empty/offline/running and portrait/landscape results; long filenames/prompts; no overflow/overlap; normal scrolling and aspect ratios passed; mobile baseline={bool(baseline)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-web', type=Path)
    parser.add_argument('--desktop-redesign', action='store_true', help='Compare shared skins and mobile pixels, but validate the new desktop geometry independently')
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.output, args.baseline_web, args.desktop_redesign))
