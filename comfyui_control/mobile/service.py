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
from urllib.parse import urlsplit

import aiohttp

from .client import ComfyClient, ComfyError
from .settings import lan_address, save_json
from .workflows import (Presets, candidates, fields_for, render, suggested_mappings,
                        with_model_controls, MODEL_CONTROLS_VERSION,
                        with_resolution_controls, RESOLUTION_CONTROLS_VERSION,
                        with_generation_controls, GENERATION_CONTROLS_VERSION)
from .workflow_sources import saved_workflows, saved_workflow_graph
from ..performance import GenerationPerformance
from .prompt_history import PromptHistory
from .image_metadata import generation_details
from .image_actions import IMAGE_WORKFLOWS, ImageLibrary, workflow_capabilities, workflow_name, workflow_bindings, workflow_import_error, upscale_multiplier_binding
from .image_pixels import encode_image
from ..background_process import run_background
import sys


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
    def __init__(self, directory, settings, output_dir, desktop_state="stopped", observer=None, monitoring=None, network_output=False):
        self.observer = observer
        self.monitoring = monitoring
        self.monitoring_active = False
        self.hardware = {}
        self.hardware_time = 0
        self.performance = {}
        self.directory = Path(directory)
        self.settings = settings
        self.local_comfy = urlsplit(settings.comfy_url).hostname in {'127.0.0.1', 'localhost', '::1', lan_address(), settings.bind} - {'0.0.0.0', '::'}
        self.network_output = network_output
        self.output_dir = Path(os.path.abspath(output_dir)) if network_output else Path(output_dir).resolve()
        self.output_scope = self.scope_for(self.output_dir)
        self.desktop_state = desktop_state
        self.output_status = {}
        self.presets = Presets(self.directory / "presets")
        self.prompts = PromptHistory(self.directory / 'prompts')
        self.image_library = ImageLibrary(self.directory / 'image-library.json')
        self.prompt_lock = asyncio.Lock()
        try:
            saved = json.loads((self.directory / "jobs.json").read_text())
            self.jobs = saved.get("jobs", {})
            self.client_id = saved["client_id"]
            if not isinstance(self.jobs, dict) or not isinstance(self.client_id, str):
                raise ValueError()
        except (OSError, ValueError, KeyError):
            self.jobs, self.client_id = {}, str(uuid.uuid4())
        self.online = False
        for job in self.jobs.values():
            job['seconds_per_iteration'] = None
        self.connection = "Connecting to ComfyUI…"
        self.queue = {"queue_running": [], "queue_pending": []}
        self.images = {}
        self.unavailable_images = set()
        self.gallery_time = 0
        self.gallery_lock = asyncio.Lock()
        self.legacy_trash_checked = set()
        self.image_workflow_lock = asyncio.Lock()
        self.workflow_names_lock = asyncio.Lock()
        self.workflow_names = []
        self.workflow_names_time = 0
        self.image_owners = {}
        self.ownership_available = True
        self.ownership_dirty = False
        ownership_path = self.directory / 'image-owners.json'
        if ownership_path.exists():
            try:
                if ownership_path.stat().st_size > 16 * 1024**2:
                    raise ValueError()
                owners = json.loads(ownership_path.read_text())
                if not isinstance(owners, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in owners.items()):
                    raise ValueError()
                self.image_owners = owners
            except (OSError, ValueError):
                self.ownership_available = False  # Fail closed; never overwrite a damaged privacy ledger.
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
        self.lora_files = None
        self.lora_files_time = 0
        self.lora_files_lock = asyncio.Lock()
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

    def change_output(self, output, network_output=False):
        self.network_output = network_output
        self.output_dir = Path(os.path.abspath(output)) if network_output else Path(output).resolve()
        self.output_scope = self.scope_for(self.output_dir)
        self.images.clear()
        self.unavailable_images.clear()
        self.gallery_time = 0
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
        self.update_monitoring()
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
        if self.ownership_dirty and self.ownership_available:
            save_json(self.directory / 'image-owners.json', self.image_owners)
            self.ownership_dirty = False

    def public_job(self, job):
        result = {k: v for k, v in job.items() if k not in {"graph", "scope", "owner", "prompt_history_recorded", "metadata"}}
        if 'images' in result:
            result['images'] = [item for item in result['images'] if item.get('id') not in self.unavailable_images
                                and not self.image_library.deleted_image(self.output_scope, item)]
        return result

    def state(self, include_details=True, owner=None):
        jobs = [j for j in self.current_jobs() if owner is None or j.get("owner") == owner][-100:]
        if include_details:
            public = [self.public_job(job) for job in jobs]
        else:
            keys = {"id", "status", "phase", "progress", "prompt_id", "position", "preset_name", "error", "seconds_per_iteration",
                    "batch_id", "batch_index", "batch_count", "batch_notice"}
            public = [{**{k: v for k, v in job.items() if k in keys}, "image_count": len(self.public_job(job).get("images", []))} for job in jobs]
        preview_allowed = owner is None or any(j["id"] == self.preview_job for j in jobs)
        return json_safe({"instance": self.instance_id, "version": self.state_version,
                "online": self.online, "connection": self.connection, "desktop": self.desktop_state,
                "output_status": self.output_status,
                "jobs": public, "partial": not include_details, "queue_remaining": len(self.queue.get("queue_running", [])) + len(self.queue.get("queue_pending", [])),
                "hardware": self.hardware if self.online and time.monotonic() - self.hardware_time < 5 else {},
                "preview": f"/api/preview?v={self.preview_version}" if self.preview and preview_allowed else None,
                "preview_job": self.preview_job if preview_allowed else None})

    def broadcast(self):
        self.update_monitoring()
        self.state_version += 1
        for subscriber, owner in self.subscribers.items():
            state = self.state(include_details=False, owner=owner)
            if subscriber.full():
                subscriber.get_nowait()
            subscriber.put_nowait(state)

    def update_monitoring(self):
        active_owners = {j.get('owner') for j in self.current_jobs() if j['status'] in {'submitting', 'queued', 'running', 'cancelling'}}
        # These are the controller PC's sensors, not those of a remote ComfyUI.
        active = not self.closed and self.online and self.local_comfy and any(owner in active_owners for owner in self.subscribers.values())
        if active != self.monitoring_active:
            self.monitoring_active = active
            if not active:
                self.hardware = {}
            if self.monitoring:
                self.monitoring(active)

    def update_hardware(self, sample):
        if not self.monitoring_active:
            return
        self.hardware = {key: value for key, value in sample.items() if key in {'utilization', 'vram_used'}
                         and type(value) in (int, float) and math.isfinite(value) and value >= 0}
        self.hardware_time = time.monotonic()
        self.broadcast()

    async def metadata(self, force=False):
        if force or time.monotonic() - self.info_time > 30 or not self.info:
            self.info = await self.client.request("GET", "/object_info")
            self.info_time = time.monotonic()
        return self.info

    async def lora_choices(self, preset, info, force=False):
        if not info or self.client is None or not any(field['role'] == 'lora_model' and field['options'] is None
                               for field in fields_for(preset, info)):
            return None
        async with self.lora_files_lock:
            if force or not self.lora_files_time or time.monotonic() - self.lora_files_time > 30:
                try:
                    files = await self.client.request('GET', '/models/loras', expected_type=list)
                    if not all(isinstance(name, str) and name for name in files):
                        raise ComfyError('ComfyUI returned an invalid LoRA list.')
                    self.lora_files = list(dict.fromkeys(files))
                except ComfyError:
                    # Older servers can lack this endpoint. Keep the workflow
                    # and its original value usable without fabricating choices.
                    self.lora_files = None
                self.lora_files_time = time.monotonic()
        return self.lora_files

    async def describe(self, preset):
        try:
            info = await self.metadata()
            missing = sorted({n["class_type"] for n in preset["graph"].values()} - set(info))
        except ComfyError:
            info, missing = {}, []
        previous = preset
        if info:
            if preset.get("model_controls_version") != MODEL_CONTROLS_VERSION:
                preset = with_model_controls(preset, info)
            if preset.get("resolution_controls_version") != RESOLUTION_CONTROLS_VERSION:
                preset = with_resolution_controls(preset, info)
            if preset.get("generation_controls_version") != GENERATION_CONTROLS_VERSION:
                preset = with_generation_controls(preset, info)
        if preset is not previous:
            if preset["mappings"] != previous["mappings"]:
                preset["model_upgrade_revision"] = revision(previous)
            save_json(self.presets.path(preset["id"]), preset)
        lora_models = await self.lora_choices(preset, info)
        return {"id": preset["id"], "name": preset["name"], "revision": revision(preset),
                "graph_revision": hashlib.sha256(json.dumps(preset["graph"], sort_keys=True).encode()).hexdigest(),
                "model_upgrade_revision": preset.get("model_upgrade_revision"),
                "fields": fields_for(preset, info, lora_models), "candidates": [{k: v for k, v in item.items() if k != "default"} for item in candidates(preset["graph"], info)],
                "missing_nodes": missing}

    async def refresh_models(self, identifier):
        info = await self.metadata(force=True)
        previous = self.presets.get(identifier)
        preset = with_generation_controls(with_resolution_controls(with_model_controls(previous, info), info), info)
        if preset["mappings"] != previous["mappings"]:
            preset["model_upgrade_revision"] = revision(previous)
        save_json(self.presets.path(identifier), preset)
        await self.lora_choices(preset, info, force=True)
        return await self.describe(preset)

    async def saved_workflows(self):
        return await saved_workflows(self.client)

    async def cleanup_vram(self):
        if self.client is None or not self.online:
            raise ValueError('Start ComfyUI and reconnect before requesting VRAM cleanup.')
        async with self.submit_lock:
            queue = await self.client.request('GET', '/queue')
            if not all(isinstance(queue.get(key), list) for key in ('queue_running', 'queue_pending')):
                raise ValueError('Could not verify that ComfyUI is idle. VRAM cleanup was not requested.')
            if queue.get('queue_running') or queue.get('queue_pending'):
                raise ValueError('Wait until ComfyUI has no running or queued generations before cleaning VRAM.')
            await self.client.request('POST', '/free', {'unload_models': True, 'free_memory': True})
        return {'message': 'VRAM cleanup requested. ComfyUI will release idle models and reload them for the next generation.'}

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

    async def submit(self, body, owner=None, *, expected_scope=None):
        request_id = body.get("request_id")
        batch_count = body.get("batch_count", 1)
        if type(batch_count) is not int or not 1 <= batch_count <= 20:
            raise ValueError("Batch count must be an integer from 1 to 20.")
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("A valid request ID is required to prevent duplicate submissions.") from None
        async with self.submit_lock:
            if expected_scope is not None and expected_scope != self.output_scope:
                raise ValueError('The output folder changed. No generation was queued; refresh the gallery.')
            if request_id in self.jobs:
                if owner is not None and self.jobs[request_id].get("owner") != owner:
                    raise ValueError("This request belongs to another browser session.")
                return self.jobs[request_id]
            if len([j for j in self.current_jobs() if j["status"] not in {"complete", "failed", "cancelled"}]) + batch_count > 20:
                raise ValueError("Batch would exceed the limit of 20 unfinished mobile jobs.")
            preset = self.presets.get(body.get("preset"))
            if body.get("revision") != revision(preset):
                raise ValueError("This preset changed. Reload it before generating.")
            info = await self.metadata()
            missing = {n["class_type"] for n in preset["graph"].values()} - set(info)
            if missing:
                raise ValueError("ComfyUI is missing these nodes: " + ", ".join(sorted(missing)))
            lora_models = await self.lora_choices(preset, info)
            if expected_scope is not None and expected_scope != self.output_scope:
                raise ValueError('The output folder changed. No generation was queued; refresh the gallery.')
            # Validate the entire batch before queueing anything. Each run uses
            # the same graph, with an independent random seed when requested.
            runs = [render(preset, body.get("values", {}), body.get("random_seed", False), body.get("disabled_loras", []), info, lora_models)
                    for _ in range(batch_count)]
            identifiers = [request_id] + [str(uuid.uuid5(uuid.UUID(request_id), str(index))) for index in range(1, batch_count)]
            if any(identifier in self.jobs for identifier in identifiers):
                raise ValueError("A batch request identifier is already in use. Start a new request.")
            scope = self.output_scope
            controls = fields_for(preset, info, lora_models)
            first = None
            for index, (identifier, (graph, actual)) in enumerate(zip(identifiers, runs)):
                if scope != self.output_scope:
                    break
                # Journal each run before its network request. Repeating the
                # parent request returns the existing batch and never requeues.
                job = {"id": identifier, "owner": owner, "scope": scope, "preset": preset["id"], "preset_name": preset["name"], "revision": revision(preset),
                   "values": actual, "disabled_loras": body.get("disabled_loras", []), "created": time.time(),
                   "status": "submitting", "phase": "preparing", "progress": None, "images": [], "prompt_id": None,
                   "prompt_history_recorded": False}
                if batch_count > 1:
                    job.update(batch_id=request_id, batch_index=index + 1, batch_count=batch_count)
                first = first or job
                job["controls"] = [{k: field[k] for k in ("key", "label", "role", "kind", "node", "input", "group")} for field in controls]
                job['metadata'] = generation_details(controls, actual, graph, info)
                self.jobs[identifier] = job
                self.persist()
                try:
                    result = await self.client.request("POST", "/prompt", {
                        "prompt": graph, "client_id": self.client_id,
                        "extra_data": {"mobile_request_id": identifier}})
                    job.update(prompt_id=result["prompt_id"], status="queued")
                except ComfyError as exc:
                    job.update(status="failed" if exc.rejected else "unknown", error=str(exc))
                except (KeyError, TypeError):
                    job.update(status="unknown", error="ComfyUI's submission response was incomplete. Reconnecting before retrying is safest.")
                await self._record_prompt(job)
                self.persist()
                if batch_count > 1 and job['status'] in {'failed', 'unknown'}:
                    first['batch_notice'] = f"Batch stopped at run {index + 1} of {batch_count}. Check History and ComfyUI's queue before starting another batch."
                    job['batch_notice'] = first['batch_notice']
                    break
            if scope != self.output_scope:
                first['batch_notice'] = 'The output folder changed; the remaining batch runs were not submitted.'
            self.persist()
            self.broadcast()
            self.schedule_refresh()
            return first

    async def prompt_history(self, owner, action='list', identifier=None, favorite=None):
        async with self.prompt_lock:
            if action == 'list':
                return await asyncio.to_thread(self.prompts.list, owner)
            if action == 'favorite':
                return await asyncio.to_thread(self.prompts.favorite, owner, identifier, favorite)
            if action == 'delete':
                await asyncio.to_thread(self.prompts.delete, owner, identifier)
            elif action == 'clear':
                await asyncio.to_thread(self.prompts.clear, owner)
            return {'ok': True}

    async def _record_prompt(self, job):
        if job.get('prompt_history_recorded') is not False or not job.get('prompt_id'):
            return
        job['prompt_history_recorded'] = True
        if not job.get('owner'):
            return
        try:
            async with self.prompt_lock:
                await asyncio.to_thread(self.prompts.record, job['owner'], job.get('controls', []), job.get('values', {}))
        except (OSError, ValueError):
            # Accepted generations must never be retried because a history write failed.
            job['prompt_history_notice'] = 'Generation submitted, but its prompt could not be saved to history. Check mobile storage or clear some history.'

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
        if relative.is_absolute() or ".." in relative.parts or '.comfyui-control-trash' in relative.parts or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return None
        image_type = descriptor.get("type", "output")
        key = hashlib.sha256((self.output_scope + ":" + image_type + ":" + str(relative)).encode()).hexdigest()[:32]
        previous = self.images.get(key, {})
        stamp = previous.get('modified', '')
        if job and job != previous.get('job'):
            stamp = ''
            self.unavailable_images.discard(key)
        version = f'v={stamp}&' if stamp else ''
        item = {**previous, "id": key, "filename": filename, "subfolder": subfolder, "type": image_type, "job": job or previous.get("job"),
                "url": f"/api/images/{key}" + (f'?v={stamp}' if stamp else ''),
                "thumbnail": f"/api/images/{key}?{version}thumbnail=1", "download": f"/api/images/{key}?{version}download=1"}
        if not previous or item['job'] != previous.get('job'):
            self.gallery_time = 0
        self.images[key] = item
        if job in self.jobs:
            owner = self.jobs[job].get('owner') or ''
            ownership_key = self.image_ownership_key(item)
            if self.image_owners.get(ownership_key) != owner:
                self.image_owners[ownership_key] = owner
                self.ownership_dirty = True
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
                    if job['status'] != 'running':
                        job['seconds_per_iteration'] = None
                        self.performance.pop(job['id'], None)
                    await self._record_prompt(job)
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

    async def cancel_batch(self, identifier, owner=None):
        # Wait for an in-flight submission to finish queueing before choosing
        # members. Reuse safe per-job cancellation; never interrupt globally.
        async with self.submit_lock:
            job = self.jobs.get(identifier)
            if not job or job not in self.current_jobs() or owner is not None and job.get('owner') != owner:
                raise ValueError('No cancellable job was found.')
            if not job.get('batch_id'):
                return await self.cancel(identifier, owner)
            members = [item for item in self.current_jobs()
                       if item.get('batch_id') == job['batch_id'] and item.get('owner') == job.get('owner')
                       and item.get('prompt_id') and item['status'] in {'queued', 'running', 'cancelling', 'unknown'}]
            # Remove queued runs even if a server cannot safely stop a running one.
            members.sort(key=lambda item: item['status'] != 'queued')
            errors = []
            for member in members:
                try:
                    await self.cancel(member['id'], owner)
                except (ValueError, ComfyError) as exc:
                    errors.append(str(exc))
            if errors:
                raise ValueError('Some batch runs could not be cancelled. ' + errors[0])
            return job

    async def cancel_queue(self, owner):
        """Stop this browser's current-scope jobs, queued members first."""
        async with self.submit_lock:
            if not owner:
                raise ValueError('A browser session is required to stop its queue.')
            members = [job for job in self.current_jobs()
                       if job.get('owner') == owner and job.get('prompt_id')
                       and job['status'] in {'queued', 'running', 'cancelling', 'unknown'}]
            members.sort(key=lambda job: job['status'] != 'queued')
            errors = []
            for job in members:
                try:
                    await self.cancel(job['id'], owner)
                except (ValueError, ComfyError) as exc:
                    errors.append(str(exc))
            if errors:
                raise ValueError('Some runs could not be stopped. ' + errors[0])

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
                                if kind in {"executing", "progress", "progress_state"} and not data.get("prompt_id"):
                                    running = [j for j in self.current_jobs() if j["status"] == "running"]
                                    job = running[0] if len(running) == 1 else None
                                if job:
                                    timing = self.performance.setdefault(job['id'], GenerationPerformance())
                                    timing.event(kind, {**data, 'prompt_id': job['prompt_id']})
                                    job['seconds_per_iteration'] = timing.snapshot()['current']
                                    if kind in {"execution_start", "executing"}:
                                        job["status"] = "running"
                                    if kind == "execution_start":
                                        job.update(phase="preparing", sampled=False, progress=None)
                                    if kind == "executing":
                                        if job.get("node") != data.get("node"):
                                            job["progress"] = None
                                        job["phase"] = "processing" if job.get("sampled") or data.get("node") is None else "preparing"
                                        job["node"] = data.get("node")
                                    if kind == "progress":
                                        job.update(status="running", phase="sampling", sampled=True)
                                        job["progress"] = {"value": data.get("value", 0), "max": data.get("max", 1)}
                                    if kind == "progress_state":
                                        active = [n for n in data.get("nodes", {}).values() if n.get("state") == "running" and n.get("max", 0) > 0]
                                        if active:
                                            job.update(status="running", phase="sampling", sampled=True)
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
            for timing in self.performance.values():
                timing.disconnect()
            for job in self.current_jobs():
                job['seconds_per_iteration'] = None
            self.connection = "ComfyUI is offline; reconnecting…"
            if self.observer:
                self.observer('disconnected', {}, time.monotonic())
            self.broadcast()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    def image_unavailable(self, identifier):
        # A network failure is not evidence of deletion. Call only on confirmed
        # missing local files or a ComfyUI 404/410 response.
        self.unavailable_images.add(identifier)
        self.gallery_time = 0

    async def gallery(self, owner=None, force=False):
        requested = time.monotonic()
        async with self.gallery_lock:
            if (force and self.gallery_time < requested) or not self.gallery_time or time.monotonic() - self.gallery_time >= 2:
                await self.scan_gallery()
            ordered = sorted(self.images.values(), key=lambda item: item.get('created',
                self.jobs.get(item.get('job'), {}).get('created', 0)), reverse=True)
            return [{**item, 'kept': self.image_library.contains(self.output_scope, owner, item),
                     'reuse': self.image_reuse_status(item, owner), 'job': item.get('job') if owner is None or
                     self.jobs.get(item.get('job'), {}).get('owner') == owner else None}
                    for item in ordered if item['id'] not in self.unavailable_images
                    and not self.image_library.deleted_image(self.output_scope, item)][:200]

    async def scan_gallery(self):
        # Shared across clients; filesystem work runs off the HTTP/Qt threads.
        # Validate old references separately so the scan limit cannot resurrect
        # deleted files or incorrectly prune valid files beyond that limit.
        root = self.output_dir
        scope = self.output_scope
        references = dict(self.images)
        for job in self.current_jobs():
            for descriptor in job.get('images', []):
                ref = self.image_ref(descriptor, job['id'])
                if ref:
                    references[ref['id']] = ref
        def scan():
            found = []
            valid = {}
            for identifier, item in references.items():
                path = self.local_image(item, root)
                if path:
                    try:
                        stat = path.stat()
                        valid[identifier] = (stat.st_mtime, str(stat.st_mtime_ns))
                    except OSError:
                        pass
            count = 0
            if not root.is_dir():
                return found, valid
            for folder, directories, files in os.walk(root, followlinks=False):
                directories[:] = [d for d in directories if d != '.comfyui-control-trash' and not (Path(folder) / d).is_symlink()]
                for filename in files:
                    count += 1
                    if count > 10000:
                        return found, valid
                    path = Path(folder) / filename
                    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or path.is_symlink():
                        continue
                    try:
                        stat = path.stat()
                        if path.is_file():
                            found.append((stat.st_mtime, str(stat.st_mtime_ns), path.relative_to(root)))
                    except OSError:
                        continue
            return found, valid
        if self.network_output:
            result = json.loads(await self.network_io('scan', list(references.values())))
            found = [(created, modified, Path(path)) for created, modified, path in result['found']]
            valid = result['valid']
        else:
            found, valid = await asyncio.to_thread(scan)
        if scope != self.output_scope:
            return  # Configuration changed while the worker was scanning.
        for identifier, item in list(self.images.items()):
            if self.local_comfy and item['type'] == 'output' and identifier in references and identifier not in valid:
                self.images.pop(identifier, None)
                self.unavailable_images.add(identifier)
        discovered = 0
        deleted = {(record['image'].get('id'), record['image'].get('modified'))
                   for record in self.image_library.deleted.values() if record['scope'] == scope}
        for created, modified, path in sorted(found, reverse=True):
            identifier = hashlib.sha256((scope + ':output:' + str(path)).encode()).hexdigest()[:32]
            if (identifier, modified) in deleted:
                continue
            if discovered >= 200:
                break
            discovered += 1
            ref = self.image_ref({"filename": path.name, "subfolder": str(path.parent) if path.parent != Path(".") else "", "type": "output"})
            if ref:
                valid[ref['id']] = (created, modified)
        for identifier, (created, modified) in valid.items():
            ref = self.images.get(identifier)
            if not ref:
                continue
            ref.update(created=created, modified=modified,
                       url=f'/api/images/{identifier}?v={modified}',
                       thumbnail=f'/api/images/{identifier}?v={modified}&thumbnail=1',
                       download=f'/api/images/{identifier}?v={modified}&download=1')
            self.unavailable_images.discard(identifier)
        def created(item):
            return item.get("created", self.jobs.get(item.get("job"), {}).get("created", 0))
        ordered = sorted(self.images.values(), key=created, reverse=True)
        self.images = {item["id"]: item for item in ordered if not self.image_library.deleted_image(scope, item)}
        self.images = dict(list(self.images.items())[:500])
        known = set(self.images) | {item.get('id') for job in self.current_jobs() for item in job.get('images', [])}
        self.unavailable_images.intersection_update(known)
        self.gallery_time = time.monotonic()

    def image_action_capabilities(self, identifier, owner):
        """Sharing pixels/settings never grants permission to remove an image."""
        item = self.images.get(identifier)
        if not item or identifier in self.unavailable_images or self.image_library.deleted_image(self.output_scope, item):
            raise ValueError('This saved image is no longer available. Refresh the gallery.')
        saved = item.get('type') == 'output'
        own = self._metadata_allowed(item, owner, allow_shared=False)
        local = self.local_comfy or self.network_output
        reason = ('Delete is available only for saved images in the configured local or network output folder.' if not saved or not local
                  else 'Only the browser that generated this image can delete it.' if not own else '')
        return {'image_id': identifier, 'modified': item.get('modified', ''),
                'kept': self.image_library.contains(self.output_scope, owner, item),
                'actions': {'keep': {'available': saved, 'reason': '' if saved else 'Favourites are available for saved output images.'},
                            'trash': {'available': not reason, 'reason': reason}, **workflow_capabilities()}}

    async def describe_image_actions(self, identifier, owner):
        result = self.image_action_capabilities(identifier, owner)
        if self.client is None or not self.online:
            return result
        item = self.images[identifier]
        source_available = (item.get('type') == 'output' and bool(item.get('modified'))
                            and (self.local_comfy or self.network_output))
        try:
            # Both the inline preview and the phone viewer share this short cache.
            async with self.workflow_names_lock:
                if time.monotonic() - self.workflow_names_time > 5:
                    self.workflow_names = await self.saved_workflows()
                    self.workflow_names_time = time.monotonic()
            for action in IMAGE_WORKFLOWS:
                try:
                    name = workflow_name(action, self.workflow_names)
                    reason = '' if source_available else 'Refresh the gallery and select an image from the configured local or network output folder.'
                    result['actions'][action].update(available=source_available, reason=reason, source=name)
                except ValueError as exc:
                    result['actions'][action]['reason'] = str(exc)
        except ComfyError as exc:
            for action in IMAGE_WORKFLOWS:
                result['actions'][action]['reason'] = str(exc)
        return result

    async def run_image_workflow(self, identifier, owner, body):
        action = body['action']
        if self.client is None or not self.online:
            raise ValueError(workflow_capabilities()[action]['reason'] + ' Start ComfyUI to use it.')
        request_id = body.get('request_id')
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('A valid request ID is required to prevent duplicate submissions.') from None
        instruction = body.get('prompt')
        if action == 'edit' and (not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 20000):
            raise ValueError('Enter an edit instruction (1–20,000 characters).')
        multiplier = body.get('multiplier')
        if multiplier is not None and (action != 'upscale' or type(multiplier) not in (int, float)
                                       or abs(multiplier) > 1e308 or not math.isfinite(multiplier) or multiplier <= 0):
            raise ValueError('The upscale multiplier must be a finite positive number, or left blank for the workflow default.')
        # Serialize only preparation. Execution still uses submit(), its journal,
        # the shared ComfyUI queue, and the existing WebSocket/session recovery.
        async with self.image_workflow_lock:
            existing = self.jobs.get(request_id)
            if existing:
                if existing.get('owner') != owner or existing.get('scope') != self.output_scope:
                    raise ValueError('This request belongs to another browser session or output folder.')
                return {'image_id': identifier, 'job': self.public_job(existing)}
            self.image_action_capabilities(identifier, owner)  # Known saved-image ID only.
            item = dict(self.images[identifier])
            scope = self.output_scope
            if (item.get('type') != 'output' or not (self.local_comfy or self.network_output)
                    or not item.get('modified')):
                raise ValueError('Select a saved image from the configured local or network output folder.')
            if body.get('modified') != item['modified']:
                raise ValueError('This image changed. Refresh the gallery before acting on it.')
            names = await self.saved_workflows()
            name = workflow_name(action, names)
            try:
                graph = await saved_workflow_graph(self.client, name)
            except ValueError as exc:
                companions = [entry for entry in names if entry.endswith('.api.json')]
                if name.endswith('.api.json') or not companions:
                    raise ValueError(workflow_import_error(action, name, exc)) from None
                try:
                    companion = workflow_name(action, companions)
                except ValueError:
                    raise ValueError(workflow_import_error(action, name, exc)) from None
                name = companion
                try:
                    graph = await saved_workflow_graph(self.client, name)
                except ValueError as fallback_error:
                    raise ValueError(workflow_import_error(action, name, fallback_error)) from None
            bindings = workflow_bindings(action, graph)
            if action == 'upscale':
                try:
                    bindings.append(upscale_multiplier_binding(graph))
                except ValueError:
                    if multiplier is not None:
                        raise
            info = await self.metadata()
            missing = {node['class_type'] for node in graph.values()} - set(info)
            if missing:
                raise ValueError('ComfyUI is missing these nodes: ' + ', '.join(sorted(missing)))
            if multiplier is not None:
                # Check node limits before making an unnecessary input copy.
                render({'graph': graph, 'mappings': [bindings[-1]]}, {'action-scale': multiplier}, info=info)
            if scope != self.output_scope:
                raise ValueError('The output folder changed. Refresh the gallery before trying again.')
            try:
                source = await self.network_io('read', {**item, 'expected_modified': item['modified']})
            except OSError as exc:
                raise ValueError(f'Could not read the selected image: {exc}. Refresh the gallery; no generation was queued.') from None
            pixels = await encode_image(source)
            if not pixels:
                raise ValueError('The selected image could not be decoded. No generation was queued.')
            if scope != self.output_scope:
                raise ValueError('The output folder changed. Refresh the gallery before trying again.')
            uploaded = await self.client.upload_image(pixels, 'comfyui-control-' + uuid.uuid4().hex + '.png')
            # LoadImage's combo list must include the newly uploaded input.
            await self.metadata(force=True)
            marker = {'action': action, 'source': name}
            preset = None
            required = {(m['key'], m['node'], m['input'], m['role']) for m in bindings}
            for entry in self.presets.list():
                saved = self.presets.get(entry['id'])
                mapped = {(m['key'], m['node'], m['input'], m['role']) for m in saved['mappings']}
                if saved.get('image_workflow') == marker and saved['graph'] == graph and required <= mapped:
                    preset = saved
                    break
            if preset is None:
                preset = self.presets.create(IMAGE_WORKFLOWS[action]['name'], graph)
                targets = {(m['node'], m['input']) for m in bindings}
                mappings = [m for m in suggested_mappings(graph, self.info) if (m['node'], m['input']) not in targets]
                preset = self.presets.map(preset['id'], mappings + bindings)
                preset['image_workflow'] = marker
                save_json(self.presets.path(preset['id']), preset)
            values = {'action-image': uploaded}
            if action == 'edit':
                values['action-prompt'] = instruction
            elif multiplier is not None:
                values['action-scale'] = multiplier
            if scope != self.output_scope:
                raise ValueError('The output folder changed. No generation was queued; refresh the gallery.')
            job = await self.submit({'request_id': request_id, 'preset': preset['id'], 'revision': revision(preset),
                                     'values': values, 'random_seed': False, 'disabled_loras': []}, owner, expected_scope=scope)
            return {'image_id': identifier, 'job': self.public_job(job)}

    async def image_action(self, identifier, owner, body):
        if not isinstance(body, dict):
            raise ValueError('Send an image action object.')
        action = body.get('action')
        if action == 'delete':
            action = 'trash'  # Retain the existing API key for older WebUI clients.
        if action not in {'keep', 'trash', 'edit', 'upscale'}:
            raise ValueError('Unknown image action.')
        if action in IMAGE_WORKFLOWS:
            return await self.run_image_workflow(identifier, owner, body)
        async with self.gallery_lock:
            scope = self.output_scope
            capabilities = self.image_action_capabilities(identifier, owner)
            capability = capabilities['actions'][action]
            if not capability['available']:
                raise ValueError(capability['reason'])
            item = dict(self.images[identifier])
            if body.get('modified') != item.get('modified', ''):
                raise ValueError('This image changed. Refresh the gallery before acting on it.')
            if action == 'keep':
                await asyncio.to_thread(self.image_library.mark, scope, owner, item, body.get('keep'))
                result = {'image_id': identifier, 'kept': body['keep']}
            elif action == 'trash':
                if body.get('confirm') is not True:
                    raise ValueError('Confirm deleting this specific image to the Wastebin.')
                if not item.get('modified'):
                    raise ValueError('Refresh the gallery before deleting this image.')
                try:
                    identity = json.loads(await self.network_io('identify', {'image': item}))
                except OSError as exc:
                    raise ValueError(f'Could not mark this image as deleted: {exc}. The original was not modified.') from None
                if scope != self.output_scope:
                    raise ValueError('The output folder changed. Nothing was marked as deleted.')
                if not self._metadata_allowed(item, owner, allow_shared=False):
                    raise ValueError('Image ownership changed. Nothing was marked as deleted.')
                record = await asyncio.to_thread(self.image_library.delete, scope, owner, item, identity)
                result = {'image_id': identifier, 'trash': self.public_trash(record)}
            else:
                raise ValueError('This image workflow has no configured execution handler.')
            self.gallery_time = 0
            if action == 'trash':
                self.broadcast()
            return result

    @staticmethod
    def public_trash(record):
        item = record['image']
        return dict(token=record['token'], filename=item['filename'], subfolder=item.get('subfolder', ''),
                    created=record['created'], error=record.get('error', ''),
                    thumbnail=f"/api/trash/{record['token']}/thumbnail")

    async def image_trash(self, owner, token=None):
        if not (self.local_comfy or self.network_output):
            raise ValueError('Wastebin is available only for the configured local or network output folder.')
        async with self.gallery_lock:
            scope = self.output_scope
            if token in self.image_library.deleted:
                record = self.image_library.entry(scope, owner, token)
                if record.get('legacy'):
                    try:
                        await self.network_io('restore', dict(owner=owner, scope=scope, token=token))
                    except OSError as exc:
                        raise ValueError(f'Could not restore the image: {exc}') from None
                await asyncio.to_thread(self.image_library.update_deleted, token)
                self.gallery_time = 0
                self.broadcast()
                return {'filename': record['image']['filename'], 'restored': True}
            if token is not None:
                raise ValueError('This Wastebin entry belongs to another browser or output folder, or is no longer available.')
            # Import old physically moved entries into the same local metadata.
            # Each browser/scope is checked once; listing virtual markers remains
            # available even if the old output folder cannot currently be read.
            key = (scope, owner)
            legacy_notice = ''
            if key not in self.legacy_trash_checked:
                try:
                    legacy = json.loads(await self.network_io('trash-list', dict(owner=owner, scope=scope), timeout=1))
                except OSError as exc:
                    if not self.image_library.entries(scope, owner):
                        raise ValueError(f'Could not read Wastebin on the output storage: {exc}') from None
                    legacy = []
                    legacy_notice = f'Older Wastebin entries could not be checked: {exc}'
                else:
                    legacy_notice = None
                if scope != self.output_scope:
                    raise ValueError('The output folder changed. Refresh Wastebin.')
                for entry in legacy:
                    if scope != self.output_scope:
                        raise ValueError('The output folder changed. Refresh Wastebin.')
                    if entry['token'] not in self.image_library.deleted:
                        item = dict(self.image_ref(dict(filename=entry['filename'], subfolder=entry['subfolder'], type='output')))
                        item['modified'] = str(entry['identity']['file'][3])
                        await asyncio.to_thread(self.image_library.delete, scope, owner, item, entry['identity'], entry)
                if legacy_notice is None:
                    self.legacy_trash_checked.add(key)
            entries = [self.public_trash(record) for record in self.image_library.entries(scope, owner)]
            if legacy_notice:
                for entry in entries:
                    entry['notice'] = legacy_notice
            return sorted(entries, key=lambda record: record['created'], reverse=True)

    async def wastebin_thumbnail(self, owner, token):
        async with self.gallery_lock:
            record = self.image_library.entry(self.output_scope, owner, token)
            return await self.network_io('legacy-read' if record.get('legacy') else 'wastebin-read', record)

    async def delete_permanently(self, owner, body, token=None):
        if not isinstance(body, dict) or body.get('confirm') is not True:
            raise ValueError('Explicitly confirm permanent deletion. This cannot be undone.')
        # Bulk confirmation covers the displayed snapshot only, never entries
        # added by another request while the operation is in flight.
        tokens = [token] if token is not None else body.get('tokens')
        if (not isinstance(tokens, list) or not tokens or len(tokens) > 2000
                or any(not isinstance(value, str) for value in tokens) or len(set(tokens)) != len(tokens)):
            raise ValueError('Choose the Wastebin entries to permanently delete.')
        if not (self.local_comfy or self.network_output):
            raise ValueError('Permanent deletion requires the configured local or network output folder.')
        async with self.gallery_lock:
            scope = self.output_scope
            # Authorize the entire snapshot before doing any filesystem work.
            records = [self.image_library.entry(scope, owner, value) for value in tokens]
            results = []
            blocked = None
            for record in records:
                if scope != self.output_scope:
                    message = 'The output folder changed. Deletion was not attempted; refresh Wastebin.'
                    await asyncio.to_thread(self.image_library.update_deleted, record['token'], {**record, 'error': message})
                    results.append(dict(token=record['token'], error=message))
                    continue
                try:
                    if blocked:
                        raise OSError(blocked)
                    if not self._metadata_allowed(record['image'], owner, allow_shared=False):
                        raise ValueError('Image ownership changed. Permanent deletion is not permitted.')
                    await self.network_io('legacy-delete' if record.get('legacy') else 'delete', record)
                except (OSError, ValueError) as exc:
                    if isinstance(exc, TimeoutError):
                        blocked = 'Storage timed out. Remaining deletions were not attempted.'
                    message = f'Could not delete {record["image"]["filename"]}: {exc}. Kept in Wastebin; check storage before retrying.'
                    await asyncio.to_thread(self.image_library.update_deleted, record['token'], {**record, 'error': message})
                    results.append(dict(token=record['token'], error=message))
                else:
                    # Keep a tombstone so journal replay cannot resurrect deleted
                    # outputs or let a retry remove a replacement at the same path.
                    await asyncio.to_thread(self.image_library.update_deleted, record['token'],
                                            {**record, 'purged': True, 'error': ''})
                    self.image_unavailable(record['image']['id'])
                    results.append(dict(token=record['token'], deleted=True))
            self.gallery_time = 0
            self.broadcast()
            return {'results': results}

    async def image_parameters(self, identifier, owner=None):
        from .image_metadata import parameters, png_parameters
        item = self.images.get(identifier)
        if not item:
            raise ValueError('Image is no longer available. Refresh the gallery.')
        if not self._metadata_allowed(item, owner):
            return []
        job = self.jobs.get(item.get('job'))
        if job:
            # Image sharing is handled by the same gate as Details and reuse.
            return parameters(job.get('controls',[]),job.get('values',{}))
        path = await self.network_io('read', item) if self.network_output else self.local_image(item)
        try:
            return await asyncio.to_thread(png_parameters,path,self.info)
        except OSError:
            return []

    def image_ownership_key(self, item):
        # Keep local-file ownership when the API URL/port changes. Public image
        # IDs still use the endpoint/output scope for normal session isolation.
        path = self.output_dir / item['subfolder'] / item['filename']
        return hashlib.sha256((item['type'] + ':' + str(path)).encode()).hexdigest()[:32]

    def _metadata_allowed(self, item, owner, *, allow_shared=True):
        if owner is None or allow_shared and self.settings.share_image_settings:
            return True
        job = self.jobs.get(item.get('job'))
        if job:
            return job.get('owner') == owner
        if not self.ownership_available:
            return False
        key = self.image_ownership_key(item)
        return key not in self.image_owners or self.image_owners[key] == owner

    def image_reuse_status(self, item, owner):
        if not self._metadata_allowed(item, owner):
            return dict(available=False, reason='Generation settings belong to another browser session. Enable image settings sharing in the desktop Mobile WebUI settings to reuse them across your devices.')
        job = self.jobs.get(item.get('job'), {})
        if job.get('preset') and job.get('revision') and isinstance(job.get('values'), dict):
            return dict(available=True, reason='')
        if item.get('type') == 'output' and self.local_comfy and Path(item['filename']).suffix.lower() == '.png':
            # Read the bounded PNG metadata only when reuse is requested, not
            # on every gallery refresh or for every thumbnail on a slow NAS.
            return dict(available=True, reason='')
        return dict(available=False, reason='No saved mobile settings or local ComfyUI PNG workflow are available for this image.')

    async def prepare_image_reuse(self, identifier, owner):
        from .image_metadata import png_graph
        item = self.images.get(identifier)
        if not item or identifier in self.unavailable_images or self.image_library.deleted_image(self.output_scope, item):
            raise ValueError('Image is no longer available. Refresh the gallery.')
        status = self.image_reuse_status(item, owner)
        if not status['available']:
            raise ValueError(status['reason'])
        job = self.jobs.get(item.get('job'), {})
        if job.get('preset') and job.get('revision') and isinstance(job.get('values'), dict):
            return {key: deepcopy(job.get(key, [] if key in {'controls', 'disabled_loras'} else {}))
                    for key in ('preset', 'revision', 'values', 'controls', 'disabled_loras')}
        scope = self.output_scope
        path = await self.network_io('read', item) if self.network_output else self.local_image(item)
        try:
            graph = await asyncio.to_thread(png_graph, path)
        except OSError:
            graph = None
        if graph is None:
            raise ValueError('This image has no usable ComfyUI API workflow saved in its PNG metadata. Use a PNG saved by ComfyUI with metadata enabled, or import its API workflow.')
        if scope != self.output_scope or not self._metadata_allowed(item, owner):
            raise ValueError('The output folder or image ownership changed. Refresh the gallery before reusing this image.')
        # Prefer the user's existing input mappings, but only when replacing
        # their mapped literals reproduces this exact saved graph. Unknown
        # nodes, connections and unmapped inputs must remain unchanged.
        preset = None
        for entry in self.presets.list():
            existing = self.presets.get(entry['id'])
            candidate = deepcopy(existing['graph'])
            for mapping in existing['mappings']:
                node, name = mapping['node'], mapping['input']
                if node not in graph or type(graph[node]['inputs'].get(name)) not in (str, int, float, bool):
                    break
                candidate[node]['inputs'][name] = graph[node]['inputs'][name]
            else:
                if json.dumps(candidate, sort_keys=True) == json.dumps(graph, sort_keys=True):
                    preset = existing
                    break
        if preset is None:
            if self.image_ownership_key(item) in self.image_owners and not self.settings.share_image_settings:
                raise ValueError('This image\'s mobile generation record is no longer available. Select an existing workflow with matching input mappings to reuse it.')
            preset = self.presets.create(('Image · ' + Path(item['filename']).stem)[:100], graph)
            preset = self.presets.map(preset['id'], suggested_mappings(graph, self.info), automatic=True)
            preset['image_reuse'] = True
            save_json(self.presets.path(preset['id']), preset)
        description = await self.describe(preset)
        return dict(preset=description['id'], revision=description['revision'], disabled_loras=[],
                    values={field['key']: graph[field['node']]['inputs'][field['input']] for field in description['fields']},
                    controls=description['fields'])

    async def image_details(self, identifier, owner=None):
        from .image_metadata import image_size, png_details
        item = self.images.get(identifier)
        if not item:
            raise ValueError('Image is no longer available. Refresh the gallery.')
        if not self._metadata_allowed(item, owner):
            return {'restricted': True, 'positive': [], 'negative': [], 'parameters': [], 'additional': []}
        job = self.jobs.get(item.get('job'))
        path = await self.network_io('read', item) if self.network_output else self.local_image(item)
        try:
            if job:
                result = deepcopy(job.get('metadata') or generation_details(job.get('controls',[]),job.get('values',{})))
                result.update(source='mobile', image=await asyncio.to_thread(image_size,path))
                return result
            if self.online and self.client and not self.info:
                try:
                    await asyncio.wait_for(self.metadata(), 3)
                except (ComfyError, asyncio.TimeoutError):
                    pass
            return await asyncio.to_thread(png_details,path,self.info)
        except OSError:
            return {'positive': [], 'negative': [], 'parameters': [], 'additional': [], 'unavailable': True}

    async def network_io(self, operation, data, timeout=8):
        worker = Path(__file__).parents[1] / 'network_output.py'
        return await run_background([sys.executable, '-I', str(worker), operation, str(self.output_dir)], data, timeout=timeout)

    def local_image(self, item, root=None):
        if self.network_output or item.get("type") != "output":
            return None
        root = self.output_dir if root is None else root
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
