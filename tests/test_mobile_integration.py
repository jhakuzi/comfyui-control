"""Protocol integration with an explicit ComfyUI test double, not model inference."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import socket
import struct
import time
import uuid

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

from comfyui_control.config import Config
from comfyui_control.mobile.runtime import MobileRuntime
from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings


async def until(predicate, timeout=5):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError('Timed out waiting for the expected ComfyUI event')
        await asyncio.sleep(.02)


class ComfyStub:
    def __init__(self, graph):
        self.graph = graph
        self.pending, self.running, self.history = [], [], {}
        self.sockets = set()
        self.submissions = []
        self.interrupts = []
        self.safe_cancel_supported = True

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        await ws.send_json({'type': 'status', 'data': {}})
        try:
            async for message in ws:
                pass
        finally:
            self.sockets.discard(ws)
        return ws

    async def emit(self, kind, data):
        for ws in list(self.sockets):
            await ws.send_json({'type': kind, 'data': data})

    async def endpoint(self, request):
        if request.path == '/object_info':
            return web.json_response({node['class_type']: {'input': {}} for node in self.graph.values()})
        if request.path == '/history':
            return web.json_response(self.history)
        if request.path == '/queue' and request.method == 'GET':
            return web.json_response({'queue_running': self.running, 'queue_pending': self.pending})
        body = await request.json()
        if request.path == '/prompt':
            self.submissions.append(deepcopy(body))
            prompt_id = str(uuid.uuid4())
            self.pending.append([len(self.submissions), prompt_id, body['prompt'], body['extra_data'], []])
            await self.emit('status', {})
            return web.json_response({'prompt_id': prompt_id})
        if request.path == '/queue':
            self.pending = [item for item in self.pending if item[1] not in body.get('delete', [])]
        if request.path == '/interrupt':
            self.interrupts.append(body)
        if request.path.startswith('/api/jobs/') and request.path.endswith('/cancel'):
            if not self.safe_cancel_supported:
                raise web.HTTPNotFound()
            self.interrupts.append({'prompt_id': request.path.split('/')[-2]})
            return web.json_response({'cancelled': True})
        return web.json_response({})

    def app(self):
        app = web.Application()
        app.router.add_get('/ws', self.ws)
        app.router.add_route('*', '/{path:.*}', self.endpoint)
        return app


def test_submit_progress_preview_completion_reconnect_gallery_and_idempotency(tmp_path, mobile_graph):
    async def scenario():
        graph = deepcopy(mobile_graph)
        stub = ComfyStub(graph)
        upstream = TestServer(stub.app())
        await upstream.start_server()
        settings = MobileSettings(require_auth=False, comfy_url=str(upstream.make_url('/')).rstrip('/'))
        output = tmp_path/'output'
        output.mkdir()
        png = (Path(__file__).parents[1]/'comfyui_control/assets/comfyui-control.png').read_bytes()
        (output/'result.png').write_bytes(png)
        service = MobileService(tmp_path/'data', settings, output)
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        origin = str(client.make_url('/')).rstrip('/')
        try:
            await service.start()
            await until(lambda: service.online)
            preset = service.presets.create('Custom graph', graph)
            preset = service.presets.map(preset['id'], [{'node': 'arbitrary-text', 'input': 'sentence', 'role': 'positive', 'key': 'prompt'}])
            request = {'request_id': str(uuid.uuid4()), 'preset': preset['id'], 'revision': revision(preset), 'values': {'prompt': 'new idea'}}
            response = await client.post('/api/generate', json=request, headers={'Origin': origin})
            assert response.status == 202, await response.text()
            first = await response.json()
            second = await service.submit(request)
            assert first['id'] == second['id'] and len(stub.submissions) == 1
            expected = deepcopy(graph)
            expected['arbitrary-text']['inputs']['sentence'] = 'new idea'
            assert stub.submissions[0]['prompt'] == expected
            stream = await client.get('/api/events')
            assert (await stream.content.readline()).startswith(b'data: ')
            stream.close()
            job = service.jobs[first['id']]
            stub.running, stub.pending = stub.pending, []
            await stub.emit('execution_start', {'prompt_id': job['prompt_id']})
            await stub.emit('progress', {'prompt_id': job['prompt_id'], 'value': 3, 'max': 10})
            for ws in stub.sockets:
                await ws.send_bytes(struct.pack('>II', 1, 2) + png)
            await until(lambda: (job.get('progress') or {}).get('value') == 3 and service.preview is not None)
            assert service.preview[0] == png
            version = service.preview_version
            metadata = json.dumps({'prompt_id': job['prompt_id'], 'image_type': 'image/png'}).encode()
            for ws in stub.sockets:
                await ws.send_bytes(struct.pack('>II', 4, len(metadata)) + metadata + png)
            await until(lambda: service.preview_version > version)
            assert service.preview[0] == png and service.preview_job == job['id']
            stub.history[job['prompt_id']] = {'prompt': stub.running[0], 'status': {'status_str': 'success'},
                                           'outputs': {'custom-upscaler': {'images': [{'filename': 'result.png', 'subfolder': '', 'type': 'output'}]}}}
            stub.running = []
            await stub.emit('execution_success', {'prompt_id': job['prompt_id']})
            await until(lambda: bool(job['images']))
            assert job['status'] == 'complete'
            images = await service.gallery()
            assert images[0]['job'] == job['id']
            image = await client.get(images[0]['url'])
            assert await image.read() == png
            assert image.headers['Cache-Control'] == 'no-store'
            thumbnail = await client.get(images[0]['thumbnail'])
            assert thumbnail.status == 200
            assert thumbnail.content_type == 'image/jpeg'
            reduced = QImage.fromData(await thumbnail.read())
            assert not reduced.isNull() and max(reduced.width(), reduced.height()) <= 384
            downloaded = await client.get(images[0]['download'])
            assert await downloaded.read() == png
            assert 'attachment' in downloaded.headers['Content-Disposition']
            await service.stop()
            restored = MobileService(tmp_path/'data', settings, output)
            assert restored.jobs[job['id']]['values'] == {'prompt': 'new idea'}
            assert restored.images[job['images'][0]['id']]['job'] == job['id']
            await restored.start()
            await until(lambda: restored.online)
            assert restored.jobs[job['id']]['status'] == 'complete'
            await restored.stop()
        finally:
            await service.stop()
            await client.close()
            await upstream.close()
    asyncio.run(scenario())


def test_cancel_targets_only_an_owned_pending_or_running_job(tmp_path, mobile_graph):
    async def scenario():
        stub = ComfyStub(deepcopy(mobile_graph))
        upstream = TestServer(stub.app())
        await upstream.start_server()
        service = MobileService(tmp_path, MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path/'out')
        await service.start()
        try:
            await until(lambda: service.online)
            service.jobs['owned'] = {'id': 'owned', 'prompt_id': 'owned-prompt', 'status': 'queued', 'images': []}
            stub.pending = [[1, 'owned-prompt', {}, {}, []]]
            await service.cancel('owned')
            assert not stub.pending and service.jobs['owned']['status'] == 'cancelled'
            stub.running = [[2, 'someone-else', {}, {}, []]]
            await service.cancel('owned')
            assert not stub.interrupts
            stub.running = [[3, 'owned-prompt', {}, {}, []]]
            await service.cancel('owned')
            assert stub.interrupts == [{'prompt_id': 'owned-prompt'}]
            stub.interrupts.clear()
            stub.safe_cancel_supported = False
            try:
                await service.cancel('owned')
            except ValueError as exc:
                assert 'No global interrupt' in str(exc)
            else:
                raise AssertionError('Old servers must not receive a global interrupt')
            assert not stub.interrupts
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_runtime_lifecycle_port_conflict_and_reconfigure_keep_qt_responsive(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    with socket.socket() as busy:
        busy.bind(('127.0.0.1', 0))
        busy.listen()
        port = busy.getsockname()[1]
        settings = MobileSettings(enabled=True, port=port, require_auth=False)
        runtime = MobileRuntime()
        runtime.configure(settings, Config())
        end = time.monotonic() + 5
        while runtime.running and time.monotonic() < end:
            app.processEvents()
            time.sleep(.01)
        assert 'Could not start' in runtime.status
    runtime.configure(settings, Config())
    end = time.monotonic() + 5
    while runtime.status != 'Listening' and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert runtime.status == 'Listening'
    runtime.configure(MobileSettings(), Config())
    end = time.monotonic() + 5
    while runtime.running and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert not runtime.running
