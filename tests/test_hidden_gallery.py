"""Hidden-folder visibility is per request and does not change stored image state."""
import asyncio
import os

import pytest
from aiohttp.test_utils import TestClient, TestServer

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_actions import ALICE, BOB, picture


@pytest.mark.parametrize('network', [False, True])
def test_gallery_filters_nested_dot_folders_without_mutating_shared_images(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        names = ['public.png', 'visible/.private/deep.png', '.private/hidden.png', '.file.png', 'normal/image.png']
        for name in names:
            picture(output / name)
        picture(output / '.comfyui-control-trash/never-visible.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        all_images = await service.gallery(ALICE)
        assert len(all_images) == 5
        hidden = next(i for i in all_images if i['filename'] == 'hidden.png')
        await service.image_action(hidden['id'], ALICE, dict(action='keep', keep=True, modified=hidden['modified']))
        visible = await service.gallery(ALICE, include_hidden=False)
        assert {i['filename'] for i in visible} == {'public.png', '.file.png', 'image.png'}
        assert {i['id'] for i in await service.gallery(BOB)} == {i['id'] for i in all_images}
        assert await service.gallery(ALICE, favourites=True, include_hidden=False) == []
        assert [i['id'] for i in await service.gallery(BOB, favourites=True)] == [hidden['id']]
        assert hidden['id'] in service.images and not service.unavailable_images
        assert all((output / name).is_file() for name in names)
    asyncio.run(scenario())


@pytest.mark.parametrize('network', [False, True])
def test_visible_page_is_filled_even_when_newest_200_images_are_in_hidden_folders(tmp_path, network):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'visible.png')
        os.utime(output / 'visible.png', ns=(1700000000000000000,) * 2)
        for index in range(510):
            path = output / '.hidden' / f'{index:03}.png'
            picture(path)
            os.utime(path, ns=(1700000001000000000 + index * 1000000,) * 2)
        service = MobileService(tmp_path / 'data', MobileSettings(), output, network_output=network)
        assert len(await service.gallery(ALICE)) == 200
        assert [i['filename'] for i in await service.gallery(ALICE, include_hidden=False)] == ['visible.png']
        assert len(await service.gallery(BOB)) == 200
    asyncio.run(scenario())


def test_http_filter_has_independent_revisions_and_validates_query(tmp_path):
    async def scenario():
        output = tmp_path / 'out'
        picture(output / 'visible.png')
        picture(output / '.hidden/hidden.png')
        service = MobileService(tmp_path / 'data', MobileSettings(), output)
        client = TestClient(TestServer(MobileHTTP(service).app()))
        await client.start_server()
        try:
            await client.get('/api/session')
            visible = await (await client.get('/api/gallery?include_hidden=0&since=')).json()
            assert len(visible['images']) == 1
            all_images = await (await client.get('/api/gallery?include_hidden=1&since=' + visible['revision'])).json()
            assert len(all_images['images']) == 2 and all_images['revision'] != visible['revision']
            same = await (await client.get('/api/gallery?include_hidden=0&since=' + visible['revision'])).json()
            assert same['images'] is None
            assert len(await (await client.get('/api/gallery')).json()) == 2
            assert (await client.get('/api/gallery?include_hidden=invalid')).status == 400
        finally:
            await client.close()
    asyncio.run(scenario())
