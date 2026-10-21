"""Generation mappings and batch requests share the normal persisted job queue."""
import asyncio
from copy import deepcopy
import json
import time
import uuid

import pytest

from comfyui_control.mobile.client import ComfyError
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings, save_json
from comfyui_control.mobile.workflows import fields_for, suggested_mappings
from test_resolution_controls import controlaltai_resolution


@pytest.fixture
def generation_workflow(controlaltai_resolution):
    graph, info = deepcopy(controlaltai_resolution)
    graph['3']['inputs'].update(seed=18446744073709551600, steps=20, cfg=3.5,
                                sampler_name='euler', scheduler='simple')
    info['Sampler']['input']['required'].update(
        seed=['INT', {'min': 0, 'max': 2**64 - 1}], steps=['INT', {'min': 1, 'max': 100}],
        cfg=['FLOAT', {'min': 0, 'max': 30}], sampler_name=[['euler', 'dpmpp_2m']],
        scheduler=[['simple', 'karras']])
    return graph, info


def prepare(tmp_path, workflow):
    graph, info = workflow
    service = MobileService(tmp_path / 'data', MobileSettings(require_auth=False), tmp_path / 'out')
    preset = service.presets.create('Generation controls', graph)
    preset = service.presets.map(preset['id'], suggested_mappings(graph, info))
    service.info, service.info_time = info, time.monotonic()
    service.schedule_refresh = lambda: None
    return service, preset


class QueueClient:
    def __init__(self, service):
        self.service = service
        self.posts, self.pending, self.running, self.cancels = [], [], [], []
        self.fail_at = None
        self.change_output = False
        self.safe_cancel = True

    async def request(self, method, path, body=None):
        if path == '/prompt':
            identifier = body['extra_data']['mobile_request_id']
            journal = json.loads((self.service.directory / 'jobs.json').read_text())['jobs']
            assert journal[identifier]['status'] == 'submitting'
            self.posts.append(deepcopy(body))
            prompt_id = str(uuid.uuid4())
            self.pending.append([len(self.posts), prompt_id, body['prompt'], body['extra_data'], []])
            if len(self.posts) == self.fail_at:
                raise ComfyError('Response lost')
            if self.change_output:
                self.service.change_output(self.service.output_dir.parent / 'new-output')
            return {'prompt_id': prompt_id}
        if path == '/queue' and method == 'GET':
            return {'queue_pending': self.pending, 'queue_running': self.running}
        if path == '/queue':
            self.cancels.extend(body['delete'])
            self.pending = [p for p in self.pending if p[1] not in body['delete']]
            return {}
        if path.startswith('/api/jobs/'):
            if not self.safe_cancel:
                raise ComfyError('Unsupported', rejected=True)
            self.cancels.append(path.split('/')[3])
            return {'cancelled': True}
        if path.startswith('/history'):
            return {}
        raise AssertionError((method, path))


def request(preset, count=1, **kwargs):
    return {'request_id': str(uuid.uuid4()), 'preset': preset['id'], 'revision': revision(preset),
            'values': {}, 'random_seed': False, 'batch_count': count, **kwargs}


def test_generation_discovery_keeps_advanced_mappings_and_split_inputs(tmp_path, generation_workflow):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        previous = [m for m in preset['mappings'] if m['role'] not in {'steps', 'sampler', 'scheduler', 'seed', 'batch'}]
        cfg = next(m for m in previous if m['role'] == 'cfg')
        cfg.update(role='advanced', key='my-cfg', label='My guidance')
        preset = service.presets.map(preset['id'], previous)
        preset.pop('generation_controls_version')
        save_json(service.presets.path(preset['id']), preset)
        described = await service.describe(preset)
        upgraded = service.presets.get(preset['id'])
        assert upgraded['graph'] == preset['graph'] and upgraded['mappings'][:len(previous)] == previous
        assert described['model_upgrade_revision'] == revision(preset)
        field = next(f for f in described['fields'] if f['key'] == 'my-cfg')
        assert field['generation_role'] == 'cfg' and field['role'] == 'advanced'
        assert {'steps', 'sampler', 'scheduler', 'seed', 'batch'} <= {f['role'] for f in described['fields']}
        hidden = service.presets.map(preset['id'], previous)
        assert not any(f['role'] == 'seed' for f in (await service.describe(hidden))['fields'])
    asyncio.run(scenario())
    # Connected sampler/seed/CFG widgets stay linked; map their literal sources.
    graph = {'sample': {'class_type': 'AdvancedSampler', 'inputs': {
        'sampler': ['select', 0], 'noise': ['noise', 0], 'guider': ['guider', 0], 'sigmas': ['schedule', 0]}},
        'select': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
        'noise': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': 42}},
        'guider': {'class_type': 'CFGGuider', 'inputs': {'cfg': 3.5}},
        'schedule': {'class_type': 'BasicScheduler', 'inputs': {'scheduler': 'simple', 'steps': 20}}}
    mapped = {(m['node'], m['input']): m['role'] for m in suggested_mappings(graph)}
    assert mapped == {('select', 'sampler_name'): 'sampler', ('noise', 'noise_seed'): 'seed',
                      ('guider', 'cfg'): 'cfg', ('schedule', 'scheduler'): 'scheduler', ('schedule', 'steps'): 'steps'}


def test_batch_count_size_random_seeds_idempotency_and_restart(tmp_path, generation_workflow, monkeypatch):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        service.client = client = QueueClient(service)
        fields = {f['role']: f for f in fields_for(preset, service.info)}
        counter = iter([101, 202, 303])
        monkeypatch.setattr('comfyui_control.mobile.workflows.secrets.randbelow', lambda _: next(counter))
        body = request(preset, 3, random_seed=True, values={fields['batch']['key']: 4})
        first = await service.submit(body, owner='phone')
        assert len(client.posts) == 3 and len(service.jobs) == 3
        assert [p['prompt']['3']['inputs']['seed'] for p in client.posts] == [101, 202, 303]
        assert all(p['prompt']['60']['inputs']['batch_size'] == 4 for p in client.posts)
        assert all(p['prompt']['60']['inputs']['width'] == ['59', 0] for p in client.posts)
        assert [j['batch_index'] for j in service.jobs.values()] == [1, 2, 3]
        assert all(j['batch_id'] == first['id'] and j['batch_count'] == 3 for j in service.jobs.values())
        assert await service.submit(body, owner='phone') is first
        assert len(client.posts) == 3
        with pytest.raises(ValueError, match='another browser'):
            await service.submit(body, owner='other')
        with pytest.raises(ValueError, match='limit of 20'):
            await service.submit(request(preset, 18), owner='phone')
        restarted = MobileService(service.directory, service.settings, service.output_dir)
        assert (await restarted.submit(body, owner='phone'))['id'] == first['id']
        assert len(restarted.jobs) == 3
        assert restarted.state(owner='other')['jobs'] == []
    asyncio.run(scenario())


@pytest.mark.parametrize('count', [0, 21, True, '2', 1.5])
def test_invalid_batch_counts_queue_nothing(tmp_path, generation_workflow, count):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        service.client = client = QueueClient(service)
        with pytest.raises(ValueError, match='Batch count'):
            await service.submit(request(preset, count))
        assert not service.jobs and not client.posts
    asyncio.run(scenario())


def test_partial_batch_response_loss_stops_without_retrying(tmp_path, generation_workflow):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        service.client = client = QueueClient(service)
        client.fail_at = 2
        body = request(preset, 4)
        first = await service.submit(body, owner='phone')
        assert len(client.posts) == 2 and len(service.jobs) == 2
        assert 'run 2 of 4' in first['batch_notice']
        assert list(service.jobs.values())[1]['status'] == 'unknown'
        assert all(p['prompt']['3']['inputs']['seed'] == 18446744073709551600 for p in client.posts)
        await service.submit(body, owner='phone')
        assert len(client.posts) == 2
        # Normal reconciliation finds the accepted run whose response was lost.
        await service.refresh()
        assert all(j['prompt_id'] for j in service.jobs.values())
    asyncio.run(scenario())


def test_batch_stops_when_output_changes(tmp_path, generation_workflow):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        service.client = client = QueueClient(service)
        client.change_output = True
        first = await service.submit(request(preset, 3))
        assert len(client.posts) == 1 and len(service.jobs) == 1
        assert 'output folder changed' in first['batch_notice']
    asyncio.run(scenario())


@pytest.mark.parametrize('safe_running_cancel', [True, False])
def test_cancel_batch_preserves_other_browser_and_never_interrupts_globally(tmp_path, generation_workflow, safe_running_cancel):
    async def scenario():
        service, preset = prepare(tmp_path, generation_workflow)
        service.client = client = QueueClient(service)
        first = await service.submit(request(preset, 3), owner='phone')
        other = await service.submit(request(preset), owner='other')
        client.running = [client.pending.pop(0)]
        await service.refresh()
        client.safe_cancel = safe_running_cancel
        with pytest.raises(ValueError, match='cancellable'):
            await service.cancel_batch(first['id'], owner='other')
        if safe_running_cancel:
            await service.cancel_batch(first['id'], owner='phone')
            assert first['status'] == 'cancelling'
        else:
            with pytest.raises(ValueError, match='Some batch runs'):
                await service.cancel_batch(first['id'], owner='phone')
        assert all(j['status'] == 'cancelled' for j in list(service.jobs.values())[1:3])
        assert client.pending == [p for p in client.pending if p[1] == other['prompt_id']]
        assert other['prompt_id'] not in client.cancels
    asyncio.run(scenario())
