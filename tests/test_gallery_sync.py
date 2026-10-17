"""Filesystem reconciliation must not resurrect deleted job output or mix owners."""
import asyncio
from copy import deepcopy
import os
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings


def image(path):
    result = QImage(16, 24, QImage.Format.Format_RGB32)
    result.fill(0)
    assert result.save(str(path))


def test_deleted_job_output_stays_deleted_across_scans_and_restart(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        output.mkdir()
        image(output / 'one.png')
        image(output / 'two.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        service.jobs['job'] = {'id': 'job', 'owner': 'alice', 'created': 1, 'status': 'complete', 'seconds_per_iteration': None}
        ref = service.image_ref({'filename': 'one.png'}, 'job')
        service.jobs['job']['images'] = [deepcopy(ref)]
        service.persist()
        jobs = deepcopy(service.jobs)
        assert len(await service.gallery('alice')) == 2
        (output / 'one.png').unlink()
        for _ in range(2):
            assert [item['filename'] for item in await service.gallery('alice', force=True)] == ['two.png']
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        assert [item['filename'] for item in await reopened.gallery('alice')] == ['two.png']
        assert service.jobs == reopened.jobs == jobs
        image(output / 'one.png')
        restored = await service.gallery('alice', force=True)
        assert len(restored) == 2 and next(item for item in restored if item['id'] == ref['id'])['job'] == 'job'
    asyncio.run(scenario())


def test_replacement_versions_urls_and_filters_job_ownership_on_cached_lists(tmp_path):
    async def scenario():
        image(tmp_path / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path)
        service.jobs['job'] = {'id': 'job', 'owner': 'alice'}
        ref = service.image_ref({'filename': 'one.png'}, 'job')
        service.jobs['job']['images'] = [deepcopy(ref)]
        first = (await service.gallery('alice'))[0]
        foreign = (await service.gallery('bob'))[0]
        assert first['job'] == 'job' and foreign['job'] is None
        path = tmp_path / 'one.png'
        stamp = path.stat().st_mtime_ns + 1000000
        os.utime(path, ns=(stamp, stamp))
        second = (await service.gallery('alice', force=True))[0]
        assert second['id'] == first['id'] and second['url'] != first['url']
        assert second['thumbnail'] != first['thumbnail'] and second['download'] != first['download']
    asyncio.run(scenario())


def test_gallery_never_advertises_symlink_files_or_symlink_directories(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        output.mkdir()
        image(tmp_path / 'outside.png')
        (output / 'file.png').symlink_to(tmp_path / 'outside.png')
        (output / 'folder').symlink_to(tmp_path, target_is_directory=True)
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        service.image_ref({'filename': 'file.png'})
        service.image_ref({'filename': 'outside.png', 'subfolder': 'folder'})
        assert await service.gallery() == []
    asyncio.run(scenario())


def test_concurrent_clients_share_scan_and_changed_output_discards_old_scan(tmp_path, monkeypatch):
    async def scenario():
        first, second = tmp_path / 'first', tmp_path / 'second'
        first.mkdir(); second.mkdir()
        image(first / 'old.png'); image(second / 'new.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), first)
        original = service.scan_gallery
        scans = 0
        async def counted():
            nonlocal scans
            scans += 1
            await asyncio.sleep(.02)
            await original()
        monkeypatch.setattr(service, 'scan_gallery', counted)
        results = await asyncio.gather(*(service.gallery(str(i), force=True) for i in range(5)))
        assert scans == 1 and all(len(result) == 1 for result in results)
        await service.gallery('sixth')
        assert scans == 1
        # Output may change on the event loop while filesystem I/O is in flight.
        import comfyui_control.mobile.service as module
        to_thread = module.asyncio.to_thread
        async def switched(function, *args):
            service.change_output(second)
            return await to_thread(function, *args)
        monkeypatch.setattr(module.asyncio, 'to_thread', switched)
        assert await service.gallery(force=True) == []
        monkeypatch.setattr(module.asyncio, 'to_thread', to_thread)
        assert [item['filename'] for item in await service.gallery(force=True)] == ['new.png']
    asyncio.run(scenario())


def test_gallery_revision_and_missing_local_image_http(tmp_path):
    async def scenario():
        image(tmp_path / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path)
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            assert isinstance(await (await client.get('/api/gallery')).json(), list)
            first = await (await client.get('/api/gallery?since=')).json()
            revision = first['revision']
            assert len(first['images']) == 1
            unchanged = await (await client.get('/api/gallery?since=' + revision)).json()
            assert unchanged == {'revision': revision, 'images': None}
            (tmp_path / 'one.png').unlink()
            # Must not proxy a deleted local image back to ComfyUI or serve a
            # stale cached thumbnail. No ComfyUI session is even needed here.
            response = await client.get(first['images'][0]['thumbnail'])
            assert response.status == 404
            changed = await (await client.get('/api/gallery?since=' + revision)).json()
            assert changed['images'] == [] and changed['revision'] != revision
        finally:
            await client.close()
    asyncio.run(scenario())


def test_remote_and_temp_refs_survive_network_errors_but_not_confirmed_deletions(tmp_path):
    async def scenario():
        status = 503
        async def view(request):
            return web.Response(status=status)
        app = web.Application()
        app.router.add_get('/view', view)
        upstream = TestServer(app)
        await upstream.start_server()
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'not-local')
        service.local_comfy = False
        remote = service.image_ref({'filename': 'remote.png'})
        temporary = service.image_ref({'filename': 'preview.png', 'type': 'temp'})
        service.session = aiohttp.ClientSession()
        service.client = SimpleNamespace(base=str(upstream.make_url('/')).rstrip('/'))
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            assert len(await service.gallery(force=True)) == 2
            assert (await client.get(remote['url'])).status == 502
            assert len(await service.gallery(force=True)) == 2
            status = 404
            assert (await client.get(remote['url'])).status == 404
            assert [item['id'] for item in await service.gallery(force=True)] == [temporary['id']]
        finally:
            await client.close()
            await service.session.close()
            await upstream.close()
    asyncio.run(scenario())
