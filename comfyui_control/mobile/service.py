"""One event-loop service for jobs, ComfyUI events, and output references."""
import asyncio
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time
import uuid

import aiohttp

from .client import ComfyClient, ComfyError
from .settings import save_json
from .workflows import Presets, candidates, fields_for, render, suggested_mappings, with_model_controls, MODEL_CONTROLS_VERSION
from .workflow_sources import saved_workflows, saved_workflow_graph


def revision(preset):
    return hashlib.sha256(json.dumps([preset["graph"], preset["mappings"]], sort_keys=True).encode()).hexdigest()


def json_safe(value):
    """JavaScript must not round fixed 64-bit seeds or other workflow integers."""
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if type(value) is float and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


class MobileService:
    def __init__(self, directory, settings, output_dir, desktop_state="stopped", observer=None):
        self.observer = observer
        self.directory = Path(directory)
        self.settings = settings
        self.output_dir = Path(output_dir).resolve()
        self.output_scope = self.scope_for(self.output_dir)
        self.desktop_state = desktop_state
        self.presets = Presets(self.directory / "presets")
        try:
            saved = json.loads((self.directory / "jobs.json").read_text())
            self.jobs = saved.get("jobs", {})
            self.client_id = saved["client_id"]
            if not isinstance(self.jobs, dict) or not isinstance(self.client_id, str):
                raise ValueError()
        except (OSError, ValueError, KeyError):
            self.jobs, self.client_id = {}, str(uuid.uuid4())
        self.online = False
        self.connection = "Connecting to ComfyUI…"
        self.queue = {"queue_running": [], "queue_pending": []}
        self.images = {}
        for job in self.current_jobs():
            for item in job.get("images", []):
                self.image_ref(item, job.get("id"))
        self.preview = None
        self.preview_version = 0
        self.preview_job = None
        self.subscribers = {}
        self.instance_id = uuid.uuid4().hex
        self.state_version = 0
        self.resume_task = None
        self.info = {}
        self.info_time = 0
        self.session = None
        self.client = None
        self.socket_task = None
        self.refresh_task = None
        self.refresh_needed = False
        self.submit_lock = asyncio.Lock()
        self.refresh_lock = asyncio.Lock()
        self.closed = False

    def scope_for(self, output):
        return hashlib.sha256((str(output) + "|" + self.settings.comfy_url.rstrip("/")).encode()).hexdigest()

    def current_jobs(self):
        return [job for job in self.jobs.values() if job.get("scope", self.output_scope) == self.output_scope]

    def change_output(self, output):
        self.output_dir = Path(output).resolve()
        self.output_scope = self.scope_for(self.output_dir)
        self.images.clear()
        self.preview = self.preview_job = None
        for job in self.current_jobs():
            for item in job.get("images", []):
                self.image_ref(item, job.get("id"))

    async def start(self):
        self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=10), timeout=aiohttp.ClientTimeout(total=120, connect=5))
        self.client = ComfyClient(self.session, self.settings.comfy_url)
        self.socket_task = asyncio.create_task(self.watch())

    async def stop(self):
        self.closed = True
        for subscriber in self.subscribers:
            if subscriber.full():
                subscriber.get_nowait()
            subscriber.put_nowait(None)
        tasks = [t for t in (self.socket_task, self.refresh_task, self.resume_task) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.session:
            await self.session.close()

    def persist(self):
        # State contains settings and image references, never duplicate image files.
        if len(self.jobs) > 100:
            terminal = [key for key, job in self.jobs.items() if job["status"] in {"complete", "failed", "cancelled"}]
            for key in terminal[:len(self.jobs) - 100]:
                self.jobs.pop(key, None)
        save_json(self.directory / "jobs.json", {"client_id": self.client_id, "jobs": self.jobs})

    @staticmethod
    def public_job(job):
        return {k: v for k, v in job.items() if k not in {"graph", "scope", "owner"}}

    def state(self, include_details=True, owner=None):
        jobs = [j for j in self.current_jobs() if owner is None or j.get("owner") == owner][-100:]
        if include_details:
            public = [self.public_job(job) for job in jobs]
        else:
            keys = {"id", "status", "progress", "prompt_id", "position", "preset_name", "error"}
            public = [{**{k: v for k, v in job.items() if k in keys}, "image_count": len(job.get("images", []))} for job in jobs]
        preview_allowed = owner is None or any(j["id"] == self.preview_job for j in jobs)
        return json_safe({"instance": self.instance_id, "version": self.state_version,
                "online": self.online, "connection": self.connection, "desktop": self.desktop_state,
                "jobs": public, "partial": not include_details, "queue_remaining": len(self.queue.get("queue_running", [])) + len(self.queue.get("queue_pending", [])),
                "preview": f"/api/preview?v={self.preview_version}" if self.preview and preview_allowed else None,
                "preview_job": self.preview_job if preview_allowed else None})

    def broadcast(self):
        self.state_version += 1
        for subscriber, owner in self.subscribers.items():
            state = self.state(include_details=False, owner=owner)
            if subscriber.full():
                subscriber.get_nowait()
            subscriber.put_nowait(state)

    async def metadata(self, force=False):
        if force or time.monotonic() - self.info_time > 30 or not self.info:
            self.info = await self.client.request("GET", "/object_info")
            self.info_time = time.monotonic()
        return self.info

    async def describe(self, preset):
        try:
            info = await self.metadata()
            missing = sorted({n["class_type"] for n in preset["graph"].values()} - set(info))
        except ComfyError:
            info, missing = {}, []
        if info and preset.get("model_controls_version") != MODEL_CONTROLS_VERSION:
            previous = preset
            preset = with_model_controls(preset, info)
            if preset["mappings"] != previous["mappings"]:
                preset["model_upgrade_revision"] = revision(previous)
            save_json(self.presets.path(preset["id"]), preset)
        return {"id": preset["id"], "name": preset["name"], "revision": revision(preset),
                "graph_revision": hashlib.sha256(json.dumps(preset["graph"], sort_keys=True).encode()).hexdigest(),
                "model_upgrade_revision": preset.get("model_upgrade_revision"),
                "fields": fields_for(preset, info), "candidates": [{k: v for k, v in item.items() if k != "default"} for item in candidates(preset["graph"], info)],
                "missing_nodes": missing}

    async def refresh_models(self, identifier):
        info = await self.metadata(force=True)
        previous = self.presets.get(identifier)
        preset = with_model_controls(previous, info)
        if preset["mappings"] != previous["mappings"]:
            preset["model_upgrade_revision"] = revision(previous)
        save_json(self.presets.path(identifier), preset)
        return await self.describe(preset)

    async def saved_workflows(self):
        return await saved_workflows(self.client)

    async def import_saved_workflow(self, name):
        graph = await saved_workflow_graph(self.client, name)
        for item in self.presets.list():
            existing = self.presets.get(item["id"])
            if existing.get("comfy_source") == name and existing["graph"] == graph:
                return await self.describe(existing)
        preset = self.presets.create(Path(name).stem[:100], graph)
        preset["comfy_source"] = name
        preset["mappings"] = suggested_mappings(graph)
        save_json(self.presets.path(preset["id"]), preset)
        return await self.describe(preset)

    async def submit(self, body, owner=None):
        request_id = body.get("request_id")
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("A valid request ID is required to prevent duplicate submissions.") from None
        async with self.submit_lock:
            if request_id in self.jobs:
                if owner is not None and self.jobs[request_id].get("owner") != owner:
                    raise ValueError("This request belongs to another browser session.")
                return self.jobs[request_id]
            if len([j for j in self.current_jobs() if j["status"] not in {"complete", "failed", "cancelled"}]) >= 20:
                raise ValueError("There are already 20 unfinished mobile jobs.")
            preset = self.presets.get(body.get("preset"))
            if body.get("revision") != revision(preset):
                raise ValueError("This preset changed. Reload it before generating.")
            info = await self.metadata()
            missing = {n["class_type"] for n in preset["graph"].values()} - set(info)
            if missing:
                raise ValueError("ComfyUI is missing these nodes: " + ", ".join(sorted(missing)))
            graph, actual = render(preset, body.get("values", {}), body.get("random_seed", False), body.get("disabled_loras", []), info)
            # Journal before the network request. A lost response never retries a prompt blindly.
            job = {"id": request_id, "owner": owner, "scope": self.output_scope, "preset": preset["id"], "preset_name": preset["name"], "revision": revision(preset),
                   "values": actual, "disabled_loras": body.get("disabled_loras", []), "created": time.time(),
                   "status": "submitting", "progress": None, "images": [], "prompt_id": None}
            job["controls"] = [{k: field[k] for k in ("key", "label", "role", "kind")} for field in fields_for(preset, info)]
            self.jobs[request_id] = job
            self.persist()
            try:
                result = await self.client.request("POST", "/prompt", {
                    "prompt": graph, "client_id": self.client_id,
                    "extra_data": {"mobile_request_id": request_id}})
                job.update(prompt_id=result["prompt_id"], status="queued")
            except ComfyError as exc:
                job.update(status="failed" if exc.rejected else "unknown", error=str(exc))
            except (KeyError, TypeError):
                job.update(status="unknown", error="ComfyUI's submission response was incomplete. Reconnecting before retrying is safest.")
            self.persist()
            self.broadcast()
            self.schedule_refresh()
            return job

    def schedule_refresh(self):
        self.refresh_needed = True
        if not self.refresh_task or self.refresh_task.done():
            self.refresh_task = asyncio.create_task(self._refresh_scheduled())

    async def resume(self):
        # Concurrent phones share one upstream refresh. Never submit or restart work.
        if not self.resume_task or self.resume_task.done():
            self.resume_task = asyncio.create_task(self.refresh())
        try:
            await asyncio.wait_for(asyncio.shield(self.resume_task), 5)
        except asyncio.TimeoutError:
            pass  # The continuous WebSocket and refresh task will deliver the result.

    async def _refresh_scheduled(self):
        await asyncio.sleep(0.08)
        while self.refresh_needed:
            self.refresh_needed = False
            await self.refresh()

    def image_ref(self, descriptor, job=None):
        if not isinstance(descriptor, dict) or descriptor.get("type", "output") not in {"output", "temp"}:
            return None
        filename, subfolder = descriptor.get("filename", ""), descriptor.get("subfolder", "")
        if not isinstance(filename, str) or not isinstance(subfolder, str) or not filename or Path(filename).name != filename or "\\" in filename or "\\" in subfolder:
            return None
        relative = Path(subfolder) / filename
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return None
        image_type = descriptor.get("type", "output")
        key = hashlib.sha256((self.output_scope + ":" + image_type + ":" + str(relative)).encode()).hexdigest()[:32]
        previous = self.images.get(key, {})
        item = {**previous, "id": key, "filename": filename, "subfolder": subfolder, "type": image_type, "job": job or previous.get("job"),
                "url": f"/api/images/{key}", "thumbnail": f"/api/images/{key}?thumbnail=1", "download": f"/api/images/{key}?download=1"}
        self.images[key] = item
        return item

    async def refresh(self):
        async with self.refresh_lock:
            try:
                queue, history = await asyncio.gather(self.client.request("GET", "/queue"), self.client.request("GET", "/history?max_items=100"))
                self.queue = queue
                visible = {item[1] for items in queue.values() if isinstance(items, list) for item in items}
                missing = {j["prompt_id"] for j in self.current_jobs() if j.get("prompt_id") and j["prompt_id"] not in history and j["prompt_id"] not in visible
                           and j["status"] in {"submitting", "queued", "running", "cancelling", "unknown"}}
                async def recover_history(prompt_id):
                    from urllib.parse import quote
                    try:
                        return await asyncio.wait_for(self.client.request("GET", "/history/" + quote(prompt_id, safe="")), 5)
                    except (ComfyError, asyncio.TimeoutError):
                        return {}
                for recovered in await asyncio.gather(*(recover_history(pid) for pid in list(missing)[:20])):
                    history.update(recovered)
                for values in queue.values():
                    if not isinstance(values, list):
                        continue
                    for item in values:
                        if len(item) > 3 and isinstance(item[3], dict):
                            key = item[3].get("mobile_request_id")
                            if key in self.jobs:
                                self.jobs[key]["prompt_id"] = item[1]
                for prompt_id, record in history.items():
                    prompt = record.get("prompt", [])
                    if len(prompt) > 3 and isinstance(prompt[3], dict):
                        key = prompt[3].get("mobile_request_id")
                        if key in self.jobs:
                            self.jobs[key]["prompt_id"] = prompt_id
                    job = next((j for j in self.current_jobs() if j.get("prompt_id") == prompt_id), None)
                    refs = []
                    for node in record.get("outputs", {}).values():
                        for descriptor in node.get("images", []) if isinstance(node, dict) else []:
                            ref = self.image_ref(descriptor, job["id"] if job else None)
                            if ref:
                                extra = prompt[3] if len(prompt) > 3 and isinstance(prompt[3], dict) else {}
                                created = extra.get("create_time")
                                if isinstance(created, (int, float)):
                                    ref["created"] = created / 1000 if created > 100_000_000_000 else created
                                else:
                                    ref.setdefault("created", job["created"] if job else time.time())
                                refs.append(ref)
                    if job:
                        status = record.get("status", {})
                        failed = status.get("status_str") == "error"
                        job.update(status="failed" if failed else "complete", images=refs, progress=None)
                        if not failed:
                            job.pop("error", None)
                        if failed:
                            messages = status.get("messages", [])
                            error = next((data.get("exception_message", "Generation failed") for kind, data in messages if kind == "execution_error"), "Generation was interrupted or failed.")
                            job["error"] = str(error)[:2500]
                running = {item[1] for item in queue.get("queue_running", [])}
                pending = {item[1]: index + 1 for index, item in enumerate(queue.get("queue_pending", []))}
                for job in self.current_jobs():
                    if job.get("prompt_id") in running:
                        job.update(status="running", position=0)
                        job.pop("error", None)
                    elif job.get("prompt_id") in pending:
                        job.update(status="queued", position=pending[job["prompt_id"]])
                        job.pop("error", None)
                    elif job.get("prompt_id") and job["prompt_id"] not in history and job["status"] in {"running", "queued", "cancelling", "submitting"}:
                        job.update(status="unknown", progress=None, error="This job is no longer in ComfyUI's queue or recent history. Check ComfyUI before submitting again.")
                self.online = True
                self.connection = "Connected to ComfyUI"
                self.persist()
            except OSError:
                self.online = False
                self.connection = "Mobile storage is unavailable. Check disk space and configuration-folder permissions."
            except (ComfyError, ValueError):
                self.online = False
                self.connection = "ComfyUI is offline; reconnecting…"
            self.broadcast()

    async def cancel(self, identifier, owner=None):
        job = self.jobs.get(identifier)
        if not job or job not in self.current_jobs() or not job.get("prompt_id") or owner is not None and job.get("owner") != owner:
            raise ValueError("No cancellable job was found.")
        queue = await self.client.request("GET", "/queue")
        prompt_id = job["prompt_id"]
        if any(item[1] == prompt_id for item in queue.get("queue_pending", [])):
            await self.client.request("POST", "/queue", {"delete": [prompt_id]})
            await self.refresh()
            still_queued = any(item[1] == prompt_id for item in self.queue.get("queue_pending", []))
            now_running = any(item[1] == prompt_id for item in self.queue.get("queue_running", []))
            if self.online and not still_queued and not now_running and job["status"] != "complete":
                job["status"] = "cancelled"
                job.pop("error", None)
        elif any(item[1] == prompt_id for item in queue.get("queue_running", [])):
            # Never fall back to /interrupt: old versions interrupt globally even
            # when given a prompt_id, racing with another client's next job.
            from urllib.parse import quote
            try:
                result = await self.client.request("POST", "/api/jobs/" + quote(prompt_id, safe="") + "/cancel", {})
            except ComfyError as exc:
                raise ValueError("Safe per-job interruption is unavailable on this ComfyUI server. Cancel the running job in ComfyUI itself. No global interrupt was sent.") from exc
            if not result.get("cancelled"):
                await self.refresh()
                return job
            job["status"] = "cancelling"
        else:
            await self.refresh()
            return job
        self.persist()
        self.broadcast()
        return job

    async def watch(self):
        delay = 1
        while not self.closed:
            try:
                timeout = aiohttp.ClientWSTimeout(ws_close=5) if hasattr(aiohttp, "ClientWSTimeout") else 5
                async with self.session.ws_connect(self.client.base + "/ws", params={"clientId": self.client_id}, heartbeat=25,
                                                   max_msg_size=20 * 1024 * 1024, timeout=timeout) as websocket:
                    delay = 1
                    await self.refresh()
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = json.loads(message.data)
                                kind, data = event.get("type"), event.get("data", {})
                                if self.observer and isinstance(data, dict):
                                    self.observer(kind, data, time.monotonic())
                                job = next((j for j in self.current_jobs() if j.get("prompt_id") == data.get("prompt_id")), None)
                                if kind == "executing" and not data.get("prompt_id"):
                                    running = [j for j in self.current_jobs() if j["status"] == "running"]
                                    job = running[0] if len(running) == 1 else None
                                if job:
                                    if kind in {"execution_start", "executing"}:
                                        job["status"] = "running"
                                    if kind == "executing":
                                        if job.get("node") != data.get("node"):
                                            job["progress"] = None
                                        job["node"] = data.get("node")
                                    if kind == "progress":
                                        job["progress"] = {"value": data.get("value", 0), "max": data.get("max", 1)}
                                    if kind == "progress_state":
                                        active = [n for n in data.get("nodes", {}).values() if n.get("state") == "running" and n.get("max", 0) > 0]
                                        if active:
                                            job["progress"] = {"value": active[-1].get("value", 0), "max": active[-1]["max"]}
                                    if kind in {"execution_error", "execution_interrupted"}:
                                        job.update(status="failed", error=str(data.get("exception_message", "Generation interrupted."))[:2500])
                                    if kind == "execution_success":
                                        job["status"] = "complete"
                                    self.broadcast()
                                if kind in {"status", "executed", "execution_success", "execution_error", "execution_interrupted"} or kind == "executing" and data.get("node") is None:
                                    self.schedule_refresh()
                            except (ValueError, TypeError, AttributeError):
                                continue
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            raw = message.data
                            running = [j for j in self.current_jobs() if j["status"] == "running"]
                            if len(raw) > 8 and running:
                                event, image_type = struct.unpack(">II", raw[:8])
                                if event == 1 and image_type in (1, 2):
                                    self.preview = (raw[8:], "image/jpeg" if image_type == 1 else "image/png")
                                    self.preview_job = running[0]["id"]
                                    self.preview_version += 1
                                    self.broadcast()
                                elif event == 4 and 0 < image_type < len(raw) - 8:
                                    try:
                                        metadata = json.loads(raw[8:8 + image_type])
                                        content_type = metadata.get("image_type")
                                        matching = next((job for job in running if job.get("prompt_id") == metadata.get("prompt_id")), None)
                                        if matching and content_type in {"image/png", "image/jpeg"}:
                                            self.preview = (raw[8 + image_type:], content_type)
                                            self.preview_job = matching["id"]
                                            self.preview_version += 1
                                            self.broadcast()
                                    except (ValueError, TypeError, AttributeError):
                                        pass
            except (aiohttp.ClientError, asyncio.TimeoutError, ComfyError, OSError):
                pass
            self.online = False
            self.connection = "ComfyUI is offline; reconnecting…"
            if self.observer:
                self.observer('disconnected', {}, time.monotonic())
            self.broadcast()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    async def gallery(self, owner=None):
        # Explicit refresh only: no recurring filesystem scans or image duplication.
        root = self.output_dir
        def scan():
            found = []
            count = 0
            if not root.is_dir():
                return found
            for folder, directories, files in os.walk(root, followlinks=False):
                directories[:] = [d for d in directories if not (Path(folder) / d).is_symlink()]
                for filename in files:
                    count += 1
                    if count > 10000:
                        return found
                    path = Path(folder) / filename
                    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or path.is_symlink():
                        continue
                    try:
                        found.append((path.stat().st_mtime, path.relative_to(root)))
                    except OSError:
                        continue
            return found
        found = await asyncio.to_thread(scan)
        for created, path in sorted(found, reverse=True)[:100]:
            ref = self.image_ref({"filename": path.name, "subfolder": str(path.parent) if path.parent != Path(".") else "", "type": "output"})
            if ref:
                ref["created"] = created
        # Restore job associations after the filesystem scan.
        for job in self.current_jobs():
            for ref in job.get("images", []):
                self.image_ref(ref, job["id"])
        def created(item):
            return item.get("created", self.jobs.get(item.get("job"), {}).get("created", 0))
        ordered = sorted(self.images.values(), key=created, reverse=True)
        self.images = {item["id"]: item for item in ordered[:500]}
        return [{**item, "job": item.get("job") if owner is None or self.jobs.get(item.get("job"), {}).get("owner") == owner else None}
                for item in ordered[:200]]

    def local_image(self, item):
        if item.get("type") != "output":
            return None
        root = self.output_dir
        path = root / item["subfolder"] / item["filename"]
        # Reject symlink components, including symlinks to another output tree.
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return None
        if not path.resolve().is_relative_to(root) or not path.is_file():
            return None
        return path
