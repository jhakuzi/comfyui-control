"""Authenticated, same-origin mobile HTTP interface and SSE stream."""
import asyncio
from collections import defaultdict, deque, OrderedDict
import io
import hashlib
import json
import mimetypes
from pathlib import Path
import secrets
import re
import time
from urllib.parse import urlsplit

from aiohttp import web
import qrcode
import qrcode.image.svg

from .client import ComfyError
from .service import MobileService, json_safe
from .settings import check_password, lan_address

ASSETS = Path(__file__).with_name("web")
ICON = Path(__file__).parents[1] / "assets" / "comfyui-control.png"
OWNER = web.RequestKey("mobile_owner", str) if hasattr(web, "RequestKey") else "mobile_owner"
PUBLIC = {"/", "/app.js", "/style.css", "/manifest.webmanifest", "/sw.js", "/icon.png", "/icon-192.png", "/icon-512.png", "/api/login", "/api/session"}


def json_response(value, **kwargs):
    return web.json_response(json_safe(value), **kwargs)


async def object_body(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Send a JSON object.")
    return body


def qr_svg(url):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=6)
    code.add_data(url)
    code.make(fit=True)
    output = io.BytesIO()
    code.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return output.getvalue()


class MobileHTTP:
    def __init__(self, service):
        self.service = service
        self.settings = service.settings
        self.sessions = {}
        self.attempts = defaultdict(deque)
        self.thumbnails = OrderedDict()
        self.allowed_hosts = {urlsplit(self.settings.url()).hostname, self.settings.bind, "localhost", "127.0.0.1", "::1", lan_address()}

    def authenticated(self, request):
        if not self.settings.require_auth:
            return True
        key = request.cookies.get("mobile_session", "")
        return self.sessions.get(key, 0) > time.time()

    @web.middleware
    async def middleware(self, request, handler):
        try:
            try:
                host = urlsplit("http://" + request.host)
                if host.hostname not in self.allowed_hosts or host.username or host.password:
                    raise web.HTTPForbidden(text="Unrecognized host. Configure the advertised LAN/VPN hostname in the desktop app.")
            except ValueError:
                raise web.HTTPForbidden(text="Invalid host.") from None
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                raise web.HTTPForbidden(text="Cross-site requests are not accepted.")
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origins = {f"{request.scheme}://{request.host}", self.settings.url().rstrip("/")}
                if request.headers.get("Origin") not in origins:
                    raise web.HTTPForbidden(text="A same-origin request is required.")
                if request.content_type != "application/json":
                    raise web.HTTPUnsupportedMediaType(text="Send application/json.")
            if request.path not in PUBLIC and not self.authenticated(request):
                return json_response({"error": "Sign in to use the mobile interface."}, status=401)
            identity = request.cookies.get("mobile_client", "")
            issue_identity = request.path in {"/api/session", "/api/login"} and not re.fullmatch(r"[A-Za-z0-9_-]{43}", identity)
            if issue_identity:
                identity = secrets.token_urlsafe(32)
            request[OWNER] = hashlib.sha256(identity.encode()).hexdigest() if re.fullmatch(r"[A-Za-z0-9_-]{43}", identity) else None
            if request.path.startswith("/api/") and request.path not in PUBLIC and request[OWNER] is None:
                return json_response({"error": "Reopen the mobile page to restore this browser session."}, status=409)
            response = await handler(request)
            if issue_identity:
                # Separate from the short-lived authentication cookie; survives app restarts.
                response.set_cookie("mobile_client", identity, httponly=True, samesite="Strict", secure=self.settings.url().startswith("https:"), max_age=180 * 24 * 3600)
        except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
            response = web.json_response({"error": str(exc)[:2500] or "Invalid request."}, status=400)
        except ComfyError as exc:
            response = web.json_response({"error": str(exc)}, status=503)
        except web.HTTPException as exc:
            response = web.Response(status=exc.status, body=exc.body, headers=exc.headers)
        except OSError:
            response = web.json_response({"error": "Could not access mobile settings or output storage."}, status=503)
        response.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        })
        return response

    async def login(self, request):
        remote = request.remote or "unknown"
        now = time.time()
        attempts = self.attempts[remote]
        if len(self.attempts) > 2048:
            self.attempts.pop(next(iter(self.attempts)))
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 5:
            return json_response({"error": "Too many attempts. Wait a minute."}, status=429)
        attempts.append(now)
        value = (await object_body(request)).get("password", "")
        if not isinstance(value, str) or len(value) > 256 or not await asyncio.to_thread(check_password, value, self.settings.password):
            return json_response({"error": "Incorrect password."}, status=401)
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
        if len(self.sessions) >= 100:
            return json_response({"error": "Too many signed-in sessions. Restart the mobile server."}, status=429)
        key = secrets.token_urlsafe(32)
        self.sessions[key] = now + 12 * 3600
        response = web.json_response({"ok": True})
        response.set_cookie("mobile_session", key, httponly=True, samesite="Strict", secure=self.settings.url().startswith("https:"), max_age=12 * 3600)
        return response

    async def session(self, request):
        return json_response({"authenticated": self.authenticated(request), "authentication_required": self.settings.require_auth})

    async def logout(self, request):
        self.sessions.pop(request.cookies.get("mobile_session"), None)
        response = web.json_response({"ok": True})
        response.del_cookie("mobile_session")
        return response

    async def state(self, request):
        return json_response(self.service.state(owner=request[OWNER]))

    async def resume(self, request):
        await object_body(request)
        await self.service.resume()
        return json_response(self.service.state(owner=request[OWNER]))

    async def events(self, request):
        if len(self.service.subscribers) >= 12:
            raise web.HTTPServiceUnavailable(text="Too many live connections.")
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        await response.prepare(request)
        queue = asyncio.Queue(maxsize=2)
        self.service.subscribers[queue] = request[OWNER]
        queue.put_nowait(self.service.state(owner=request[OWNER]))
        try:
            while not self.service.closed:
                if not self.authenticated(request):
                    break
                try:
                    state = await asyncio.wait_for(queue.get(), 20)
                    if state is None:
                        break
                    await asyncio.wait_for(response.write(b"data: " + json.dumps(state).encode() + b"\n\n"), 10)
                except asyncio.TimeoutError:
                    await asyncio.wait_for(response.write(b"event: ping\ndata: {}\n\n"), 10)
        except (ConnectionError, asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            self.service.subscribers.pop(queue, None)
        return response

    async def presets(self, request):
        if request.method == "GET":
            return json_response([{**item, "default": item["id"] == self.settings.default_preset}
                                  for item in self.service.presets.list()])
        body = await object_body(request)
        if isinstance(body.get("workflow"), str):
            body["workflow"] = json.loads(body["workflow"])
        preset = self.service.presets.create(body.get("name"), body.get("workflow"))
        return json_response(await self.service.describe(preset), status=201)

    async def preset(self, request):
        identifier = request.match_info["id"]
        if request.method == "PUT":
            preset = self.service.presets.map(identifier, (await object_body(request)).get("mappings"))
        elif request.method == "DELETE":
            self.service.presets.path(identifier).unlink()
            return json_response({"ok": True})
        else:
            preset = self.service.presets.get(identifier)
        return json_response(await self.service.describe(preset))

    async def saved_workflows(self, request):
        if request.method == "GET":
            return json_response(await self.service.saved_workflows())
        return json_response(await self.service.import_saved_workflow((await object_body(request)).get("name")), status=201)

    async def generate(self, request):
        job = await self.service.submit(await object_body(request), owner=request[OWNER])
        return json_response(self.service.public_job(job), status=202)

    async def cancel(self, request):
        body = await object_body(request)
        if body.get("confirm_interrupt") is not True:
            raise ValueError("Confirm interruption before cancelling a running job.")
        return json_response(self.service.public_job(await self.service.cancel(request.match_info["id"], owner=request[OWNER])))

    async def gallery(self, request):
        return json_response(await self.service.gallery(owner=request[OWNER]))

    async def image(self, request):
        item = self.service.images.get(request.match_info["id"])
        if not item:
            for job in self.service.current_jobs():
                for stored in job.get("images", []):
                    if stored.get("id") == request.match_info["id"]:
                        item = self.service.image_ref(stored, job["id"])
                        break
                if item:
                    break
        if not item:
            raise web.HTTPNotFound(text="This image is no longer available. Refresh the gallery.")
        path = self.service.local_image(item)
        headers = {}
        if request.query.get("download") == "1":
            # ASCII fallback avoids response-header injection via filenames.
            from urllib.parse import quote
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(item["filename"], safe="")
        if path:
            if request.query.get("thumbnail") == "1":
                return await self.thumbnail((item["id"], path.stat().st_mtime_ns), path)
            return web.FileResponse(path, headers=headers)
        candidate = self.service.output_dir / item["subfolder"] / item["filename"]
        if item["type"] == "output" and (candidate.exists() or candidate.is_symlink()):
            raise web.HTTPNotFound(text="Image is unavailable.")
        # This is not an arbitrary proxy: references originate in ComfyUI history.
        from urllib.parse import urlencode
        params = {k: item[k] for k in ("filename", "subfolder", "type")}
        thumb = request.query.get("thumbnail") == "1"
        key = (item["id"], item.get("job"), item.get("created"))
        if thumb and key in self.thumbnails:
            return web.Response(body=self.thumbnails[key], content_type="image/jpeg")
        if thumb:
            params["preview"] = "jpeg;75"
        query = urlencode(params)
        async with self.service.session.get(self.service.client.base + "/view?" + query) as upstream:
            if upstream.status != 200 or upstream.content_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise web.HTTPNotFound(text="Image was deleted or is unavailable.")
            if thumb:
                chunks, size = [], 0
                async for chunk in upstream.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 20 * 1024 * 1024:
                        raise web.HTTPRequestEntityTooLarge(max_size=20 * 1024 * 1024, actual_size=size)
                    chunks.append(chunk)
                return await self.thumbnail(key, b"".join(chunks))
            response = web.StreamResponse(headers={**headers, "Content-Type": upstream.content_type, "Cache-Control": "no-store"})
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(65536):
                await response.write(chunk)
            await response.write_eof()
            return response

    async def thumbnail(self, key, source):
        if key not in self.thumbnails:
            def encode():
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
                from PySide6.QtGui import QImageReader
                buffer = None
                if isinstance(source, Path):
                    reader = QImageReader(str(source))
                else:
                    buffer = QBuffer()
                    buffer.setData(source)
                    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                    reader = QImageReader(buffer)
                reader.setAutoTransform(True)
                reader.setScaledSize(reader.size().scaled(QSize(384, 384), Qt.AspectRatioMode.KeepAspectRatio))
                image = reader.read()
                if image.isNull():
                    return None
                data = QByteArray()
                output = QBuffer(data)
                output.open(QIODevice.OpenModeFlag.WriteOnly)
                if not image.save(output, "JPEG", 80):
                    return None
                return bytes(data)
            data = await asyncio.to_thread(encode)
            if data is None:
                raise web.HTTPNotFound(text="Thumbnail unavailable; open the original image.")
            self.thumbnails[key] = data
            while len(self.thumbnails) > 64:
                self.thumbnails.popitem(last=False)
        return web.Response(body=self.thumbnails[key], content_type="image/jpeg")

    async def preview(self, request):
        job = self.service.jobs.get(self.service.preview_job, {})
        if not self.service.preview or job.get("owner") != request[OWNER]:
            raise web.HTTPNotFound()
        data, content_type = self.service.preview
        return web.Response(body=data, content_type=content_type)

    async def asset(self, request):
        name = request.path
        if name in ("/icon.png", "/icon-192.png", "/icon-512.png"):
            if name == "/icon.png":
                return web.FileResponse(ICON)
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
            from PySide6.QtGui import QImage
            size = 192 if name == "/icon-192.png" else 512
            image = QImage(str(ICON)).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            return web.Response(body=bytes(data), content_type="image/png")
        file = ASSETS / ({"/": "index.html"}.get(name, name.lstrip("/")))
        if name not in PUBLIC or not file.is_file():
            raise web.HTTPNotFound()
        content_type = {".js": "application/javascript", ".webmanifest": "application/manifest+json"}.get(file.suffix)
        return web.Response(body=file.read_bytes(), content_type=content_type or mimetypes.guess_type(file.name)[0] or "text/plain")

    def app(self):
        app = web.Application(middlewares=[self.middleware], client_max_size=5 * 1024 * 1024)
        app.add_routes([
            web.post('/api/login', self.login), web.get('/api/session', self.session), web.post('/api/logout', self.logout),
            web.get('/api/state', self.state), web.post('/api/resume', self.resume), web.get('/api/events', self.events),
            web.get('/api/presets', self.presets), web.post('/api/presets', self.presets),
            web.get('/api/workflows/saved', self.saved_workflows), web.post('/api/workflows/saved', self.saved_workflows),
            web.get('/api/presets/{id}', self.preset), web.put('/api/presets/{id}', self.preset), web.delete('/api/presets/{id}', self.preset),
            web.post('/api/generate', self.generate), web.post('/api/jobs/{id}/cancel', self.cancel),
            web.get('/api/gallery', self.gallery), web.get('/api/images/{id}', self.image), web.get('/api/preview', self.preview),
        ])
        for path in PUBLIC - {"/api/login", "/api/session"}:
            app.router.add_get(path, self.asset)
        return app
