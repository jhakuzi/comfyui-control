"""Batch Count is repeated journaled prompts, never an enlarged latent batch."""
import asyncio
from copy import deepcopy
import json
import uuid

import pytest
from aiohttp.test_utils import TestServer

from comfyui_control.mobile.client import ComfyError
from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from test_mobile_integration import ComfyStub, until

ALICE, BOB = 'a' * 64, 'b' * 64


async def setup(tmp_path):
    graph = {
        'sampler': dict(class_type='Sampler', inputs={'seed': 18446744073709551600, 'steps': 8}),
        'latent': dict(class_type='Latent', inputs={'batch_size': 4, 'width': 512}),
        'text': dict(class_type='Text', inputs={'text': 'unchanged'}),
        'custom': dict(class_type='UnknownCustom', inputs={'wiring': ['latent', 0], 'opaque': {'keep': True}}),
    }
    stub = ComfyStub(graph)
    upstream = TestServer(stub.app())
    await upstream.start_server()
    service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
    await service.start()
    await until(lambda: service.online)
    preset = service.presets.create('Batch fixture', graph)
    preset = service.presets.map(preset['id'], [
        dict(key='seed', node='sampler', input='seed', role='seed'),
        dict(key='batch', node='latent', input='batch_size', role='batch'),
        dict(key='text', node='text', input='text', role='positive')])
    body = dict(request_id=str(uuid.uuid4()), preset=preset['id'], revision=revision(preset),
                values={'seed': '18446744073709551600', 'batch': '4', 'text': 'repeated prompt'},
                batch_count=4, random_seed=False)
    return service, stub, upstream, graph, body


@pytest.mark.parametrize('random_seed', [False, True])
def test_batch_posts_independent_prompts_with_exact_seeds_and_idempotent_retries(tmp_path, monkeypatch, random_seed):
    async def scenario():
        service, stub, upstream, graph, body = await setup(tmp_path)
        draws = iter([11, 22, 33, 44])
        monkeypatch.setattr('comfyui_control.mobile.workflows.secrets.randbelow', lambda _limit: next(draws))
        body['random_seed'] = random_seed
        original = deepcopy(body)
        try:
            first, again = await asyncio.gather(service.submit(body, ALICE), service.submit(body, ALICE))
            assert first['id'] == again['id'] == body['request_id']
            assert len(stub.submissions) == len(service.jobs) == 4
            seeds = []
            for index, submission in enumerate(stub.submissions):
                expected = deepcopy(graph)
                expected['latent']['inputs']['batch_size'] = 1
                expected['text']['inputs']['text'] = 'repeated prompt'
                seed = [11, 22, 33, 44][index] if random_seed else 18446744073709551600
                expected['sampler']['inputs']['seed'] = seed
                seeds.append(submission['prompt']['sampler']['inputs']['seed'])
                assert submission['prompt'] == expected
                job = service.jobs[submission['extra_data']['mobile_request_id']]
                assert job['batch_id'] == first['id'] and job['batch_index'] == index + 1 and job['batch_count'] == 4
                assert job['values']['batch'] == 1 and job['values']['seed'] == seed
            assert len(set(seeds)) == (4 if random_seed else 1)
            assert body == original
            saved = json.loads((tmp_path / 'data/jobs.json').read_text())
            assert len(saved['jobs']) == 4
            reopened = MobileService(tmp_path / 'data', service.settings, service.output_dir)
            assert (await reopened.submit(body, ALICE))['id'] == first['id']
            assert len(stub.submissions) == 4
            with pytest.raises(ValueError, match='another browser'):
                await service.submit(body, BOB)
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('count', [0, -1, 21, 1.5, True, '4', None])
def test_invalid_count_never_queues_partial_work(tmp_path, count):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        try:
            body['batch_count'] = count
            with pytest.raises(ValueError, match='Batch Count'):
                await service.submit(body, ALICE)
            assert not stub.submissions and not service.jobs
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_batch_admission_is_atomic_and_old_requests_keep_saved_batch_semantics(tmp_path):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        try:
            service.jobs['existing'] = dict(id='existing', status='unknown', owner=BOB)
            body['batch_count'] = 20
            with pytest.raises(ValueError, match='20 unfinished'):
                await service.submit(body, ALICE)
            assert not stub.submissions and len(service.jobs) == 1
            body.pop('batch_count')
            await service.submit(body, ALICE)
            assert len(stub.submissions) == 1
            assert stub.submissions[0]['prompt']['latent']['inputs']['batch_size'] == 4
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('rejected', [False, True])
def test_partial_submission_stops_and_retry_never_duplicates_accepted_prompts(tmp_path, rejected):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        original = service.client.request
        calls = 0
        async def interrupted(method, path, data=None, **kwargs):
            nonlocal calls
            if method == 'POST' and path == '/prompt':
                calls += 1
                if calls == 2:
                    if not rejected:
                        await original(method, path, data, **kwargs)  # Accepted, response lost.
                    raise ComfyError('Fixture response lost or rejected', rejected=rejected)
            return await original(method, path, data, **kwargs)
        service.client.request = interrupted
        try:
            result = await service.submit(body, ALICE)
            assert calls == 2
            jobs = list(service.jobs.values())
            assert jobs[1]['status'] == ('failed' if rejected else 'unknown')
            assert all(j['status'] == 'cancelled' for j in jobs[2:])
            assert 'Batch submission stopped' in result['batch_notice']
            await service.submit(body, ALICE)
            assert calls == 2
            assert len(stub.submissions) == (1 if rejected else 2)
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_cancel_batch_is_owner_scoped_and_removes_only_its_pending_prompts(tmp_path):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        try:
            job = await service.submit(body, ALICE)
            unrelated = deepcopy(body)
            unrelated.update(request_id=str(uuid.uuid4()), batch_count=1)
            other = await service.submit(unrelated, BOB)
            with pytest.raises(ValueError, match='cancellable'):
                await service.cancel(job['id'], BOB)
            await service.cancel(job['id'], ALICE)
            assert all(j['status'] == 'cancelled' for j in service.jobs.values() if j.get('batch_id') == job['id'])
            assert [p[1] for p in stub.pending] == [other['prompt_id']]
            assert not stub.interrupts
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_cancel_during_submission_stops_unsent_runs_and_journal_survives_restart(tmp_path):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        original = service.client.request
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def hold(method, path, data=None, **kwargs):
            nonlocal calls
            if method == 'POST' and path == '/prompt':
                calls += 1
                if calls == 2:
                    started.set()
                    await release.wait()
            return await original(method, path, data, **kwargs)
        service.client.request = hold
        try:
            task = asyncio.create_task(service.submit(body, ALICE))
            await started.wait()
            reopened = MobileService(tmp_path / 'data', service.settings, service.output_dir)
            jobs = list(reopened.jobs.values())
            assert jobs[1]['status'] == 'unknown' and all(j['status'] == 'cancelled' for j in jobs[2:])
            assert (await reopened.submit(body, ALICE))['id'] == body['request_id']
            cancel = asyncio.create_task(service.cancel(body['request_id'], ALICE))
            await until(lambda: service.jobs[body['request_id']].get('batch_cancelled'))
            release.set()
            await task
            await cancel
            assert calls == 2 and not stub.pending
            assert all(j['status'] == 'cancelled' for j in service.jobs.values())
        finally:
            release.set()
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_batch_never_uses_global_interrupt_when_safe_running_cancel_is_unavailable(tmp_path):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        try:
            job = await service.submit(body, ALICE)
            stub.running = [stub.pending.pop(0)]
            stub.safe_cancel_supported = False
            await service.refresh()
            with pytest.raises(ValueError, match='Safe per-job'):
                await service.cancel(job['id'], ALICE)
            assert not stub.pending and not stub.interrupts
            assert job['status'] == 'running'
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


def test_task_cancellation_retains_uncertain_inflight_and_cancels_unsent_runs(tmp_path):
    async def scenario():
        service, stub, upstream, _, body = await setup(tmp_path)
        original = service.client.request
        started = asyncio.Event()
        async def hold(method, path, data=None, **kwargs):
            if method == 'POST' and path == '/prompt':
                started.set()
                await asyncio.Event().wait()
            return await original(method, path, data, **kwargs)
        service.client.request = hold
        try:
            task = asyncio.create_task(service.submit(body, ALICE))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            jobs = list(service.jobs.values())
            assert jobs[0]['status'] == 'unknown'
            assert all(j['status'] == 'cancelled' for j in jobs[1:])
            assert not stub.submissions
            await service.submit(body, ALICE)
            assert not stub.submissions
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())
