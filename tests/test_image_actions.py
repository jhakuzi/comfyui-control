"""Image actions target a saved file/version; job and workflow state stay intact."""
import asyncio
from copy import deepcopy
import os

from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage
import pytest

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.network_output import image_library, scan

ALICE, BOB = 'a' * 64, 'b' * 64


def picture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(24, 32, QImage.Format.Format_RGB32)
    image.fill(0xff446688)
    assert image.save(str(path))


def test_keep_is_per_browser_version_and_output_and_does_not_change_jobs(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'old.png')
        picture(output / 'new.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        service.jobs['job'] = {'id': 'job', 'owner': ALICE, 'status': 'complete', 'images': [], 'created': 1}
        saved_jobs = deepcopy(service.jobs)
        images = await service.gallery(ALICE)
        old = next(item for item in images if item['filename'] == 'old.png')
        contents = (output / 'old.png').read_bytes()
        await service.image_action(old['id'], ALICE, dict(action='keep', keep=True, modified=old['modified']))
        assert next(item for item in await service.gallery(ALICE) if item['id'] == old['id'])['kept']
        assert not any(item['kept'] for item in await service.gallery(BOB))
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        assert next(item for item in await reopened.gallery(ALICE) if item['id'] == old['id'])['kept']
        stamp = (output / 'old.png').stat().st_mtime_ns + 1000000
        os.utime(output / 'old.png', ns=(stamp, stamp))
        assert not any(item['kept'] for item in await service.gallery(ALICE, force=True))
        with pytest.raises(ValueError, match='changed'):
            await service.image_action(old['id'], ALICE, dict(action='keep', keep=False, modified=old['modified']))
        assert service.jobs == saved_jobs and (output / 'old.png').read_bytes() == contents
        other = tmp_path / 'other'
        picture(other / 'old.png')
        service.change_output(other)
        assert not any(item['kept'] for item in await service.gallery(ALICE))
    asyncio.run(scenario())


@pytest.mark.parametrize('network', [False, True])
def test_trash_is_recoverable_and_never_overwrites_or_mutates_other_images(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'nested' / 'old.png')
        picture(output / 'latest.png')
        original = (output / 'nested' / 'old.png').read_bytes()
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        old = next(item for item in await service.gallery(ALICE) if item['filename'] == 'old.png')
        with pytest.raises(ValueError, match='Confirm'):
            await service.image_action(old['id'], ALICE, dict(action='trash', modified=old['modified']))
        result = await service.image_action(old['id'], ALICE, dict(action='trash', confirm=True, modified=old['modified']))
        assert not (output / 'nested' / 'old.png').exists()
        assert [item['filename'] for item in await service.gallery(ALICE, force=True)] == ['latest.png']
        assert not service.image_ref(dict(filename='image.png', subfolder='.comfyui-control-trash/anything'))
        assert await service.image_trash(BOB) == []
        assert image_library(output, 'trash-list', dict(owner=ALICE, scope='different-output')) == []
        with pytest.raises(ValueError, match='another browser'):
            await service.image_trash(BOB, result['trash']['token'])
        restarted = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        assert len(await restarted.image_trash(ALICE)) == 1
        picture(output / 'nested' / 'old.png')
        replacement = (output / 'nested' / 'old.png').read_bytes()
        with pytest.raises(ValueError, match='already exists'):
            await restarted.image_trash(ALICE, result['trash']['token'])
        assert (output / 'nested' / 'old.png').read_bytes() == replacement
        (output / 'nested' / 'old.png').unlink()
        await restarted.image_trash(ALICE, result['trash']['token'])
        assert (output / 'nested' / 'old.png').read_bytes() == original
        assert await restarted.image_trash(ALICE) == []
        assert len(await restarted.gallery(ALICE, force=True)) == 2
    asyncio.run(scenario())


def test_trashed_outputs_disappear_from_public_jobs_without_changing_journal(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        service.jobs['job'] = dict(id='job', owner=ALICE, status='complete', images=[], created=1, seconds_per_iteration=None)
        ref = service.image_ref(dict(filename='one.png'), 'job')
        service.jobs['job']['images'] = [deepcopy(ref)]
        service.persist()
        original = deepcopy(service.jobs)
        item = (await service.gallery(ALICE))[0]
        result = await service.image_action(item['id'], ALICE, dict(action='trash', confirm=True, modified=item['modified']))
        assert service.jobs == original
        assert service.state(owner=ALICE)['jobs'][0]['images'] == []
        assert service.state(owner=ALICE, include_details=False)['jobs'][0]['image_count'] == 0
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        await reopened.gallery(ALICE)
        assert reopened.state(owner=ALICE)['jobs'][0]['images'] == []
        await reopened.image_trash(ALICE, result['trash']['token'])
        await reopened.gallery(ALICE, force=True)
        assert len(reopened.state(owner=ALICE)['jobs'][0]['images']) == 1
        assert reopened.jobs == original
    asyncio.run(scenario())


def test_workflow_actions_are_honestly_unavailable_and_sharing_does_not_grant_trash(tmp_path):
    async def scenario():
        picture(tmp_path / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(share_image_settings=True), tmp_path)
        service.jobs['job'] = {'id': 'job', 'owner': ALICE}
        item = service.image_ref(dict(filename='one.png'), 'job')
        item = (await service.gallery(ALICE))[0]
        caps = service.image_action_capabilities(item['id'], BOB)
        assert caps['actions']['keep']['available']
        assert not caps['actions']['trash']['available']
        for action in ('edit', 'upscale'):
            assert not caps['actions'][action]['available']
            with pytest.raises(ValueError, match='not configured'):
                await service.image_action(item['id'], ALICE, dict(action=action, modified=item['modified']))
        with pytest.raises(ValueError, match='Only the browser'):
            await service.image_action(item['id'], BOB, dict(action='trash', confirm=True, modified=item['modified']))
        assert (tmp_path / 'one.png').exists()
    asyncio.run(scenario())


def test_worker_rejects_stale_files_symlink_components_and_restore_escape(tmp_path):
    picture(tmp_path / 'out' / 'one.png')
    root = tmp_path / 'out'
    descriptor = dict(filename='one.png', subfolder='', type='output')
    data = dict(owner=ALICE, scope='scope', image=descriptor, modified='wrong')
    with pytest.raises(ValueError, match='changed'):
        image_library(root, 'trash', data)
    (root / 'linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(FileNotFoundError):
        image_library(root, 'trash', {**data, 'image': dict(filename='outside.png', subfolder='linked')})
    data['modified'] = str((root / 'one.png').stat().st_mtime_ns)
    result = image_library(root, 'trash', data)
    assert scan(root, [])['found'] == []
    (root / 'one.png').symlink_to(tmp_path / 'outside.png')
    with pytest.raises(ValueError, match='already exists'):
        image_library(root, 'restore', dict(owner=ALICE, scope='scope', token=result['token']))
    with pytest.raises(ValueError, match='Invalid trash'):
        image_library(root, 'restore', dict(owner=ALICE, scope='scope', token='../elsewhere'))


def test_http_action_validation_session_isolation_and_deleted_image_access(tmp_path):
    async def scenario():
        picture(tmp_path / 'out' / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            headers = {'Origin': str(client.make_url('/')).rstrip('/')}
            item = (await (await client.get('/api/gallery')).json())[0]
            url = '/api/images/' + item['id'] + '/actions'
            assert (await client.post(url, json={'action': 'trash'})).status == 403
            caps = await (await client.get(url)).json()
            assert caps['image_id'] == item['id'] and caps['actions']['trash']['available']
            assert (await client.post(url, headers=headers, json={'action': 'unknown'})).status == 400
            assert (await client.post(url, headers=headers, json={'action': 'keep', 'keep': 'yes', 'modified': item['modified']})).status == 400
            result = await (await client.post(url, headers=headers,
                json={'action': 'trash', 'confirm': True, 'modified': item['modified']})).json()
            assert (await client.get(item['thumbnail'])).status == 404
            assert await (await client.get('/api/gallery')).json() == []
            entries = await (await client.get('/api/trash')).json()
            assert len(entries) == 1 and 'owner' not in entries[0] and 'scope' not in entries[0]
            assert (await client.post('/api/trash/' + result['trash']['token'] + '/restore', headers=headers,
                                      json={'confirm': True})).status == 200
            assert len(await (await client.get('/api/gallery?refresh=1')).json()) == 1
        finally:
            await client.close()
    asyncio.run(scenario())
