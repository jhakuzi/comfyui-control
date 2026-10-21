"""Disposable preview of the real WebUI; never loads saved configuration.

Only this mode serves an in-process ComfyUI protocol simulator. Normal generation,
sessions and gallery code remain in MobileService and MobileHTTP.
"""
import asyncio
from copy import deepcopy
from contextlib import AsyncExitStack
import json
from pathlib import Path
import signal
import tempfile
import uuid

from aiohttp import web
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

from .server import MobileHTTP
from .service import MobileService
from .settings import MobileSettings


def sample_workflow():
    return {
        'positive': {'class_type': 'DemoText', 'inputs': {'text': 'A mountain lake at sunset'}},
        'negative': {'class_type': 'DemoText', 'inputs': {'text': ''}},
        'model': {'class_type': 'DemoModel', 'inputs': {'model': 'sample-landscape.gguf'}},
        'vae': {'class_type': 'DemoVAE', 'inputs': {'vae_name': 'sample-vae.safetensors'}},
        'encoder': {'class_type': 'DemoEncoder', 'inputs': {'clip_name': 'sample-encoder.safetensors'}},
        'lora': {'class_type': 'DemoLoRA', 'inputs': {
            'model': ['model', 0], 'lora_name': 'sample-detail.safetensors', 'strength_model': .7}},
        'sampler': {'class_type': 'DemoSampler', 'inputs': {
            'positive': ['positive', 0], 'negative': ['negative', 0], 'model': ['lora', 0],
            'seed': 42, 'steps': 20, 'cfg': 5.5, 'width': 768, 'height': 1024}},
    }


def sample_image(path, graph, number):
    # Fixed-size abstract artwork, not model output. Form dimensions are metadata
    # for layout testing and cannot cause unbounded preview image allocation.
    image = QImage(768, 1024, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 768, 1024)
    gradient.setColorAt(0, QColor.fromHsv(number * 43 % 360, 150, 170))
    gradient.setColorAt(1, QColor('#0d1728'))
    painter.fillRect(0, 0, 768, 1024, gradient)
    painter.setBrush(QColor(255, 255, 255, 35))
    painter.setPen(QColor(255, 255, 255, 45))
    for index in range(5):
        painter.drawEllipse(70 + index * 90, 140 + index * 100, 300, 300)
    painter.end()
    image.setText('prompt', json.dumps(graph))
    if not image.save(str(path)):
        raise OSError('Could not create a temporary demo image.')


class DemoComfy:
    """Loopback-only simulator, intentionally unavailable outside demo mode."""

    def __init__(self, output):
        self.output = output
        self.pending, self.running, self.history = [], [], {}
        self.sockets = set()
        self.sequence = 0
        self.cancelled = set()

    async def emit(self, kind, data):
        for socket in list(self.sockets):
            if not socket.closed:
                try:
                    await socket.send_json({'type': kind, 'data': data})
                except ConnectionError:
                    self.sockets.discard(socket)

    async def ws(self, request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.sockets.add(socket)
        try:
            await socket.send_json({'type': 'status', 'data': {}})
            async for _ in socket:
                pass
        finally:
            self.sockets.discard(socket)
        return socket

    async def endpoint(self, request):
        if request.path == '/object_info':
            return web.json_response({
                'DemoText': {'input': {'required': {'text': ['STRING', {'multiline': True}]}}},
                'DemoModel': {'input': {'required': {'model': [['sample-landscape.gguf', 'sample-portrait.gguf']]}}},
                'DemoVAE': {'input': {'required': {'vae_name': [['sample-vae.safetensors']]}}},
                'DemoEncoder': {'input': {'required': {'clip_name': [['sample-encoder.safetensors']]}}},
                'DemoLoRA': {'input': {'required': {'model': ['MODEL'],
                    'lora_name': [['sample-detail.safetensors', 'sample-style.safetensors']],
                    'strength_model': ['FLOAT', {'min': 0, 'max': 2, 'step': .05}]}}},
                'DemoSampler': {'input': {'required': {
                    'positive': ['CONDITIONING'], 'negative': ['CONDITIONING'], 'model': ['MODEL'],
                    'seed': ['INT', {'min': 0, 'max': 2**64 - 1}], 'steps': ['INT', {'min': 1, 'max': 100}],
                    'cfg': ['FLOAT', {'min': 0, 'max': 30}], 'width': ['INT', {'min': 64, 'max': 2048, 'step': 64}],
                    'height': ['INT', {'min': 64, 'max': 2048, 'step': 64}]}}},
            })
        if request.path == '/userdata':
            return web.json_response(['Demo.json'])
        if request.path == '/userdata/workflows/Demo.json':
            return web.json_response(sample_workflow())
        if request.path == '/history':
            return web.json_response(self.history)
        if request.path.startswith('/history/'):
            identifier = request.path.split('/')[-1]
            return web.json_response({identifier: self.history[identifier]} if identifier in self.history else {})
        if request.path == '/queue' and request.method == 'GET':
            return web.json_response({'queue_running': self.running, 'queue_pending': self.pending})
        if request.method == 'POST':
            body = await request.json()
            if request.path == '/prompt':
                self.sequence += 1
                identifier = str(uuid.uuid4())
                self.pending.append([self.sequence, identifier, deepcopy(body['prompt']), body.get('extra_data', {}), []])
                await self.emit('status', {})
                return web.json_response({'prompt_id': identifier})
            if request.path == '/queue':
                self.pending = [item for item in self.pending if item[1] not in body.get('delete', [])]
            elif request.path.startswith('/api/jobs/') and request.path.endswith('/cancel'):
                self.cancelled.add(request.path.split('/')[-2])
                return web.json_response({'cancelled': True})
            elif request.path == '/free':
                return web.json_response({})  # No GPU memory was allocated.
            else:
                raise web.HTTPNotFound()
            await self.emit('status', {})
            return web.json_response({})
        raise web.HTTPNotFound()

    def app(self):
        app = web.Application()
        app.router.add_get('/ws', self.ws)
        app.router.add_route('*', '/{path:.*}', self.endpoint)
        return app

    async def simulate(self):
        while True:
            if not self.pending:
                await asyncio.sleep(.1)
                continue
            item = self.pending.pop(0)
            identifier, graph = item[1], item[2]
            self.running = [item]
            await self.emit('execution_start', {'prompt_id': identifier})
            await self.emit('executing', {'prompt_id': identifier, 'node': 'model'})
            await asyncio.sleep(.5)
            steps = graph.get('sampler', {}).get('inputs', {}).get('steps', 20)
            steps = min(100, max(1, steps)) if type(steps) is int else 20
            for step in range(1, steps + 1):
                if identifier in self.cancelled:
                    break
                await self.emit('progress', {'prompt_id': identifier, 'value': step, 'max': steps})
                await asyncio.sleep(3 / steps)
            cancelled = identifier in self.cancelled
            self.cancelled.discard(identifier)
            outputs = {}
            if not cancelled:
                filename = f'demo-{identifier}.png'
                sample_image(self.output / filename, graph, self.sequence)
                outputs = {'result': {'images': [{'filename': filename, 'subfolder': '', 'type': 'output'}]}}
            self.history[identifier] = {'prompt': item, 'outputs': outputs,
                'status': {'completed': not cancelled, 'status_str': 'error' if cancelled else 'success',
                           'messages': [['execution_interrupted', {'prompt_id': identifier}]] if cancelled else []}}
            self.running = []
            await self.emit('execution_interrupted' if cancelled else 'execution_success', {'prompt_id': identifier})
            await self.emit('status', {})


@web.middleware
async def demo_notice(request, handler):
    response = await handler(request)
    if request.path == '/' and response.status == 200:
        notice = ('<aside id="demo-notice" role="note" class="card hint">'
                  'Demo preview — sample images and simulated generation. No ComfyUI connection. '
                  'Demo data is discarded when this command stops.</aside>')
        response.body = response.body.replace(b'<body>', ('<body>' + notice).encode(), 1)
    return response


async def serve(host, port):
    # Explicit values and a fresh directory: never consult Config.load(),
    # MobileSettings.load(), desktop locks, mounts, models or real output folders.
    settings = MobileSettings(bind=host, port=port, require_auth=False)
    settings.validate()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        with tempfile.TemporaryDirectory(prefix='comfyui-control-demo-') as directory:
            async with AsyncExitStack() as cleanup:
                root = Path(directory)
                output = root / 'output'
                output.mkdir()
                graph = sample_workflow()
                for number in range(6):
                    sample_image(output / f'sample-{number + 1}.png', graph, number)
                demo = DemoComfy(output)
                upstream = web.AppRunner(demo.app(), access_log=None, shutdown_timeout=1)
                await upstream.setup()
                cleanup.push_async_callback(upstream.cleanup)
                site = web.TCPSite(upstream, '127.0.0.1', 0)
                await site.start()
                settings.comfy_url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
                service = MobileService(root / 'data', settings, output)
                cleanup.push_async_callback(service.stop)
                preset = service.presets.create('Demo — simulated generation', graph)
                fields = [('positive', 'text', 'positive', 'Prompt'), ('negative', 'text', 'negative', 'Negative prompt'),
                          ('model', 'model', 'diffusion_model', 'Diffusion model'), ('vae', 'vae_name', 'vae', 'VAE'),
                          ('encoder', 'clip_name', 'text_encoder', 'Text encoder'),
                          ('lora', 'lora_name', 'lora_model', 'LoRA'), ('lora', 'strength_model', 'lora_strength', 'Strength')]
                fields += [('sampler', role, role, role.title()) for role in ('seed', 'steps', 'cfg', 'width', 'height')]
                service.presets.map(preset['id'], [dict(node=node, input=name, role=role, key=role, label=label, group=node)
                                                 for node, name, role, label in fields])
                settings.default_preset = preset['id']
                await service.start()
                app = MobileHTTP(service).app()
                app.middlewares.insert(0, demo_notice)
                public = web.AppRunner(app, access_log=None, shutdown_timeout=1)
                await public.setup()
                cleanup.push_async_callback(public.cleanup)
                await web.TCPSite(public, host, port).start()
                simulation = asyncio.create_task(demo.simulate())
                async def stop_simulation():
                    simulation.cancel()
                    await asyncio.gather(simulation, return_exceptions=True)
                cleanup.push_async_callback(stop_simulation)
                print(f'Demo WebUI: {settings.url()} (listening on {host}:{port})\n'
                      'SIMULATED generation only. Temporary sample data; saved settings are untouched.\n'
                      'No password in demo mode: use a trusted LAN/VPN. Ctrl+C stops the preview.', flush=True)
                await stop.wait()
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


def run(*, host='127.0.0.1', port=8190):
    asyncio.run(serve(host, port))
    return 0
