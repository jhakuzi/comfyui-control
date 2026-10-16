"""Read saved workflows; prefer exact API snapshots and validate metadata conversion."""
import asyncio
import json
from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import quote

from .workflows import graph_from


def editor_signature(workflow):
    """Ignore editor layout, but require matching execution-relevant saved data."""
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or any(not isinstance(n, dict) for n in nodes):
        raise ValueError("Choose a ComfyUI workflow JSON file.")
    # Retain unknown node/widget properties; only discard known layout fields.
    layout = {"pos", "size", "order", "color", "bgcolor", "title"}
    normalized = [{k: v for k, v in node.items() if k not in layout} for node in nodes]
    return json.dumps({"nodes": sorted(normalized, key=lambda n: str(n.get("id"))),
                       "links": workflow.get("links", []), "definitions": workflow.get("definitions")}, sort_keys=True)


async def queued_workflow(client, saved_editor=None):
    queue, history = await asyncio.gather(client.request("GET", "/queue"),
                                           client.request("GET", "/history?max_items=100"))
    # The newest queued graph wins; history supplies completed workflows too.
    records = [record.get("prompt", []) for record in history.values() if isinstance(record, dict)]
    records.extend(queue.get("queue_running", []))
    records.extend(queue.get("queue_pending", []))
    signature = editor_signature(saved_editor) if saved_editor is not None else None
    for prompt in reversed(records):
        if not isinstance(prompt, list) or len(prompt) < 4 or not isinstance(prompt[3], dict):
            continue
        if signature is not None:
            extra = prompt[3].get("extra_pnginfo")
            editor = extra.get("workflow") if isinstance(extra, dict) else None
            if not isinstance(editor, dict) or editor_signature(editor) != signature:
                continue
        try:
            return graph_from(prompt[2])
        except ValueError:
            continue
    if saved_editor is not None:
        raise ValueError("No exact executable copy of this saved workflow is in ComfyUI's recent queue/history. Run this saved workflow once in ComfyUI, then choose it again, or export it in API format. Custom widget inputs are not guessed.")
    raise ValueError("ComfyUI has no recent queued workflow. Run your workflow once in ComfyUI, or choose an API-format JSON file from this computer.")


def editor_to_api(editor, info):
    """Convert only metadata-described widgets. Ambiguous custom serialization fails closed."""
    graph = {}
    nodes = editor.get("nodes", [])
    definitions = editor.get("definitions") or {}
    if not isinstance(nodes, list) or not 0 < len(nodes) <= 3000 or not isinstance(definitions, dict) or definitions.get("subgraphs"):
        raise ValueError("This workflow needs ComfyUI's API export (subgraphs or unsupported editor data).")
    if any(not isinstance(n, dict) or type(n.get("id")) not in (str, int) for n in nodes) or len({str(n['id']) for n in nodes}) != len(nodes):
        raise ValueError("Saved workflow nodes need unique IDs.")
    links = {link[0]: link for link in editor.get("links", []) if isinstance(link, list) and len(link) >= 6}
    for node in nodes:
        name, node_id = node.get("type"), str(node.get("id"))
        if node.get("mode", 0) != 0 or name not in info:
            raise ValueError(f"Node {node_id} ({name}) requires ComfyUI's API export or an exact queued snapshot (missing metadata or bypass/mute mode).")
        schema = info[name].get("input", {})
        fields = {**schema.get("required", {}), **schema.get("optional", {})}
        values = deepcopy(node.get("widgets_values", []))
        if not isinstance(values, (list, dict)):
            raise ValueError(f"Node {node_id}: unsupported widget serialization; export in API format.")
        connections = {}
        for slot, entry in enumerate(node.get("inputs", [])):
            if entry.get("link") is None:
                continue
            link = links.get(entry["link"])
            if not link or str(link[3]) != node_id or link[4] != slot:
                raise ValueError(f"Node {node_id}: invalid saved connection.")
            connections[entry["name"]] = [str(link[1]), link[2]]
        inputs, index = {}, 0
        for key, definition in fields.items():
            if not isinstance(definition, (list, tuple)) or not definition:
                raise ValueError(f"Node {node_id}: incomplete input metadata for {key}; export in API format.")
            kind = definition[0]
            options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
            widget = (isinstance(kind, list) or kind in {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}) and not options.get("forceInput")
            if widget:
                if isinstance(values, dict):
                    if key not in values:
                        if key in connections:
                            inputs[key] = connections[key]
                            continue
                        raise ValueError(f"Node {node_id}: missing widget {key}; export in API format.")
                    value = values.pop(key)
                else:
                    if index >= len(values):
                        raise ValueError(f"Node {node_id}: widget order is ambiguous; export in API format.")
                    value = values[index]
                    index += 1
                    if options.get("control_after_generate") and index < len(values) and values[index] in ("fixed", "randomize", "increment", "decrement"):
                        index += 1
                choices = kind if isinstance(kind, list) else options.get("options")
                valid = value in choices if choices is not None else (
                    type(value) is int if kind == "INT" else type(value) in (int, float) if kind == "FLOAT" else
                    type(value) is bool if kind == "BOOLEAN" else isinstance(value, str))
                if not valid:
                    raise ValueError(f"Node {node_id}: {key} does not match its metadata; export in API format.")
                inputs[key] = value
            if key in connections:
                inputs[key] = connections[key]
            elif key in schema.get("required", {}) and key not in inputs:
                raise ValueError(f"Node {node_id}: missing required input {key}.")
        if (isinstance(values, list) and index != len(values)) or (isinstance(values, dict) and values) or set(connections) - set(fields):
            raise ValueError(f"Node {node_id}: custom widgets need ComfyUI's API export or an exact queued snapshot.")
        graph[node_id] = {"class_type": name, "inputs": inputs, "_meta": {"title": node.get("title", name)}}
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) not in graph:
                raise ValueError("Workflow contains a missing connection source.")
    return graph_from(graph)


async def import_graph(client, value):
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        return graph_from(value)
    try:
        return await queued_workflow(client, value)
    except ValueError:
        return editor_to_api(value, await client.request("GET", "/object_info"))


async def saved_workflows(client):
    names = await client.request("GET", "/userdata?dir=workflows&recurse=true", expected_type=list)
    return sorted({name for name in names if isinstance(name, str) and name.lower().endswith(".json")
                   and not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts and "\\" not in name})[:500]


async def saved_workflow_graph(client, name):
    if name not in await saved_workflows(client):
        raise ValueError("Choose a workflow from ComfyUI's saved workflow list.")
    value = await client.request("GET", "/userdata/" + quote("workflows/" + name, safe=""))
    return await import_graph(client, value)
