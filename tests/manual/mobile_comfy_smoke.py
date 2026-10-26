"""Optional image/queue test against an existing ComfyUI; no diffusion model needed."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision

async def check(comfy_url, output):
    graph = json.loads((REPO/'examples/mobile-smoke-api.json').read_text())
    graph['save']['inputs']['filename_prefix'] += '-' + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix='comfy-mobile-smoke-') as temporary:
        root = Path(temporary)
        settings = MobileSettings(require_auth=False, comfy_url=comfy_url)
        service = MobileService(root/'state', settings, output or root/'output')
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        await client.get('/api/session')
        origin = str(client.make_url('/')).rstrip('/')
        try:
            await service.start()
            for _ in range(200):
                if service.online:
                    break
                await asyncio.sleep(.1)
            assert service.online, service.connection
            preset = service.presets.create('CPU image/upscale smoke test', graph)
            preset = service.presets.map(preset['id'], [
                {'node':'canvas','input':'width','role':'width','key':'width'},
                {'node':'canvas','input':'height','role':'height','key':'height'},
                {'node':'canvas','input':'batch_size','role':'batch','key':'batch'}])
            body = {'request_id':str(uuid.uuid4()),'preset':preset['id'],'revision':revision(preset),
                    'values':{'width':96,'height':80,'batch':2}}
            response = await client.post('/api/generate', json=body, headers={'Origin':origin})
            assert response.status == 202, await response.text()
            initial = await response.json()
            job = service.jobs[initial['id']]
            for _ in range(600):
                if job['status'] == 'failed' or job['images']:
                    break
                await asyncio.sleep(.1)
            assert job['status'] == 'complete', job
            assert len(job['images']) == 2, job
            for item in job['images']:
                image_response = await client.get(item['url'])
                assert image_response.status == 200
                image = QImage.fromData(await image_response.read())
                assert (image.width(), image.height()) == (128,128)
                metadata = json.loads(image.text('prompt'))
                assert metadata['canvas']['inputs']['width'] == 96
                assert metadata['upscale']['inputs']['image'] == ['canvas',0]
                thumbnail = await client.get(item['thumbnail'])
                assert thumbnail.status == 200
                assert thumbnail.content_type == 'image/jpeg'
                reduced = QImage.fromData(await thumbnail.read())
                assert not reduced.isNull() and max(reduced.width(), reduced.height()) <= 384
                details = await (await client.get('/api/images/' + item['id'] + '/details')).json()
                assert details['source'] == 'mobile'
                assert next(field['value'] for field in details['parameters'] if field['label']=='Width') == 96
                if output:
                    assert details['image'] == {'width':128, 'height':128}
            # An independent ComfyUI submission has no mobile job/mappings.
            direct = deepcopy(graph)
            direct['save']['inputs']['filename_prefix'] += '-direct'
            accepted = await service.client.request('POST','/prompt',{'prompt':direct,'client_id':str(uuid.uuid4())})
            for _ in range(200):
                history = await service.client.request('GET','/history/' + accepted['prompt_id'])
                if accepted['prompt_id'] in history:
                    break
                await asyncio.sleep(.1)
            descriptors = [item for node in history[accepted['prompt_id']]['outputs'].values() for item in node.get('images',[])]
            assert descriptors
            if output:
                ref = service.image_ref(descriptors[0])
                details = await service.image_details(ref['id'],job['owner'])
                assert details['source'] == 'png' and details['image'] == {'width':128,'height':128}
            again = await client.post('/api/generate',json=body,headers={'Origin':origin})
            assert (await again.json())['prompt_id'] == job['prompt_id']
            assert service.presets.get(preset['id'])['graph'] == graph
            assert any(item['job'] == job['id'] for item in await service.gallery())
            print('PASS: actual ComfyUI queue, images/upscaling, download/gallery, mobile and direct PNG details, exact graph preservation, and duplicate-request protection.')
            print('This test did not run diffusion or LoRA inference. Smoke-test images remain in ComfyUI output.')
        finally:
            await service.stop()
            await client.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-url', default='http://127.0.0.1:8188')
    parser.add_argument('--comfy-output', type=Path, default=None)
    arguments = parser.parse_args()
    asyncio.run(check(arguments.comfy_url, arguments.comfy_output))
