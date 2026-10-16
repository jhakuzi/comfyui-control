"""Queues model-free images after importing a temporary saved editor workflow from real ComfyUI."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import quote
import uuid

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
import aiohttp
from PySide6.QtGui import QImage
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.service import MobileService

async def check(url):
    name='mobile-editor-smoke-'+uuid.uuid4().hex+'.json'
    api=json.loads((REPO/'examples/mobile-smoke-api.json').read_text())
    api['save']['inputs']['filename_prefix'] += '-editor-'+uuid.uuid4().hex[:8]
    editor={'nodes':[
        {'id':'canvas','type':'EmptyImage','widgets_values':[64,64,1,3200000]},
        {'id':'upscale','type':'ImageScale','inputs':[{'name':'image','link':1}], 'widgets_values':['lanczos',128,128,'disabled']},
        {'id':'save','type':'SaveImage','inputs':[{'name':'images','link':2}], 'widgets_values':[api['save']['inputs']['filename_prefix']]},
        ],'links':[[1,'canvas',0,'upscale',0,'IMAGE'],[2,'upscale',0,'save',0,'IMAGE']]}
    endpoint=url.rstrip('/')+'/userdata/'+quote('workflows/'+name,safe='')
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint,params={'overwrite':'false'},json=editor) as response:
            assert response.status==200,await response.text()
        try:
            with tempfile.TemporaryDirectory(prefix='mobile-real-saved-') as temporary:
                service=MobileService(Path(temporary),MobileSettings(comfy_url=url),Path(temporary)/'out')
                await service.start()
                try:
                    for _ in range(200):
                        if service.online:break
                        await asyncio.sleep(.1)
                    assert service.online,service.connection
                    assert name in await service.saved_workflows()
                    preset=await service.import_saved_workflow(name)
                    stored=service.presets.get(preset['id'])
                    assert {key:node['inputs'] for key,node in stored['graph'].items()}=={key:node['inputs'] for key,node in api.items()}
                    values={field['key']:96 if field['input']=='width' else 80 if field['input']=='height' else 2
                        for field in preset['fields'] if field['node']=='canvas' and field['input'] in {'width','height','batch_size'}}
                    job=await service.submit({'request_id':str(uuid.uuid4()),'preset':preset['id'],'revision':preset['revision'],'values':values},owner='smoke-client')
                    for _ in range(600):
                        if job['images'] or job['status']=='failed':break
                        await asyncio.sleep(.1)
                    assert job['status']=='complete' and len(job['images'])==2,job
                    for item in job['images']:
                        params={key:item[key] for key in ('filename','subfolder','type')}
                        async with session.get(url.rstrip('/')+'/view',params=params) as response:
                            image=QImage.fromData(await response.read())
                        assert (image.width(),image.height())==(128,128)
                    async with session.get(endpoint) as response:
                        assert await response.json(content_type=None)==editor
                    print('PASS: real ComfyUI saved-workflow catalog, metadata conversion, preserved links/source, auto-mapped controls, and 2 generated/upscaled images.')
                    print('No diffusion/LoRA inference; only the temporary workflow is removed. Smoke images remain in ComfyUI output.')
                finally:
                    await service.stop()
        finally:
            async with session.delete(endpoint) as response:
                assert response.status in (200,204),await response.text()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-url',default='http://127.0.0.1:8188')
    asyncio.run(check(parser.parse_args().comfy_url))
