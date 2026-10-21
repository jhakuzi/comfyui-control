"""Presentation shell assets remain public while application data stays private."""
import asyncio
from html.parser import HTMLParser
import re

from aiohttp.test_utils import TestClient, TestServer

from comfyui_control.mobile.server import MobileHTTP
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings


class ShellAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles, self.scripts = [], []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.styles.append(attrs['href'])
        elif tag == 'script' and 'src' in attrs:
            self.scripts.append(attrs['src'])


def test_presentation_assets_boot_without_auth_and_are_in_offline_shell(tmp_path):
    async def scenario():
        service = MobileService(tmp_path / 'state', MobileSettings(require_auth=True), tmp_path / 'out')
        async with TestClient(TestServer(MobileHTTP(service).app())) as client:
            shell = await client.get('/')
            assert shell.status == 200
            assets = ShellAssets()
            assets.feed(await shell.text())
            assert assets.scripts.count('/app.js') == 1
            coordinator = assets.scripts.index('/presentation.js')
            app = assets.scripts.index('/app.js')
            for adapter in ('/presentation_mobile.js', '/presentation_desktop.js'):
                assert coordinator < assets.scripts.index(adapter) < app
            assert {'/theme.css', '/style.css', '/presentation_mobile.css', '/presentation_desktop.css'} <= set(assets.styles)
            cache = await (await client.get('/sw.js')).text()
            cached_assets = set(re.findall(r'"(/[^"\n]*)"', cache))
            for path in assets.styles + assets.scripts:
                response = await client.get(path)
                assert response.status == 200, path
                assert await response.read(), path
                assert response.content_type == ('text/css' if path.endswith('.css') else 'application/javascript')
                assert path in cached_assets, path
            # Loading a presentation must not grant a session access to jobs.
            assert (await client.get('/api/state')).status == 401
            assert (await client.get('/unlisted-presentation.js')).status == 401
    asyncio.run(scenario())
