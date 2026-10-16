"""Manual Chromium coverage of ComfyUI catalog, Flux controls and optional login (test double)."""
import asyncio
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import json

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
sys.path.insert(0,str(REPO/'tests'))
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright,expect
from test_mobile_integration import ComfyStub
from test_mobile_workflow_sources import flux_saved
from comfyui_control.mobile.workflow_sources import editor_to_api
from comfyui_control.mobile.workflows import suggested_mappings, fields_for
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.service import MobileService, revision, json_safe
from comfyui_control.mobile.server import MobileHTTP

async def main(gguf=False):
    root=Path(tempfile.mkdtemp(prefix='comfy-mobile-controls-'))
    editor,info=flux_saved.__wrapped__()
    loader='LoaderGGUF' if gguf else 'ArbitraryDiffusion'
    model_input='gguf_name' if gguf else 'model_name'
    if gguf:
        editor['nodes'][0]['title']='GGUF Loader'
    definition=info.pop('ArbitraryDiffusion')
    definition['input']['required']={model_input:definition['input']['required']['unet_name']}
    definition['output']=['MODEL']
    info[loader]=definition
    editor['nodes'][0]['type']=loader
    original=deepcopy(editor)
    graph=editor_to_api(editor,info)
    stub=ComfyStub(graph)
    stub.object_info=info
    bad=deepcopy(editor)
    bad['nodes'][-1]['widgets_values'].append({'opaque':'cannot-convert'})
    stub.saved={'nested/Flux Portrait.json':editor,'Unsupported custom.json':bad}
    upstream=TestServer(stub.app())
    await upstream.start_server()
    settings=MobileSettings(comfy_url=str(upstream.make_url('/')))
    service=MobileService(root/'data',settings,root/'out')
    preset=service.presets.create('Desktop default',graph)
    # Simulate an older preset: no diffusion mapping and a custom prompt key/label.
    mappings=suggested_mappings(graph)
    if gguf:
        mappings=suggested_mappings(graph,info)
        next(m for m in mappings if m['node']=='diff')['role']='advanced'
    prompt_mapping=next(m for m in mappings if m['role']=='positive')
    prompt_mapping.update(key='my-prompt',label='My prompt')
    preset=service.presets.map(preset['id'],mappings,automatic=True)
    legacy_draft=json_safe({'revision':revision(preset),
        'values':{f['key']:'Unsent before upgrading' if f['role']=='positive' else f['default'] for f in fields_for(preset,info)},
        'mappings':preset['mappings'],'randomSeed':False,'disabledLoras':[]})
    other=service.presets.create('A second preset',graph)
    settings.default_preset=preset['id']
    await service.start()
    runner=web.AppRunner(MobileHTTP(service).app(),access_log=None,shutdown_timeout=1)
    await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0)
    await site.start()
    url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
    errors=[]
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
        await context.add_init_script('localStorage.setItem('+json.dumps('comfy-mobile-draft-'+preset['id'])+','+json.dumps(json.dumps(legacy_draft))+');')
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(url)
        await expect(page.locator('#preset')).to_have_value(preset['id'])
        assert await page.locator('#login').is_hidden()
        await page.locator('[data-role="diffusion_model"]').wait_for()
        assert await page.locator('#model-controls .control').count()==3
        await expect(page.locator('[data-role="positive"]')).to_have_value('Unsent before upgrading')
        await page.locator('[data-role="diffusion_model"]').select_option('another.gguf')
        await page.locator('[data-role="positive"]').fill('Keep my new draft')
        info[loader]['input']['required'][model_input][0].append('newly-installed.gguf')
        await page.locator('#refresh-models').click()
        await expect(page.locator('[data-role="diffusion_model"] option[value="newly-installed.gguf"]')).to_have_count(1)
        await expect(page.locator('[data-role="diffusion_model"]')).to_have_value('another.gguf')
        await expect(page.locator('[data-role="positive"]')).to_have_value('Keep my new draft')
        assert service.presets.get(preset['id'])['mappings'][0]['role']!='diffusion_model'
        assert await page.locator('#advanced-controls [data-role="diffusion_model"]').count()==0
        if gguf:
            assert service.presets.get(preset['id'])['mappings'][0]['role']=='advanced'
            await expect(page.locator('#model-controls select').first).to_have_attribute('data-role','diffusion_model')
        await page.locator('#preset').select_option('saved:nested/Flux Portrait.json')
        await expect(page.locator('#preset')).not_to_have_value('saved:nested/Flux Portrait.json')
        selected=await page.locator('#preset').input_value()
        assert selected!=preset['id']
        await page.locator('[data-role="diffusion_model"]').select_option('another.gguf')
        await page.locator('[data-role="vae"]').select_option('other-vae.safetensors')
        await page.locator('[data-role="text_encoder"]').select_option('other-text.gguf')
        await page.screenshot(path=str(root/'mobile-three-models.png'),full_page=True)
        await page.locator('#settings-card').evaluate('(el)=>el.open=true')
        await page.locator('[data-role="sampler"]').select_option('dpmpp_2m')
        await page.locator('[data-role="scheduler"]').select_option('karras')
        await page.locator('[data-role="steps"]').fill('32')
        await page.locator('[data-role="cfg"]').fill('4.5')
        await expect(page.get_by_role('slider',name='CFG slider',exact=True)).to_have_value('4.5')
        await page.locator('#resolution-card').evaluate('(el)=>el.open=true')
        await page.locator('[data-role="resolution_mp"]').fill('2')
        await expect(page.get_by_role('slider',name='Megapixels slider',exact=True)).to_have_value('2')
        await page.locator('[data-role="aspect_ratio"]').select_option('1:1 (Square)')
        await page.locator('[data-role="alignment"]').fill('128')
        await page.locator('[data-role="custom_ratio"]').select_option('Enable')
        await page.locator('[data-role="custom_aspect_ratio"]').fill('16:9')
        assert await page.locator('[data-role="width"]').count()==0
        for width in (320,375,390,430,768,1200):
            await page.set_viewport_size({'width':width,'height':900})
            assert await page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'),width
        await page.set_viewport_size({'width':390,'height':844})
        await page.screenshot(path=str(root/'mobile-flux-resolution.png'),full_page=True)
        await page.locator('#generate').click()
        await expect(page.locator('#job-title')).to_have_text('In the queue')
        sent=stub.submissions[0]['prompt']
        assert sent['diff']['inputs'][model_input]=='another.gguf'
        assert sent['vae']['inputs']['vae_name']=='other-vae.safetensors'
        assert sent['encoder']['inputs']['clip_name']=='other-text.gguf'
        assert sent['sampler']['inputs']['steps']==32 and sent['sampler']['inputs']['cfg']==4.5
        assert sent['sampler']['inputs']['sampler_name']=='dpmpp_2m'
        assert sent['sampler']['inputs']['width']==['resolution',0] and sent['sampler']['inputs']['height']==['resolution',1]
        assert sent['sampler']['inputs']['seed']==18446744073709551600
        assert sent['resolution']['inputs']=={'megapixel':2.0,'aspect_ratio':'1:1 (Square)','divisible_by':128,'custom_ratio':'Enable','custom_aspect_ratio':'16:9'}
        assert stub.saved['nested/Flux Portrait.json']==original
        assert service.presets.get(selected)['graph']['resolution']['inputs']['megapixel']==1.5
        await page.locator('#preset').select_option('saved:Unsupported custom.json')
        await expect(page.locator('#notice')).to_contain_text('custom widgets')
        await expect(page.locator('#preset')).to_have_value(selected)
        assert not errors,errors
        print(json.dumps({'login':'optional; fresh browser opens without a password','default':'selected from desktop preferences with multiple presets',
            'saved_workflow':'selected from ComfyUI catalog and imported','controls':'three model selectors, sampler/scheduler, steps/CFG sliders, calculator fields',
            'legacy_preset_and_unsent_draft_upgrade':'passed','diffusion_loader':loader,'diffusion_model_selection':'selectable; submitted value verified',
            'advanced_gguf_mapping_presented_in_main_model_section':gguf,
            'fresh_model_choices':'newly installed model appears without losing prompt/model edits',
            'connection_and_source_preservation':True,'fixed_64_bit_seed':'exact','mobile_widths':[320,375,390,430,768,1200],'unsupported_custom_widget':'clear error, previous form retained','javascript_errors':errors}))
        await browser.close()
    finally:
        await service.stop()
        await runner.cleanup()
        await upstream.close()
    print('Screenshots:',root)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gguf',action='store_true',help='Use the GGUF schema with an existing Advanced mapping.')
    asyncio.run(main(parser.parse_args().gguf))
