"""Read saved workflows; prefer exact API snapshots and validate metadata conversion."""
import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .workflows import graph_from
from .input_metadata import expanded_inputs
from .editor_subgraphs import expand_subgraphs, link_table


def local_workflow_files(root):
    """Discover local JSON files without reading their contents or following symlinks."""
    root = Path(root)
    result, count = [], 0
    if not root.is_dir():
        return result
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if not (Path(folder) / d).is_symlink())
        for name in sorted(files):
            count += 1
            path = Path(folder) / name
            if path.suffix.lower() == ".json" and not path.is_symlink():
                result.append(str(path.relative_to(root)))
            if count >= 10000 or len(result) >= 500:
                return sorted(result)
    return sorted(result)


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


def _resolve_saved_connections(nodes, connections, info):
    """Omit muted outputs and follow only unambiguous, typed bypass paths.

    ComfyUI omits modes NEVER (2) and BYPASS (4) from its API graph. A bypass
    forwards a matching input, not the disabled node's widget values. Custom
    wildcard/type-list routing still needs an exact snapshot or API export.
    """
    by_id = {str(node["id"]): node for node in nodes}

    def input_type(node, entry):
        if "type" in entry:
            return entry["type"]
        schema = info.get(node.get("type"), {}).get("input", {})
        definition = {**schema.get("required", {}), **schema.get("optional", {})}.get(entry["name"], [])
        return definition[0] if isinstance(definition, (list, tuple)) and definition else None

    def resolve(source, target_type):
        visited = set()
        while True:
            node_id, slot = source
            if type(slot) is not int or slot < 0 or node_id not in by_id:
                raise ValueError("Workflow contains an invalid connection source.")
            node = by_id[node_id]
            if node.get("mode", 0) == 2:
                return None
            if node.get("mode", 0) != 4:
                return source
            if (node_id, slot) in visited:
                raise ValueError(f"Node {node_id}: circular bypass connection; fix it in ComfyUI.")
            visited.add((node_id, slot))
            outputs = node.get("outputs", [])
            metadata_outputs = info.get(node.get("type"), {}).get("output", [])
            output_type = (outputs[slot].get("type") if slot < len(outputs)
                           else metadata_outputs[slot] if slot < len(metadata_outputs) else None)
            entries = node.get("inputs", [])
            matches = [entry for entry in entries if input_type(node, entry) == target_type]
            if (not isinstance(target_type, str) or target_type in ("", "*") or "," in target_type
                    or output_type != target_type or len(matches) != 1):
                raise ValueError(f"Node {node_id} ({node.get('type')}): bypass routing is ambiguous or missing type metadata. Run this saved workflow once in ComfyUI and select it again, or export it in API format.")
            source = connections[node_id].get(matches[0]["name"])
            if source is None:
                return None

    resolved = {}
    for node_id, node in by_id.items():
        if node.get("mode", 0) not in (0, 2, 4):
            raise ValueError(f"Node {node_id}: unsupported execution mode; use ComfyUI's API export or an exact queued snapshot.")
        if node.get("mode", 0) != 0:
            continue
        resolved[node_id] = {}
        for entry in node.get("inputs", []):
            if entry["name"] not in connections[node_id]:
                continue
            source = resolve(connections[node_id][entry["name"]], input_type(node, entry))
            if source is not None:
                resolved[node_id][entry["name"]] = source
    return resolved


def editor_to_api(editor, info, *, retain_loras=False, base_graph=None):
    """Convert only metadata-described widgets. Ambiguous custom serialization fails closed."""
    graph = {}
    editor, literal_inputs = expand_subgraphs(editor)
    nodes = editor.get("nodes", [])
    definitions = editor.get("definitions") or {}
    if not isinstance(nodes, list) or not 0 < len(nodes) <= 3000 or not isinstance(definitions, dict) or definitions.get("subgraphs"):
        raise ValueError("This workflow needs ComfyUI's API export (subgraphs or unsupported editor data).")
    if any(not isinstance(n, dict) or type(n.get("id")) not in (str, int) for n in nodes) or len({str(n['id']) for n in nodes}) != len(nodes):
        raise ValueError("Saved workflow nodes need unique IDs.")
    retained = {}
    if retain_loras:
        # Only known, metadata-described LoRA loaders with unambiguous passthrough
        # sockets can be exposed as optional nodes. Unknown bypasses stay omitted.
        for node in nodes:
            metadata = info.get(node.get('type'), {})
            schema = metadata.get('input', {})
            fields = {**schema.get('required', {}), **schema.get('optional', {})}
            outputs = metadata.get('output', [])
            if (node.get('mode', 0) not in (0, 4) or 'lora_name' not in fields
                    or not {'strength_model', 'strength_clip'} & fields.keys()
                    or not outputs or any(kind not in ('MODEL', 'CLIP') for kind in outputs)):
                continue
            routes = {}
            for slot, kind in enumerate(outputs):
                matches = [entry['name'] for entry in node.get('inputs', [])
                           if entry.get('link') is not None and fields.get(entry['name'], [None])[0] == kind]
                if len(matches) != 1:
                    break
                routes[str(slot)] = matches[0]
            else:
                retained[str(node['id'])] = dict(bypassed=node.get('mode', 0) == 4, routes=routes)
                node['mode'] = 0
    if retain_loras and not retained and base_graph is not None:
        return graph_from(base_graph)
    links = link_table(editor.get('links', []))
    connections_by_node = {}
    for node in nodes:
        node_id, connections = str(node["id"]), {}
        for slot, entry in enumerate(node.get("inputs", [])):
            if entry.get("link") is None:
                continue
            link = links.get(str(entry["link"]))
            if not link or str(link[3]) != node_id or link[4] != slot:
                raise ValueError(f"Node {node_id}: invalid saved connection.")
            connections[entry["name"]] = [str(link[1]), link[2]]
        connections_by_node[node_id] = connections
    connections_by_node = _resolve_saved_connections(nodes, connections_by_node, info)
    roots = [str(node["id"]) for node in nodes if node.get("mode", 0) == 0
             and info.get(node.get("type"), {}).get("output_node") is True]
    required_nodes, pending = set(), list(roots)
    while pending:
        current = pending.pop()
        if current in required_nodes:
            continue
        required_nodes.add(current)
        pending.extend(value[0] for value in connections_by_node.get(current, {}).values())
    # Older/custom metadata may omit output flags; keep strict validation then.
    if not roots:
        required_nodes = set(connections_by_node)
    for node in nodes:
        name, node_id = node.get("type"), str(node.get("id"))
        if node.get("mode", 0) in (2, 4):
            continue
        if name not in info and name in {'Note', 'MarkdownNote'} and not node.get('inputs') and not node.get('outputs'):
            continue  # Native canvas notes are absent from ComfyUI API exports.
        if base_graph is not None and node_id in base_graph:
            # The exact snapshot owns opaque custom widget serialization. Only
            # restore its saved connections through the retained LoRA chain.
            graph[node_id] = deepcopy(base_graph[node_id])
            graph[node_id]['inputs'].update(connections_by_node[node_id])
            if node_id in retained:
                graph[node_id].setdefault('_meta', {})['control_lora'] = retained[node_id]
            continue
        if name not in info:
            raise ValueError(f"Node {node_id} ({name}): ComfyUI did not provide input metadata. Install/enable this node in ComfyUI, or use an API export or an exact queued snapshot.")
        schema = info[name].get("input", {})
        hints = node.get('widgets_values_named', {})
        if not isinstance(hints, dict):
            raise ValueError(f'Node {node_id}: invalid named widget data; export in API format.')
        if isinstance(node.get('widgets_values'), dict):
            hints = {**hints, **node['widgets_values']}
        elif not hints:
            declared = [entry['widget']['name'] for entry in node.get('inputs', []) if isinstance(entry.get('widget'), dict) and 'name' in entry['widget']]
            raw = node.get('widgets_values', [])
            if isinstance(raw, list) and len(raw) == len(declared):
                hints = dict(zip(declared, raw))
        overrides = literal_inputs.get(node_id, {})
        schema = expanded_inputs(schema, {**hints, **overrides})
        fields = {**schema.get("required", {}), **schema.get("optional", {})}
        values = deepcopy(node.get("widgets_values", []))
        if not isinstance(values, (list, dict)):
            raise ValueError(f"Node {node_id}: unsupported widget serialization; export in API format.")
        connections = connections_by_node[node_id]
        inputs, index = {}, 0
        for key, definition in fields.items():
            if not isinstance(definition, (list, tuple)) or not definition:
                raise ValueError(f"Node {node_id}: incomplete input metadata for {key}; export in API format.")
            kind = definition[0]
            options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
            if kind == 'IMAGECOMPARE' and options.get('socketless'):
                # Native empty comparison widgets have no saved values. Their
                # API representation is a UI-value wrapper, not a connection.
                if (isinstance(values, list) and index == len(values)) or (isinstance(values, dict) and key not in values):
                    inputs[key] = {'__value__': ['', '']}
                    continue
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
                value = overrides.get(key, value)
                choices = kind if isinstance(kind, list) else options.get("options")
                valid = value in choices if choices is not None else (
                    type(value) is int if kind == "INT" else type(value) in (int, float) if kind == "FLOAT" else
                    type(value) is bool if kind == "BOOLEAN" else isinstance(value, str))
                if not valid:
                    raise ValueError(f"Node {node_id}: {key} does not match its metadata; export in API format.")
                inputs[key] = value
            elif key in overrides:
                value = overrides[key]
                valid = (type(value) is int if kind == 'INT' else type(value) in (int, float) if kind == 'FLOAT'
                         else type(value) is bool if kind == 'BOOLEAN' else isinstance(value, str) if kind == 'STRING' else False)
                if not valid:
                    raise ValueError(f'Node {node_id}: promoted input {key} does not match its metadata.')
                inputs[key] = value
            if key in connections:
                inputs[key] = connections[key]
            elif node_id in required_nodes and key in schema.get("required", {}) and key not in inputs:
                raise ValueError(f"Node {node_id} ({name}): required input '{key}' is not connected in this saved workflow. Connect it in ComfyUI and save again, or use an API-format export.")
        upload = [entry for entry in node.get('inputs', []) if entry.get('type') == 'IMAGEUPLOAD'
                  and entry.get('name') not in fields and entry.get('link') is None]
        can_upload = any(isinstance(d, (list, tuple)) and len(d) > 1 and isinstance(d[1], dict)
                         and d[1].get('image_upload') for d in fields.values())
        if len(upload) == 1 and can_upload:
            if isinstance(values, list) and values[index:] == ['image']:
                index += 1
            elif isinstance(values, dict) and values.get(upload[0]['name']) == 'image':
                values.pop(upload[0]['name'])
        if (isinstance(values, list) and index != len(values)) or (isinstance(values, dict) and values) or set(connections) - set(fields):
            raise ValueError(f"Node {node_id}: custom widgets need ComfyUI's API export or an exact queued snapshot.")
        graph[node_id] = {"class_type": name, "inputs": inputs, "_meta": {"title": node.get("title", name)}}
    for node_id, settings in retained.items():
        if node_id in graph:
            graph[node_id].setdefault('_meta', {})['control_lora'] = settings
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


async def saved_workflow_graph(client, name, *, retain_loras=False):
    if name not in await saved_workflows(client):
        raise ValueError("Choose a workflow from ComfyUI's saved workflow list.")
    value = await client.request("GET", "/userdata/" + quote("workflows/" + name, safe=""))
    if retain_loras and isinstance(value, dict) and isinstance(value.get('nodes'), list):
        info = await client.request('GET', '/object_info')
        try:
            exact = await queued_workflow(client, value)
        except ValueError:
            exact = None
        return editor_to_api(value, info, retain_loras=True, base_graph=exact)
    return await import_graph(client, value)
