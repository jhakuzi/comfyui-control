"""Named saved workflow protocol checks; no model inference or full user graphs."""
import asyncio
from copy import deepcopy
import os
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage
import pytest

from comfyui_control.mobile.image_actions import IMAGE_WORKFLOWS, workflow_bindings, workflow_name
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.network_output import read_image
from test_mobile_integration import ComfyStub, until

ALICE, BOB = 'a' * 64, 'b' * 64


def action_graphs():
    # Only the input entries are user-verified. Other nodes deliberately stand
    # in for arbitrary custom processing and must survive without reconstruction.
    edit = {
        '88': dict(class_type='LoadImage', inputs={'image': ''}),
        '89': dict(class_type='TextEncodeQwenImage21', inputs={
            'prompt': 'saved instruction', 'negative_prompt': '', 'resolution': 1024,
            'clip': ['86', 0], 'images.image_1': ['88', 0], 'vae': ['87', 0]}),
        '86': dict(class_type='CustomTextEncoder', inputs={'file': 'encoder.gguf'}),
        '87': dict(class_type='CustomVAE', inputs={'file': 'vae.safetensors'}),
        'custom': dict(class_type='UnknownPipeline', inputs={
            'encoding': ['89', 0], 'image': ['88', 0], 'seed': 1234, 'custom_option': 'retain'}),
    }
    upscale = {
        '1': dict(class_type='LoadImage', inputs={'image': 'saved.png'}),
        'custom': dict(class_type='UnknownUpscaler', inputs={'pixels': ['1', 0], 'scale': 2.5, 'seed': 4567}),
    }
    return {IMAGE_WORKFLOWS['edit']['name'] + '.json': edit,
            IMAGE_WORKFLOWS['upscale']['name'] + '.json': upscale}


class ImageWorkflowStub(ComfyStub):
    def __init__(self):
        super().__init__({})
        self.saved = action_graphs()
        self.object_info = {node['class_type']: {'input': {}} for graph in self.saved.values() for node in graph.values()}
        self.image_names = ['saved.png']
        self.object_info['LoadImage'] = {'input': {'required': {'image': [self.image_names, {'image_upload': True}]}}}
        self.uploads = []
        self.upload_hook = None

    async def endpoint(self, request):
        if request.path == '/upload/image':
            fields = await request.post()
            file = fields['image']
            self.uploads.append({'name': file.filename, 'pixels': file.file.read(),
                                 'type': fields['type'], 'subfolder': fields['subfolder'], 'overwrite': fields['overwrite']})
            path = file.filename
            self.image_names.append(path)
            if self.upload_hook:
                self.upload_hook()
            return web.json_response({'name': file.filename, 'subfolder': fields['subfolder'], 'type': fields['type']})
        return await super().endpoint(request)


def picture(path, color=0xff446688):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(32, 48, QImage.Format.Format_RGB32)
    image.fill(color)
    image.setText('prompt', 'PRIVATE ORIGINAL PROMPT')
    assert image.save(str(path))


@pytest.mark.parametrize('network', [False, True])
def test_actions_preserve_graphs_pixels_drafts_and_existing_session_recovery(tmp_path, network):
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        output = tmp_path / 'out'
        picture(output / 'older.png')
        picture(output / 'latest.png', 0xffaa7733)
        original = (output / 'older.png').read_bytes()
        service = MobileService(tmp_path / 'data', MobileSettings(require_auth=False, comfy_url=str(upstream.make_url('/'))), output, network_output=network)
        http = TestClient(TestServer(MobileHTTP(service).app()))
        try:
            await service.start()
            await until(lambda: service.online)
            main = service.presets.create('Main generation', {'original': dict(class_type='Untouched', inputs={'text': 'unsent'})})
            before = deepcopy(service.presets.get(main['id']))
            items = await service.gallery(ALICE)
            older = next(item for item in items if item['filename'] == 'older.png')
            # Pixels are already visible to other gallery clients. Their private
            # PNG metadata must not hitchhike into the workflow upload.
            service.image_owners[service.image_ownership_key(older)] = BOB
            caps = await service.describe_image_actions(older['id'], ALICE)
            assert caps['actions']['edit']['available'] and caps['actions']['upscale']['available']
            assert not caps['actions']['trash']['available']
            request = dict(action='edit', request_id=str(uuid.uuid4()), modified=older['modified'], prompt='Golden light, preserve composition')
            first, retry = await asyncio.gather(*(service.image_action(older['id'], ALICE, request) for _ in range(2)))
            assert first['job']['id'] == retry['job']['id'] == request['request_id']
            assert len(stub.uploads) == len(stub.submissions) == 1
            upload = stub.uploads[0]
            assert upload['type'] == 'input' and upload['subfolder'] == '' and upload['overwrite'] == 'false'
            assert b'PRIVATE ORIGINAL PROMPT' not in upload['pixels']
            image = QImage.fromData(upload['pixels'])
            assert image.pixelColor(0, 0) == QImage(str(output / 'older.png')).pixelColor(0, 0)
            expected = deepcopy(stub.saved[IMAGE_WORKFLOWS['edit']['name'] + '.json'])
            expected['88']['inputs']['image'] = upload['name']
            expected['89']['inputs']['prompt'] = request['prompt']
            assert stub.submissions[0]['prompt'] == expected
            assert service.presets.get(main['id']) == before
            assert (output / 'older.png').read_bytes() == original
            assert not service.state(owner=BOB)['jobs']
            with pytest.raises(ValueError, match='another browser'):
                await service.image_action(older['id'], BOB, request)
            # Existing queue/history recovery works across service restarts.
            await service.stop()
            service = MobileService(tmp_path / 'data', service.settings, output, network_output=network)
            await service.start()
            await service.resume()
            assert service.jobs[request['request_id']]['prompt_id'] == first['job']['prompt_id']
            assert (await service.image_action(older['id'], ALICE, request))['job']['id'] == request['request_id']
            assert len(stub.submissions) == 1
            await service.gallery(ALICE)
            upscale = await service.image_action(older['id'], ALICE, dict(action='upscale', request_id=str(uuid.uuid4()), modified=older['modified']))
            expected = deepcopy(stub.saved[IMAGE_WORKFLOWS['upscale']['name'] + '.json'])
            expected['1']['inputs']['image'] = stub.uploads[-1]['name']
            assert stub.submissions[-1]['prompt'] == expected
            assert upscale['job']['preset_name'] == IMAGE_WORKFLOWS['upscale']['name']
            assert len(stub.uploads) == 2
            # Repeated edits reuse the same immutable preset, not one per image.
            await service.image_action(older['id'], ALICE, {**request, 'request_id': str(uuid.uuid4())})
            assert len(service.presets.list()) == 3
            # Existing HTTP origin checks apply to image action submissions too.
            await http.start_server()
            await http.get('/api/session')
            response = await http.post('/api/images/' + older['id'] + '/actions', json=request, headers={'Origin': 'https://other.example'})
            assert response.status == 403
        finally:
            await http.close()
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_binding_name_and_connection_validation():
    names = action_graphs()
    assert workflow_name('edit', names) == IMAGE_WORKFLOWS['edit']['name'] + '.json'
    expected = IMAGE_WORKFLOWS['upscale']['name'] + '.json'
    assert workflow_name('upscale', ['nested/' + expected]) == 'nested/' + expected
    with pytest.raises(ValueError, match='Multiple'):
        workflow_name('upscale', ['a/' + expected, 'b/' + expected])
    with pytest.raises(ValueError, match='not configured'):
        workflow_name('upscale', [])
    graph = deepcopy(names[IMAGE_WORKFLOWS['edit']['name'] + '.json'])
    graph['89']['inputs']['images.image_1'] = ['different', 0]
    with pytest.raises(ValueError, match='No connections were changed'):
        workflow_bindings('edit', graph)
    graph['88']['inputs']['image'] = ['other', 0]
    with pytest.raises(ValueError, match='image binding'):
        workflow_bindings('edit', graph)


def test_bad_sources_prompts_graphs_and_output_switch_never_queue(tmp_path):
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        output = tmp_path / 'out'
        picture(output / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
        try:
            await service.start()
            await until(lambda: service.online)
            item = (await service.gallery(ALICE))[0]
            request = dict(action='edit', prompt='make a change', request_id=str(uuid.uuid4()), modified=item['modified'])
            for prompt in ['', '   ', None, 'x' * 20001]:
                with pytest.raises(ValueError, match='instruction'):
                    await service.image_action(item['id'], ALICE, {**request, 'prompt': prompt})
            name = IMAGE_WORKFLOWS['edit']['name'] + '.json'
            saved = stub.saved[name]
            stub.saved[name] = deepcopy(saved)
            stub.saved[name]['89']['inputs']['images.image_1'] = ['87', 0]
            with pytest.raises(ValueError, match='No connections were changed'):
                await service.image_action(item['id'], ALICE, request)
            stub.saved[name] = saved
            stamp = int(item['modified']) + 1000000
            os.utime(output / 'one.png', ns=(stamp, stamp))
            with pytest.raises(ValueError, match='changed'):
                await service.image_action(item['id'], ALICE, request)
            assert not stub.uploads and not stub.submissions
            item = (await service.gallery(ALICE, force=True))[0]
            request['modified'] = item['modified']
            # Changing output while an upload is in flight must not queue a job
            # against the new output scope.
            stub.upload_hook = lambda: service.change_output(tmp_path / 'other-output')
            with pytest.raises(ValueError, match='output folder changed'):
                await service.image_action(item['id'], ALICE, request)
            assert len(stub.uploads) == 1 and not stub.submissions
            assert not service.jobs
            # Also guard a folder change inside submit's awaited validation,
            # after the action preparation has already checked its scope.
            service.change_output(output)
            await service.gallery(ALICE, force=True)
            stub.upload_hook = None
            async def switch_during_validation(*args, **kwargs):
                service.change_output(tmp_path / 'other-output')
                return None
            service.lora_choices = switch_during_validation
            with pytest.raises(ValueError, match='output folder changed'):
                await service.image_action(item['id'], ALICE, request)
            assert len(stub.uploads) == 2 and not stub.submissions and not service.jobs
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_source_read_rejects_replaced_file_and_symlink(tmp_path):
    picture(tmp_path / 'one.png')
    descriptor = dict(filename='one.png', subfolder='', type='output', expected_modified='wrong')
    with pytest.raises(ValueError, match='changed'):
        read_image(tmp_path, descriptor)
    (tmp_path / 'link.png').symlink_to(tmp_path / 'one.png')
    with pytest.raises(FileNotFoundError):
        read_image(tmp_path, {**descriptor, 'filename': 'link.png'})
