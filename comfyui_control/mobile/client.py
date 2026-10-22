"""Small asynchronous client for ComfyUI's documented HTTP/WS interfaces."""
import asyncio
import json
from pathlib import PurePosixPath

import aiohttp


class ComfyError(Exception):
    def __init__(self, message, rejected=False):
        super().__init__(message)
        self.rejected = rejected


class ComfyClient:
    def __init__(self, session, base_url):
        self.session = session
        self.base = base_url.rstrip("/")

    async def upload_image(self, contents, name):
        data = aiohttp.FormData()
        data.add_field('image', contents, filename=name, content_type='image/png')
        data.add_field('type', 'input')
        # LoadImage's standard combo lists files directly in input/, not nested
        # directories. A unique prefix avoids replacing existing inputs.
        data.add_field('subfolder', '')
        data.add_field('overwrite', 'false')
        try:
            async with self.session.post(self.base + '/upload/image', data=data,
                                         timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    raise ComfyError(f'ComfyUI could not accept the source image (HTTP {response.status}). No generation was queued.')
                result = await response.json()
            filename, subfolder = result.get('name'), result.get('subfolder', '')
            if (result.get('type') != 'input' or not isinstance(filename, str) or not filename
                    or PurePosixPath(filename).name != filename or '\\' in filename
                    or subfolder != '' or filename in {'.', '..'}):
                raise ComfyError('ComfyUI returned an invalid uploaded-image location. No generation was queued.')
            return filename
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError) as exc:
            raise ComfyError('The source image could not be uploaded to ComfyUI. No generation was queued; reconnect and try again.') from exc

    async def request(self, method, path, data=None, expected_type=dict):
        try:
            async with self.session.request(method, self.base + path, json=data,
                                            timeout=aiohttp.ClientTimeout(total=30)) as response:
                text = await response.text()
                try:
                    value = json.loads(text) if text else {}
                except ValueError:
                    raise ComfyError("ComfyUI returned an invalid response. Check the ComfyUI URL.") from None
                if response.status >= 400:
                    details = value.get("error", value) if isinstance(value, dict) else value
                    if isinstance(details, dict):
                        details = details.get("message", "Request failed") + ": " + str(details.get("details", ""))
                    node_errors = value.get("node_errors", {}) if isinstance(value, dict) else {}
                    if node_errors:
                        summaries = []
                        for node, error in node_errors.items():
                            messages = [str(e.get("message", "")) + ": " + str(e.get("details", "")) for e in error.get("errors", [])]
                            summaries.append(f"Node {node}: " + "; ".join(messages))
                        details = str(details) + " · " + " · ".join(summaries)
                    raise ComfyError(str(details)[:2500], rejected=response.status < 500)
                if not isinstance(value, expected_type):
                    raise ComfyError("ComfyUI returned an unexpected API response. Check the ComfyUI URL.")
                return value
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ComfyError("ComfyUI is unavailable. Start it in the desktop app and check its API URL.") from exc
