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
        'custom': dict(class_type='UnknownUpscaler', inputs={'pixels': ['1', 0], 'scale_multiplier': 2, 'seed': 4567}),
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
        self.object_info['UnknownUpscaler'] = {'input': {'required': {'scale_multiplier': ['FLOAT', {'min': .25, 'max': 8}]}}}
        self.uploads = []
        self.upload_hook = None
        self.free_requests = []

    async def endpoint(self, request):
        if request.path == '/free':
            self.free_requests.append(await request.json())
            return web.Response(status=200)  # ComfyUI's endpoint has no JSON body.
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
    companion = expected.removesuffix('.json') + '.api.json'
    assert workflow_name('upscale', [expected, companion]) == expected
    assert workflow_name('upscale', ['nested/' + companion]) == 'nested/' + companion
    assert workflow_name('upscale', [expected, 'nested/' + companion]) == expected
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


@pytest.mark.parametrize('action', ['edit', 'upscale'])
def test_editor_import_errors_name_api_companion_and_preserve_original(tmp_path, action):
    async def scenario():
        stub = ImageWorkflowStub()
        name = IMAGE_WORKFLOWS[action]['name'] + '.json'
        api = deepcopy(stub.saved[name])
        # Reproduce both reported formats: SeedVR editor subgraphs and a
        # LoadImage node with an extra extension-provided upload widget.
        node_id = int(IMAGE_WORKFLOWS[action]['image'][0])
        editor = {'nodes': [{'id': node_id, 'type': 'LoadImage',
                             'widgets_values': ['saved.png', {'custom': 'upload control'}]}], 'links': []}
        if action == 'upscale':
            editor['definitions'] = {'subgraphs': [{'id': 'custom-editor-subgraph', 'nodes': []}]}
        stub.saved[name] = editor
        upstream = TestServer(stub.app())
        await upstream.start_server()
        output = tmp_path / 'out'
        picture(output / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output)
        try:
            await service.start()
            await until(lambda: service.online)
            item = (await service.gallery(ALICE))[0]
            request = dict(action=action, request_id=str(uuid.uuid4()), modified=item['modified'], prompt='edit instruction')
            with pytest.raises(ValueError) as error:
                await service.image_action(item['id'], ALICE, request)
            message = str(error.value)
            assert name in message and 'Nothing was queued' in message
            assert 'run it once' in message and 'Export (API)' in message
            assert IMAGE_WORKFLOWS[action]['name'] + '.api.json' in message
            assert 'Keep the original' in message and 'renaming editor JSON alone' in message
            assert not stub.uploads and not stub.submissions
            # Supplying an API companion enables the normal action without
            # replacing the desktop editor JSON or constructing its subgraphs.
            companion = name.removesuffix('.json') + '.api.json'
            stub.saved[companion] = api
            service.workflow_names_time = 0
            caps = await service.describe_image_actions(item['id'], ALICE)
            assert caps['actions'][action]['available']
            assert caps['actions'][action]['source'] == name
            result = await service.image_action(item['id'], ALICE, request)
            assert result['job']['prompt_id'] and len(stub.submissions) == 1
            expected = deepcopy(api)
            source_node, source_input = IMAGE_WORKFLOWS[action]['image']
            expected[source_node]['inputs'][source_input] = stub.uploads[0]['name']
            if action == 'edit':
                expected['89']['inputs']['prompt'] = request['prompt']
            assert stub.submissions[0]['prompt'] == expected
            assert stub.saved[name] == editor
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


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


def test_multiplier_maps_unique_numeric_input_and_preserves_workflow_defaults(tmp_path):
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
        try:
            await service.start()
            await until(lambda: service.online)
            item = (await service.gallery(ALICE))[0]
            body = dict(action='upscale', modified=item['modified'])
            name = IMAGE_WORKFLOWS['upscale']['name'] + '.json'
            original = deepcopy(stub.saved[name])
            for value in (None, 1.5, 4):
                result = await service.image_action(item['id'], ALICE, {
                    **body, 'request_id': str(uuid.uuid4()), 'multiplier': value})
                expected = deepcopy(original)
                expected['1']['inputs']['image'] = stub.uploads[-1]['name']
                if value is not None:
                    expected['custom']['inputs']['scale_multiplier'] = value
                assert stub.submissions[-1]['prompt'] == expected
                assert result['job']['values']['action-scale'] == (2 if value is None else value)
            assert len(service.presets.list()) == 1 and stub.saved[name] == original
            for value in (0, -2, True, '2', float('inf'), 10**500, .1, 9):
                with pytest.raises(ValueError):
                    await service.image_action(item['id'], ALICE, {
                        **body, 'request_id': str(uuid.uuid4()), 'multiplier': value})
            assert len(stub.submissions) == len(stub.uploads) == 3
            stub.saved[name]['another'] = dict(class_type='UnknownUpscaler', inputs={'scale_multiplier': 3})
            with pytest.raises(ValueError, match='exactly one'):
                await service.image_action(item['id'], ALICE, {**body, 'request_id': str(uuid.uuid4()), 'multiplier': 2})
            del stub.saved[name]['another']
            stub.saved[name]['custom']['inputs']['scale_multiplier'] = ['1', 0]
            with pytest.raises(ValueError, match='not a connection'):
                await service.image_action(item['id'], ALICE, {**body, 'request_id': str(uuid.uuid4()), 'multiplier': 2})
            assert len(stub.submissions) == 3
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_vram_cleanup_uses_standard_empty_response_api_and_refuses_busy_queue(tmp_path):
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
        http = TestClient(TestServer(MobileHTTP(service).app()))
        try:
            with pytest.raises(ValueError, match='Start ComfyUI'):
                await service.cleanup_vram()
            await service.start()
            await until(lambda: service.online)
            await http.start_server()
            await http.get('/api/session')
            origin = str(http.make_url('/')).rstrip('/')
            assert (await http.post('/api/vram/cleanup', json={}, headers={'Origin': 'https://other.example'})).status == 403
            assert not stub.free_requests
            response = await http.post('/api/vram/cleanup', json={}, headers={'Origin': origin})
            assert response.status == 200
            assert 'requested' in (await response.json())['message']
            assert stub.free_requests == [{'unload_models': True, 'free_memory': True}]
            for queue in (stub.pending, stub.running):
                queue.append([1, 'desktop-job', {}, {}, []])
                response = await http.post('/api/vram/cleanup', json={}, headers={'Origin': origin})
                assert response.status == 400 and 'running or queued' in (await response.json())['error']
                queue.clear()
            assert len(stub.free_requests) == 1 and not stub.submissions and not service.jobs
            service.settings.require_auth = True
            assert (await http.post('/api/vram/cleanup', json={}, headers={'Origin': origin})).status == 401
        finally:
            await http.close()
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_old_action_preset_and_jobs_are_retained_when_multiplier_mapping_is_added(tmp_path):
    from comfyui_control.mobile.image_actions import workflow_bindings
    from comfyui_control.mobile.settings import save_json
    async def scenario():
        stub = ImageWorkflowStub()
        upstream = TestServer(stub.app())
        await upstream.start_server()
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
        try:
            await service.start()
            await until(lambda: service.online)
            name = IMAGE_WORKFLOWS['upscale']['name'] + '.json'
            graph = stub.saved[name]
            old = service.presets.create('Previous upscale preset', graph)
            old = service.presets.map(old['id'], workflow_bindings('upscale', graph))
            old['image_workflow'] = dict(action='upscale', source=name)
            save_json(service.presets.path(old['id']), old)
            service.jobs['old-job'] = dict(id='old-job', owner=ALICE, preset=old['id'], created=1,
                scope=service.output_scope, status='complete', images=[])
            previous_job = deepcopy(service.jobs['old-job'])
            item = (await service.gallery(ALICE))[0]
            result = await service.image_action(item['id'], ALICE, dict(action='upscale', multiplier=1.5,
                request_id=str(uuid.uuid4()), modified=item['modified']))
            assert result['job']['preset'] != old['id']
            assert result['job']['values']['action-scale'] == 1.5
            assert service.presets.get(old['id']) == old and service.jobs['old-job'] == previous_job
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_vram_cleanup_does_not_treat_an_unknown_queue_as_idle(tmp_path):
    class InvalidQueue:
        async def request(self, method, path, data=None):
            assert (method, path) == ('GET', '/queue'), 'Memory release must not be requested without a verifiable empty queue'
            return {}
    async def scenario():
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        service.online = True
        service.client = InvalidQueue()
        with pytest.raises(ValueError, match='Could not verify'):
            await service.cleanup_vram()
    asyncio.run(scenario())
