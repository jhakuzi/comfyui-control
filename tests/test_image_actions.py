"""Image actions target a saved file/version; job and workflow state stay intact."""
import asyncio
from copy import deepcopy
import os
import json
import errno

from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage
import pytest

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.network_output import image_library, scan, virtual_image
from comfyui_control.mobile.image_actions import ImageLibrary

ALICE, BOB = 'a' * 64, 'b' * 64


def picture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(24, 32, QImage.Format.Format_RGB32)
    image.fill(0xff446688)
    assert image.save(str(path))


def test_keep_is_shared_by_devices_but_version_and_output_scoped_and_leaves_jobs_private(tmp_path):
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
        assert next(item for item in await service.gallery(BOB) if item['id'] == old['id'])['kept']
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
def test_delete_is_virtual_persistent_and_restore_never_touches_images(tmp_path, network):
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
        assert (output / 'nested' / 'old.png').read_bytes() == original
        assert not (output / '.comfyui-control-trash').exists()
        assert [item['filename'] for item in await service.gallery(ALICE, force=True)] == ['latest.png']
        assert not service.image_ref(dict(filename='image.png', subfolder='.comfyui-control-trash/anything'))
        assert [entry['filename'] for entry in await service.image_trash(BOB)] == ['old.png']
        assert image_library(output, 'trash-list', dict(owner=ALICE, scope='different-output')) == []
        assert await service.wastebin_thumbnail(BOB, result['trash']['token'])
        restarted = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        assert len(await restarted.image_trash(ALICE)) == 1
        assert [item['filename'] for item in await restarted.gallery(ALICE, force=True)] == ['latest.png']
        assert [item['filename'] for item in await restarted.gallery(BOB, force=True)] == ['latest.png']
        # Restore is a local metadata operation even with a disconnected NAS.
        async def offline(*args, **kwargs):
            raise OSError('NAS offline')
        original_io = restarted.network_io
        restarted.network_io = offline
        await restarted.image_trash(BOB, result['trash']['token'])
        assert (output / 'nested' / 'old.png').read_bytes() == original
        restarted.network_io = original_io
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
            thumbnail = await client.get(entries[0]['thumbnail'])
            assert thumbnail.status == 200 and thumbnail.content_type == 'image/jpeg'
            assert (await client.post('/api/trash/empty', headers=headers, json={'tokens': [entries[0]['token']]})).status == 400
            assert (await client.post('/api/trash/' + result['trash']['token'] + '/restore', headers=headers,
                                      json={'confirm': True})).status == 200
            assert len(await (await client.get('/api/gallery?refresh=1')).json()) == 1
        finally:
            await client.close()
    asyncio.run(scenario())


async def delete_image(service, filename, owner=ALICE):
    item = next(item for item in await service.gallery(owner, force=True) if item['filename'] == filename)
    result = await service.image_action(item['id'], owner, dict(action='delete', confirm=True, modified=item['modified']))
    return result['trash']['token']


@pytest.mark.parametrize('network', [False, True])
def test_permanent_delete_requires_confirmation_and_preserves_other_files(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'nested' / 'one.png')
        picture(output / 'other.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        token = await delete_image(service, 'one.png')
        for body in ({}, {'confirm': 'yes'}):
            with pytest.raises(ValueError, match='confirm'):
                await service.delete_permanently(ALICE, body, token)
        with pytest.raises(ValueError, match='no longer available'):
            await service.delete_permanently(BOB, {'confirm': True}, 'f' * 32)
        assert (output / 'nested' / 'one.png').is_file()
        result = await service.delete_permanently(BOB, {'confirm': True}, token)
        assert result == {'results': [{'token': token, 'deleted': True}]}
        assert not (output / 'nested' / 'one.png').exists()
        assert (output / 'other.png').is_file()
        assert await service.image_trash(ALICE) == []
        # A retry may not delete a new file at the original path.
        picture(output / 'nested' / 'one.png')
        with pytest.raises(ValueError, match='no longer available'):
            await service.delete_permanently(ALICE, {'confirm': True}, token)
        assert (output / 'nested' / 'one.png').is_file()
    asyncio.run(scenario())


@pytest.mark.parametrize('network', [False, True])
def test_clear_bin_completes_confirmed_missing_original_without_unlinking_replacements(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        path = output / 'nested' / 'gone.png'
        picture(path)
        picture(output / 'unselected.png')
        untouched = (output / 'unselected.png').read_bytes()
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        service.network_output = network
        token = await delete_image(service, 'gone.png')
        path.unlink()  # Removed outside the app, or an earlier unlink lost its reply.
        assert len(await service.image_trash(BOB)) == 1
        result = await service.delete_permanently(BOB, dict(confirm=True, tokens=[token]))
        assert result['results'] == [dict(token=token, deleted=True)]
        assert await service.image_trash(ALICE) == []
        picture(path)  # A future file at the same name is outside this tombstone.
        with pytest.raises(ValueError):
            await service.delete_permanently(ALICE, dict(confirm=True, tokens=[token]))
        assert path.is_file() and (output / 'unselected.png').read_bytes() == untouched
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        assert await reopened.image_trash(BOB) == []
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['nfs', 'nfs4'])
@pytest.mark.parametrize('subfolder', ['', 'nested'])
def test_missing_original_after_nfs_device_renumber_only_completes_metadata(tmp_path, monkeypatch, kind, subfolder):
    from comfyui_control import network_output
    root = tmp_path / 'out'
    path = root / subfolder / 'gone.png'
    picture(path)
    descriptor = dict(filename=path.name, subfolder=subfolder, type='output', modified=str(path.stat().st_mtime_ns))
    identity = virtual_image(root, 'identify', dict(image=descriptor))
    for directory in identity['directories']:
        directory[0] += 1  # Saved st_dev from before an NFS remount.
    identity['file'][0] += 1
    path.unlink()
    monkeypatch.setattr(network_output, 'mount_record', lambda where: (kind, 'fixture:/output'))
    monkeypatch.setattr(network_output.os, 'unlink', lambda *a, **k: pytest.fail('Missing-file cleanup must never unlink'))
    assert virtual_image(root, 'delete', dict(image=descriptor, identity=identity)) == dict(ok=True, missing=True)
    with pytest.raises(FileNotFoundError):
        virtual_image(root, 'wastebin-read', dict(image=descriptor, identity=identity))


@pytest.mark.parametrize('failure', ['unmounted', 'autofs', 'local', 'parent-inode', 'root-inode',
                                     'nested-device', 'bad-identity', 'changed-mount', 'existing-file'])
def test_nfs_missing_cleanup_keeps_storage_and_existing_file_guards(tmp_path, monkeypatch, failure):
    from comfyui_control import network_output
    root = tmp_path / 'out'
    path = root / 'nested' / 'one.png'
    picture(path)
    descriptor = dict(filename=path.name, subfolder='nested', type='output', modified=str(path.stat().st_mtime_ns))
    identity = virtual_image(root, 'identify', dict(image=descriptor))
    for directory in identity['directories']:
        directory[0] += 1
    identity['file'][0] += 1
    if failure != 'existing-file':
        path.unlink()
    kind = {'unmounted': None, 'autofs': ('autofs', 'systemd-1'), 'local': ('ext4', '/dev/fixture')}.get(
        failure, ('nfs4', 'fixture:/output'))
    if failure == 'parent-inode': identity['directories'][-1][1] += 1
    if failure == 'root-inode': identity['directories'][0][1] += 1
    if failure == 'nested-device': identity['directories'][-1][0] += 1
    if failure == 'bad-identity': identity['directories'] = [['invalid']]
    calls = []
    def mounted(where):
        calls.append(where)
        return ('nfs4', 'different:/export') if failure == 'changed-mount' and len(calls) > 1 else kind
    monkeypatch.setattr(network_output, 'mount_record', mounted)
    monkeypatch.setattr(network_output.os, 'unlink', lambda *a, **k: pytest.fail('Must not unlink a changed file/location'))
    with pytest.raises(ValueError, match='changed'):
        virtual_image(root, 'delete', dict(image=descriptor, identity=identity))
    if failure == 'existing-file': assert path.is_file()


@pytest.mark.parametrize('failure', ['replacement', 'symlink', 'parent', 'root', 'missing-parent', 'missing-root'])
def test_permanent_delete_rejects_changed_files_or_locations(tmp_path, failure):
    async def scenario():
        output = tmp_path / 'out'
        path = output / 'nested' / 'one.png'
        picture(path)
        picture(tmp_path / 'outside.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        token = await delete_image(service, 'one.png')
        info = path.stat()
        if failure == 'replacement':
            picture(output / 'replacement.png')
            os.replace(output / 'replacement.png', path)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        elif failure == 'symlink':
            path.unlink()
            path.symlink_to(tmp_path / 'outside.png')
        elif failure == 'parent':
            path.parent.rename(output / 'moved')
            path.parent.mkdir()
            picture(path)
        elif failure == 'root':
            output.rename(tmp_path / 'unmounted')
            picture(path)
        elif failure == 'missing-parent':
            path.unlink()
            path.parent.rmdir()
        else:
            output.rename(tmp_path / 'missing-root')
        result = await service.delete_permanently(ALICE, {'confirm': True}, token)
        assert result['results'][0]['error']
        assert (tmp_path / 'outside.png').is_file()
        if failure not in {'missing-parent', 'missing-root'}:
            assert path.exists()
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        entries = await reopened.image_trash(ALICE)
        assert len(entries) == 1 and entries[0]['error']
        await reopened.image_trash(ALICE, token)  # Metadata restore does not overwrite anything.
        assert await reopened.image_trash(ALICE) == []
    asyncio.run(scenario())


def test_empty_wastebin_partial_failure_snapshot_and_shared_output_scope(tmp_path, monkeypatch):
    async def scenario():
        output = tmp_path / 'out'
        for name in ('one.png', 'two.png', 'later.png', 'bob.png', 'normal.png'):
            picture(output / name)
        service = MobileService(tmp_path / 'data', MobileSettings(share_image_settings=True), output)
        first = await delete_image(service, 'one.png')
        failed = await delete_image(service, 'two.png')
        bob = await delete_image(service, 'bob.png', BOB)
        later = await delete_image(service, 'later.png')
        # Authorize the whole bulk request before deleting even its first entry.
        with pytest.raises(ValueError, match='no longer available'):
            await service.delete_permanently(ALICE, dict(confirm=True, tokens=[first, 'f' * 32]))
        assert (output / 'one.png').exists()
        original_io = service.network_io
        async def failed_io(operation, data, **kwargs):
            if operation == 'delete' and data['token'] == failed:
                raise OSError(errno.EROFS, 'NFS export is read-only')
            return await original_io(operation, data, **kwargs)
        monkeypatch.setattr(service, 'network_io', failed_io)
        result = await service.delete_permanently(ALICE, dict(confirm=True, tokens=[first, failed]))
        assert result['results'][0]['deleted']
        assert 'read-only' in result['results'][1]['error']
        assert not (output / 'one.png').exists()
        assert all((output / name).exists() for name in ('two.png', 'bob.png', 'later.png', 'normal.png'))
        assert {entry['token'] for entry in await service.image_trash(ALICE)} == {failed, later, bob}
        assert {entry['token'] for entry in await service.image_trash(BOB)} == {failed, later, bob}
        monkeypatch.setattr(service, 'network_io', original_io)
        result = await service.delete_permanently(BOB, dict(confirm=True, tokens=[failed, later]))
        assert all(entry['deleted'] for entry in result['results'])
        assert [entry['token'] for entry in await service.image_trash(ALICE)] == [bob]
        assert (output / 'bob.png').is_file()
    asyncio.run(scenario())


def test_nas_timeout_keeps_markers_and_does_not_retry_remaining_files(tmp_path, monkeypatch):
    async def scenario():
        output = tmp_path / 'nas'
        picture(output / 'one.png')
        picture(output / 'two.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=True)
        tokens = [await delete_image(service, name) for name in ('one.png', 'two.png')]
        calls = []
        async def offline(operation, data, **kwargs):
            calls.append(operation)
            raise TimeoutError('NFS server offline')
        monkeypatch.setattr(service, 'network_io', offline)
        result = await service.delete_permanently(ALICE, dict(confirm=True, tokens=tokens))
        assert calls == ['delete']
        assert all(entry['error'] for entry in result['results'])
        entries = await service.image_trash(ALICE)
        assert len(entries) == 2 and all(entry['error'] for entry in entries)
        for token in tokens:
            await service.image_trash(ALICE, token)
        assert all((output / name).is_file() for name in ('one.png', 'two.png'))
    asyncio.run(scenario())


def test_worker_rejects_paths_outside_output_and_managed_nfs_mount_is_required(tmp_path):
    from comfyui_control import network_output
    picture(tmp_path / 'outside.png')
    root = tmp_path / 'out'
    root.mkdir()
    for descriptor in (dict(filename='../outside.png'), dict(filename='outside.png', subfolder='..'),
                       dict(filename='outside.png', subfolder=str(tmp_path)), dict(filename='outside.png', type='temp')):
        with pytest.raises(ValueError, match='location'):
            virtual_image(root, 'delete', {'image': descriptor})
    (root / 'linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        virtual_image(root, 'identify', {'image': dict(filename='outside.png', subfolder='linked')})
    # Exercise the same CLI mount guard used before network worker operations.
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-I', network_output.__file__, 'delete', '/mnt/comfyui-nfs-0123456789abcdef'],
                            input=json.dumps({'image': dict(filename='outside.png')}), capture_output=True, text=True)
    assert result.returncode == 1 and 'not mounted' in result.stdout
    assert (tmp_path / 'outside.png').exists()


def test_favourites_migrate_without_loss_and_corrupt_metadata_fails_closed(tmp_path):
    path = tmp_path / 'image-library.json'
    legacy = {'a' * 64: {'image': '1234'}}
    path.write_text(json.dumps(legacy))
    library = ImageLibrary(path)
    assert library.valid and library.kept == legacy
    library.delete('scope', ALICE, dict(id='image', modified='1234'), {})
    reopened = ImageLibrary(path)
    assert reopened.kept == legacy and len(reopened.deleted) == 1
    path.write_text('{broken')
    damaged = ImageLibrary(path)
    with pytest.raises(ValueError, match='Back it up'):
        damaged.delete('scope', ALICE, dict(id='image'), {})
    assert path.read_text() == '{broken'


def test_legacy_moved_trash_can_still_restore_or_delete_permanently(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'one.png')
        picture(output / 'two.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        for item in await service.gallery(ALICE):
            image_library(output, 'trash', dict(image=item, owner=ALICE, scope=service.output_scope, modified=item['modified']))
        entries = await service.image_trash(BOB)
        assert len(entries) == 2
        assert await service.wastebin_thumbnail(BOB, entries[0]['token'])
        await service.image_trash(BOB, entries[0]['token'])
        result = await service.delete_permanently(BOB, dict(confirm=True), entries[1]['token'])
        assert result['results'][0]['deleted']
        assert (output / entries[0]['filename']).is_file()
        assert not (output / entries[1]['filename']).exists()
    asyncio.run(scenario())


def test_http_permanent_delete_confirmation_and_output_scope_with_shared_thumbnails(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        server = TestServer(MobileHTTP(service).app())
        alice, bob = TestClient(server), None
        await alice.start_server()
        # Independent cookie jars against one server.
        from aiohttp import ClientSession, CookieJar
        bob = ClientSession(cookie_jar=CookieJar(unsafe=True))
        try:
            await alice.get('/api/session')
            await bob.get(server.make_url('/api/session'))
            origin = {'Origin': str(server.make_url('/')).rstrip('/')}
            item = (await (await alice.get('/api/gallery')).json())[0]
            deleted = await (await alice.post('/api/images/' + item['id'] + '/actions', headers=origin,
                json=dict(action='delete', confirm=True, modified=item['modified'], filename='/etc/passwd'))).json()
            token = deleted['trash']['token']
            assert len(await (await bob.get(server.make_url('/api/trash'))).json()) == 1
            assert (await bob.get(server.make_url(deleted['trash']['thumbnail']))).status == 200
            assert (await bob.post(server.make_url('/api/trash/' + token + '/delete'), headers=origin,
                                   json={})).status == 400
            assert (await alice.post('/api/trash/' + token + '/delete', json={'confirm': True})).status == 403
            assert (await alice.post('/api/trash/' + token + '/delete', headers=origin, json={})).status == 400
            other = tmp_path / 'other'
            picture(other / 'one.png')
            service.change_output(other)
            assert (await alice.post('/api/trash/' + token + '/delete', headers=origin,
                                     json={'confirm': True})).status == 400
            assert (output / 'one.png').is_file() and (other / 'one.png').is_file()
            service.change_output(output)
            result = await bob.post(server.make_url('/api/trash/' + token + '/delete'), headers=origin, json={'confirm': True})
            assert result.status == 200 and (await result.json())['results'][0]['deleted']
            assert not (output / 'one.png').exists() and (other / 'one.png').is_file()
            assert (await alice.get(deleted['trash']['thumbnail'])).status == 404
        finally:
            await bob.close()
            await alice.close()
    asyncio.run(scenario())
