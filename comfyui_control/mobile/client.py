"""Small asynchronous client for ComfyUI's documented HTTP/WS interfaces."""
import asyncio
import json

import aiohttp


class ComfyError(Exception):
    def __init__(self, message, rejected=False):
        super().__init__(message)
        self.rejected = rejected


class ComfyClient:
    def __init__(self, session, base_url):
        self.session = session
        self.base = base_url.rstrip("/")

    async def request(self, method, path, data=None):
        try:
            async with self.session.request(method, self.base + path, json=data,
                                            timeout=aiohttp.ClientTimeout(total=30)) as response:
                text = await response.text()
                try:
                    value = json.loads(text) if text else {}
                except ValueError:
                    raise ComfyError("ComfyUI returned an invalid response. Check the ComfyUI URL.") from None
                if not isinstance(value, dict):
                    raise ComfyError("ComfyUI returned an unexpected API response. Check the ComfyUI URL.")
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
                return value
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ComfyError("ComfyUI is unavailable. Start it in the desktop app and check its API URL.") from exc
