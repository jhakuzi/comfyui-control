"""Favourites include older marked versions without expanding the recent Gallery."""
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
        assert await reopened.gallery(BOB, favourites=True) == []
        # A regular refresh must retain the older image's validated reference for
        # the existing image/details/action APIs, without granting delete access.
        await reopened.gallery(BOB, force=True)
        assert reopened.image_action_capabilities(item['id'], ALICE)['kept']
        os.utime(old, ns=(1700000000001000000,) * 2)
        assert await reopened.gallery(ALICE, force=True, favourites=True) == []
        assert old.exists()
    asyncio.run(scenario())


def test_http_favourite_collection_is_private_and_excludes_deleted_versions(tmp_path):
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
            assert await (await bob.get(str(server.make_url('/api/gallery?favourites=1')))).json() == []
            deleted = await alice.post(action, headers=origin,
                json=dict(action='delete', confirm=True, modified=item['modified']))
            assert deleted.status == 200
            assert await (await alice.get('/api/gallery?favourites=1')).json() == []
            entries = await (await alice.get('/api/trash')).json()
            assert len(entries) == 1 and entries[0]['filename'] == 'one.png'
            assert await (await bob.get(str(server.make_url('/api/trash')))).json() == []
            assert (await bob.get(str(server.make_url(entries[0]['thumbnail'])))).status == 404
            response = await alice.get(entries[0]['thumbnail'])
            assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
            assert (tmp_path / 'out/one.png').exists()
        finally:
            await bob.close()
            await alice.close()
    asyncio.run(scenario())
