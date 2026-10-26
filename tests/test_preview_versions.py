"""Preview results must distinguish new files from tombstones at reused paths."""
import asyncio
from copy import deepcopy
import os
import uuid

import pytest
from aiohttp.test_utils import TestServer

from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings
from test_image_actions import ALICE, picture
from test_mobile_integration import ComfyStub, until


@pytest.mark.parametrize('network', [False, True])
@pytest.mark.parametrize('purge', [False, True])
def test_new_output_at_deleted_filename_appears_in_job_before_gallery_is_opened(tmp_path, network, purge):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'reused.png')
        graph = {'text': dict(class_type='Text', inputs={'text': 'fixture'})}
        stub = ComfyStub(graph)
        upstream = TestServer(stub.app())
        await upstream.start_server()
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), output, network_output=network)
        try:
            service.jobs['earlier'] = dict(id='earlier', owner=ALICE, status='complete', created=1, images=[])
            service.jobs['earlier']['images'] = [deepcopy(service.image_ref(dict(filename='reused.png'), 'earlier'))]
            old = (await service.gallery(ALICE))[0]
            deleted = await service.image_action(old['id'], ALICE, dict(action='trash', confirm=True, modified=old['modified']))
            if purge:
                assert (await service.delete_permanently(ALICE, dict(confirm=True,tokens=[deleted['trash']['token']])))['results'][0]['deleted']
            picture(output / 'reused.png')
            fresh = str(int(old['modified']) + 100000000)
            os.utime(output / 'reused.png', ns=(int(fresh), int(fresh)))
            await service.start()
            await until(lambda: service.online)
            preset = service.presets.create('Version fixture', graph)
            request = dict(request_id=str(uuid.uuid4()), preset=preset['id'], revision=revision(preset), values={})
            job = await service.submit(request, ALICE)
            entry = stub.pending.pop()
            stub.history[job['prompt_id']] = dict(prompt=entry, outputs={'save': {'images':[dict(filename='reused.png',subfolder='',type='output')]}},status=dict(status_str='success'))
            await service.refresh()
            public = service.state(owner=ALICE)['jobs'][-1]
            assert public['status'] == 'complete'
            assert len(public['images']) == 1, 'New result was hidden by the old filename tombstone'
            assert public['images'][0]['modified'] == fresh
            assert '?v='+fresh in public['images'][0]['url']
            assert service.state(owner=ALICE, include_details=False)['jobs'][-1]['image_count'] == 1
            assert service.public_job(service.jobs['earlier'])['images'] == []
            reopened = MobileService(tmp_path / 'data', service.settings, output, network_output=network)
            assert len(reopened.state(owner=ALICE)['jobs'][-1]['images']) == 1
            assert reopened.public_job(reopened.jobs['earlier'])['images'] == []
            assert (output / 'reused.png').is_file()
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('condition', ['unchanged', 'missing', 'symlink', 'offline'])
def test_version_resolution_never_revives_deleted_or_unverified_files(tmp_path, condition):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'reused.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=True)
        service.jobs['old'] = dict(id='old',owner=ALICE,status='complete',created=1,images=[])
        service.jobs['old']['images'] = [deepcopy(service.image_ref(dict(filename='reused.png'), 'old'))]
        old = (await service.gallery(ALICE))[0]
        result = await service.image_action(old['id'], ALICE, dict(action='trash',confirm=True,modified=old['modified']))
        if condition in {'missing', 'symlink'}:
            await service.delete_permanently(ALICE, dict(confirm=True,tokens=[result['trash']['token']]))
        if condition == 'symlink':
            picture(tmp_path / 'outside.png')
            (output / 'reused.png').symlink_to(tmp_path / 'outside.png')
        if condition == 'offline':
            async def offline(*args, **kwargs): raise TimeoutError('Fixture storage timeout')
            service.network_io = offline
        service.jobs['new'] = dict(id='new',owner=ALICE,status='complete',created=2,images=[])
        service.jobs['new']['images'] = [service.image_ref(dict(filename='reused.png'), 'new')]
        await service.resolve_output_versions()
        assert service.public_job(service.jobs['old'])['images'] == []
        assert service.public_job(service.jobs['new'])['images'] == []
        if condition == 'symlink':
            assert (tmp_path / 'outside.png').is_file() and (output / 'reused.png').is_symlink()
    asyncio.run(scenario())


def test_reused_path_never_inherits_previous_jobs_timestamp(tmp_path):
    service=MobileService(tmp_path/'data',MobileSettings(),tmp_path/'out')
    service.jobs['old']=dict(id='old',status='complete',images=[],created=1)
    old=service.image_ref(dict(filename='reused.png'),'old')
    old.update(modified='123',created=1)
    service.jobs['old']['images']=[deepcopy(old)]
    service.jobs['new']=dict(id='new',status='complete',images=[],created=2)
    new=service.image_ref(dict(filename='reused.png'),'new')
    assert new['id']==old['id'] and not new.get('modified')
    assert new['url']!=old['url'] and 'v=job-new' in new['url']
    assert service.image_ref(dict(filename='reused.png'),'old')['modified']=='123'


def test_unversioned_network_thumbnails_are_separate_for_different_generations(tmp_path):
    from aiohttp.test_utils import TestClient
    from PySide6.QtGui import QImage
    from comfyui_control.mobile.server import MobileHTTP
    async def scenario():
        output=tmp_path/'out'
        picture(output/'reused.png')
        service=MobileService(tmp_path/'data',MobileSettings(),output,network_output=True)
        service.jobs['old']=dict(id='old',status='complete',owner=ALICE,images=[],created=1)
        old=service.image_ref(dict(filename='reused.png'),'old')
        client=TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            first=QImage.fromData(await (await client.get(old['thumbnail'])).read())
            image=QImage(24,32,QImage.Format.Format_RGB32)
            image.fill(0xffee8822)
            assert image.save(str(output/'reused.png'))
            service.jobs['new']=dict(id='new',status='complete',owner=ALICE,images=[],created=2)
            new=service.image_ref(dict(filename='reused.png'),'new')
            second=QImage.fromData(await (await client.get(new['thumbnail'])).read())
            assert not first.isNull() and not second.isNull() and first!=second
            assert second.pixelColor(0,0).red()>200
        finally: await client.close()
    asyncio.run(scenario())
