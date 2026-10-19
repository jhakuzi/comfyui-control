import asyncio
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtGui import QImage

from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.mobile.server import MobileHTTP


def test_thumbnail_sizes_quality_cache_and_original_metadata(tmp_path):
    async def scenario():
        image = QImage(1024, 1536, QImage.Format.Format_RGB32)
        image.fill(0)
        image.setText('prompt', 'Private metadata must not be in thumbnails')
        path = tmp_path / 'portrait.png'
        assert image.save(str(path))
        original = path.read_bytes()
        service = MobileService(tmp_path / 'data', MobileSettings(), tmp_path)
        item = service.image_ref(dict(filename=path.name))
        http = MobileHTTP(service)
        client = TestClient(TestServer(http.app()))
        await client.start_server()
        await client.get('/api/session')
        try:
            encoded = {}
            for size, dimensions in [(384, (256, 384)), (768, (512, 768)), (1280, (853, 1280))]:
                response = await client.get(item['thumbnail'] + f'&size={size}')
                assert response.status == 200
                encoded[size] = await response.read()
                result = QImage.fromData(encoded[size])
                assert (result.width(), result.height()) == dimensions
                assert all(not result.text(key) for key in result.textKeys())
            assert len(http.thumbnails) == 3
            assert await (await client.get(item['thumbnail'])).read() == encoded[384]
            assert len(http.thumbnails) == 3 and path.read_bytes() == original
            for value in ('0', '-1', '100000', 'abc'):
                assert (await client.get(item['thumbnail'] + '&size=' + value)).status == 400
            service.network_output = True
            service.network_io = AsyncMock(return_value=original)
            http.thumbnails.clear()
            for _ in range(2):
                assert (await client.get(item['thumbnail'] + '&size=768')).status == 200
            service.network_io.assert_awaited_once()
        finally:
            await client.close()
    asyncio.run(scenario())
