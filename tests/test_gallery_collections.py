"""Shared device collections retain version, output and authentication boundaries."""
import asyncio
import os

from aiohttp.test_utils import TestClient, TestServer
import pytest

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_actions import ALICE, BOB, picture


@pytest.mark.parametrize('network', [False, True])
def test_old_favourites_survive_restart_recent_scans_and_other_browser_reads(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        old = output / 'old.png'
        picture(old)
        os.utime(old, ns=(1700000000000000000,) * 2)
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        item = (await service.gallery(ALICE))[0]
        await service.image_action(item['id'], ALICE, dict(action='keep', keep=True, modified=item['modified']))
        for number in range(510):
            path = output / f'recent-{number:03}.png'
            picture(path)
            os.utime(path, ns=(1700000001000000000 + number * 1000000000,) * 2)
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        recent = await reopened.gallery(BOB, force=True)
        assert len(recent) == 200 and item['id'] not in {entry['id'] for entry in recent}
        favourites = await reopened.gallery(ALICE, favourites=True)
        assert [entry['id'] for entry in favourites] == [item['id']]
        assert favourites[0]['kept'] and favourites[0]['modified'] == item['modified']
        assert [entry['id'] for entry in await reopened.gallery(BOB, favourites=True)] == [item['id']]
        # A regular refresh must retain the older image's validated reference for
        # the existing image/details/action APIs, without granting delete access.
        await reopened.gallery(BOB, force=True)
        assert reopened.image_action_capabilities(item['id'], ALICE)['kept']
        os.utime(old, ns=(1700000000001000000,) * 2)
        assert await reopened.gallery(ALICE, force=True, favourites=True) == []
        assert old.exists()
    asyncio.run(scenario())


def test_legacy_browser_marks_merge_without_resurrecting_removed_hearts(tmp_path):
    async def scenario():
        from comfyui_control.mobile.image_actions import ImageLibrary, SHARED_LIBRARY_OWNER
        output = tmp_path / 'out'
        for name in ('desktop.png', 'phone.png', 'replaced.png'):
            picture(output / name)
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        items = {item['filename']: item for item in await service.gallery(ALICE)}
        library = service.image_library
        # Persist the exact pre-sharing format, including marks from both devices.
        library.mark(service.output_scope, ALICE, items['desktop.png'], True)
        library.mark(service.output_scope, BOB, items['phone.png'], True)
        library.mark(service.output_scope, ALICE, items['replaced.png'], True)
        stamp = (output / 'replaced.png').stat().st_mtime_ns + 1000000
        os.utime(output / 'replaced.png', ns=(stamp, stamp))
        reopened = MobileService(tmp_path / 'data', MobileSettings(), output)
        favourites = await reopened.gallery(BOB, force=True, favourites=True)
        assert {item['filename'] for item in favourites} == {'desktop.png', 'phone.png'}
        canonical = ImageLibrary.key(reopened.output_scope, SHARED_LIBRARY_OWNER)
        assert len(reopened.image_library.kept[canonical]) == 2
        item = items['desktop.png']
        await reopened.image_action(item['id'], BOB, dict(action='keep', keep=False, modified=item['modified']))
        again = MobileService(tmp_path / 'data', MobileSettings(), output)
        assert [item['filename'] for item in await again.gallery(ALICE, favourites=True)] == ['phone.png']
        assert all((output / name).exists() for name in items)
    asyncio.run(scenario())


def test_authenticated_devices_share_library_but_not_jobs_history_or_live_permissions(tmp_path):
    async def scenario():
        import aiohttp
        import hashlib
        from comfyui_control.mobile.settings import password_hash
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(require_auth=True,
            password=password_hash('fixture-library-password')), tmp_path / 'out')
        server = TestServer(MobileHTTP(service).app())
        alice = TestClient(server)
        await alice.start_server()
        bob = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        anonymous = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        base = str(server.make_url('/'))
        origin = {'Origin': base.rstrip('/')}
        try:
            await alice.get('/api/session')
            await bob.get(base + 'api/session')
            await anonymous.get(base + 'api/session')
            assert (await alice.post('/api/login', headers=origin,
                json={'password': 'fixture-library-password'})).status == 200
            assert (await bob.post(base + 'api/login', headers=origin,
                json={'password': 'fixture-library-password'})).status == 200
            identity = alice.session.cookie_jar.filter_cookies(server.make_url('/'))['mobile_client'].value
            owner = hashlib.sha256(identity.encode()).hexdigest()
            job = dict(id='private-job', owner=owner, status='complete', images=[], created=1)
            service.jobs[job['id']] = job
            job['images'] = [service.image_ref(dict(filename='one.png'), job['id'])]
            service.prompts.record(owner, [dict(key='p', role='positive')], {'p': 'Private fixture prompt'})
            item = (await (await alice.get('/api/gallery')).json())[0]
            action = f'api/images/{item["id"]}/actions'
            assert (await alice.post('/' + action, headers=origin,
                json=dict(action='keep', keep=True, modified=item['modified']))).status == 200
            assert len(await (await bob.get(base + 'api/gallery?favourites=1')).json()) == 1
            assert (await (await bob.get(base + 'api/state')).json())['jobs'] == []
            assert await (await bob.get(base + 'api/prompts')).json() == []
            assert not (await (await bob.get(base + action)).json())['actions']['trash']['available']
            assert (await bob.post(base + 'api/jobs/private-job/cancel', headers=origin,
                json={'confirm_interrupt': True})).status == 400
            deleted = await (await alice.post('/' + action, headers=origin,
                json=dict(action='delete', confirm=True, modified=item['modified']))).json()
            token = deleted['trash']['token']
            assert len(await (await bob.get(base + 'api/trash')).json()) == 1
            assert (await bob.get(base.rstrip('/') + deleted['trash']['thumbnail'])).status == 200
            for path in ['api/gallery?favourites=1', 'api/trash', deleted['trash']['thumbnail'].lstrip('/')]:
                assert (await anonymous.get(base + path)).status == 401
            assert (await anonymous.post(base + 'api/trash/empty', headers=origin,
                json={'confirm': True, 'tokens': [token]})).status == 401
            assert (tmp_path / 'out/one.png').exists()
            result = await bob.post(base + 'api/trash/empty', headers=origin,
                json={'confirm': True, 'tokens': [token]})
            assert result.status == 200 and (await result.json())['results'][0]['deleted']
            assert not (tmp_path / 'out/one.png').exists()
            assert await (await alice.get('/api/trash')).json() == []
            assert (await (await bob.get(base + 'api/state')).json())['jobs'] == []
        finally:
            await anonymous.close()
            await bob.close()
            await alice.close()
    asyncio.run(scenario())


def test_shared_bin_keeps_original_when_source_ownership_changes(tmp_path):
    async def scenario():
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        service.jobs['original'] = dict(id='original', owner=ALICE, status='complete', images=[], created=1)
        item = service.image_ref(dict(filename='one.png'), 'original')
        item = (await service.gallery(ALICE))[0]
        deleted = await service.image_action(item['id'], ALICE,
            dict(action='delete', confirm=True, modified=item['modified']))
        service.jobs['original']['owner'] = BOB
        result = await service.delete_permanently(BOB,
            dict(confirm=True, tokens=[deleted['trash']['token']]))
        assert 'ownership changed' in result['results'][0]['error']
        assert (tmp_path / 'out/one.png').exists()
        assert len(await service.image_trash(ALICE)) == len(await service.image_trash(BOB)) == 1
    asyncio.run(scenario())


def test_http_favourite_collection_is_shared_and_excludes_deleted_versions(tmp_path):
    async def scenario():
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path / 'out')
        server = TestServer(MobileHTTP(service).app())
        alice, bob = TestClient(server), None
        await alice.start_server()
        # Separate clients need separate cookie jars, not separate applications.
        import aiohttp
        bob = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        try:
            await alice.get('/api/session')
            await bob.get(str(server.make_url('/api/session')))
            origin = {'Origin': str(server.make_url('/')).rstrip('/')}
            item = (await (await alice.get('/api/gallery')).json())[0]
            action = f'/api/images/{item["id"]}/actions'
            response = await alice.post(action, headers=origin,
                json=dict(action='keep', keep=True, modified=item['modified']))
            assert response.status == 200
            favourites = await (await alice.get('/api/gallery?favourites=1&refresh=1')).json()
            assert len(favourites) == 1 and favourites[0]['kept']
            assert len(await (await bob.get(str(server.make_url('/api/gallery?favourites=1')))).json()) == 1
            deleted = await alice.post(action, headers=origin,
                json=dict(action='delete', confirm=True, modified=item['modified']))
            assert deleted.status == 200
            assert await (await alice.get('/api/gallery?favourites=1')).json() == []
            entries = await (await alice.get('/api/trash')).json()
            assert len(entries) == 1 and entries[0]['filename'] == 'one.png'
            assert len(await (await bob.get(str(server.make_url('/api/trash')))).json()) == 1
            assert (await bob.get(str(server.make_url(entries[0]['thumbnail'])))).status == 200
            response = await alice.get(entries[0]['thumbnail'])
            assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
            assert (tmp_path / 'out/one.png').exists()
        finally:
            await bob.close()
            await alice.close()
    asyncio.run(scenario())
