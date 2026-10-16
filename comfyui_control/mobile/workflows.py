"""Immutable API graphs and explicit, reusable mappings for arbitrary nodes."""
from copy import deepcopy
from collections import Counter
import json
import math
from pathlib import Path
import re
import secrets
import uuid

from .settings import save_json

ROLES = {"positive", "negative", "model", "lora_model", "lora_strength", "lora_enabled",
         "diffusion_model", "vae", "text_encoder", "sampler", "scheduler",
         "resolution_mp", "aspect_ratio", "alignment", "custom_ratio", "custom_aspect_ratio",
         "width", "height", "steps", "cfg", "seed", "batch", "advanced"}


def graph_from(value):
    if not isinstance(value, dict):
        raise ValueError("Import a ComfyUI API-format JSON object.")
    graph = value.get("prompt", value)
    if not isinstance(graph, dict) or not graph or "nodes" in graph:
        raise ValueError("This looks like node-editor JSON. Export the workflow in API format from ComfyUI first.")
    if len(graph) > 3000:
        raise ValueError("Workflow has too many nodes (maximum 3000).")
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ValueError("Each API node needs a class_type and an inputs object.")
    return deepcopy(graph)


def input_schema(graph, node_id, name, info):
    node = graph[node_id]
    inputs = info.get(node["class_type"], {}).get("input", {})
    definition = inputs.get("required", {}).get(name, inputs.get("optional", {}).get(name, []))
    return definition if isinstance(definition, (list, tuple)) else []


def candidates(graph, info):
    result = []
    for node_id, node in graph.items():
        title = node.get("_meta", {}).get("title", node["class_type"])
        for name, value in node["inputs"].items():
            # Connections, objects, and custom structures are never mapped automatically.
            if type(value) not in (str, int, float, bool):
                continue
            schema = input_schema(graph, node_id, name, info)
            limits = schema[1] if len(schema) > 1 and isinstance(schema[1], dict) else {}
            options = schema[0] if schema and isinstance(schema[0], list) else limits.get("options")
            result.append({"node": node_id, "input": name, "label": f"{title} · {name}",
                           "default": value, "kind": "bool" if type(value) is bool else "int" if type(value) is int else "float" if type(value) is float else "text",
                           "options": options, "min": limits.get("min"), "max": limits.get("max"), "step": limits.get("step")})
    return result


def validate_mappings(graph, mappings):
    if not isinstance(mappings, list) or len(mappings) > 200:
        raise ValueError("Mappings must be a list of at most 200 controls.")
    available = {(item["node"], item["input"]): item for item in candidates(graph, {})}
    targets = set()
    keys = set()
    result = []
    for index, item in enumerate(mappings):
        if not isinstance(item, dict) or item.get("role") not in ROLES:
            raise ValueError("Each mapping needs a supported control role.")
        target = (item.get("node"), item.get("input"))
        if target not in available or target in targets:
            raise ValueError("Map each literal input at most once. Node connections cannot be edited.")
        base = available[target]
        role = item["role"]
        if role in {"positive", "negative", "model", "lora_model", "diffusion_model", "vae", "text_encoder", "sampler", "scheduler", "aspect_ratio", "custom_aspect_ratio"} and base["kind"] != "text":
            raise ValueError(f"{role} must map to a text or model-name input.")
        if role in {"width", "height", "steps", "seed", "batch", "alignment"} and base["kind"] != "int":
            raise ValueError(f"{role} must map to an integer input.")
        if role in {"cfg", "lora_strength", "resolution_mp"} and base["kind"] not in {"int", "float"}:
            raise ValueError(f"{role} must map to a numeric input.")
        if role == "lora_enabled" and base["kind"] != "bool":
            raise ValueError("LoRA enabled must map to a boolean input.")
        key = item.get("key", f"field-{index}")
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key) or key in keys:
            raise ValueError("Control keys must be unique simple identifiers.")
        label = str(item.get("label", base["label"]))[:120]
        group = str(item.get("group", target[0]))[:80]
        result.append({"key": key, "node": target[0], "input": target[1], "role": role, "label": label, "group": group})
        keys.add(key)
        targets.add(target)
    return result


def suggested_mappings(graph):
    """Recognize literal input names; custom node classes/IDs remain unrestricted."""
    names = {
        "ckpt_name": ("model", "Checkpoint"), "unet_name": ("diffusion_model", "Diffusion model"),
        "diffusion_model": ("diffusion_model", "Diffusion model"), "vae_name": ("vae", "VAE"),
        "clip_name": ("text_encoder", "Text encoder"), "clip_name1": ("text_encoder", "Text encoder 1"),
        "clip_name2": ("text_encoder", "Text encoder 2"), "text_encoder_name": ("text_encoder", "Text encoder"),
        "sampler_name": ("sampler", "Sampler"), "scheduler": ("scheduler", "Scheduler"),
        "steps": ("steps", "Steps"), "cfg": ("cfg", "CFG"), "seed": ("seed", "Seed"),
        "guidance": ("cfg", "Guidance"),
        "noise_seed": ("seed", "Seed"), "width": ("width", "Width"), "height": ("height", "Height"),
        "batch_size": ("batch", "Batch size"), "lora_name": ("lora_model", "LoRA"),
        "strength_model": ("lora_strength", "Model strength"), "strength_clip": ("lora_strength", "CLIP strength"),
    }
    resolution = {"megapixel": ("resolution_mp", "Megapixels"), "megapixels": ("resolution_mp", "Megapixels"),
                  "resolution": ("resolution_mp", "Megapixels"), "aspect_ratio": ("aspect_ratio", "Aspect ratio"),
                  "divisible_by": ("alignment", "Divisible by"), "custom_ratio": ("custom_ratio", "Custom ratio"),
                  "custom_aspect_ratio": ("custom_aspect_ratio", "Custom aspect ratio")}
    prompt_nodes = {"positive": set(), "negative": set()}
    def trace(node_id, seen):
        found, pending = set(), [node_id]
        while pending:
            node_id = pending.pop()
            if node_id in seen or node_id not in graph:
                continue
            seen.add(node_id)
            inputs = graph[node_id]["inputs"]
            if isinstance(inputs.get("text"), str):
                found.add(node_id)
            pending.extend(value[0] for value in inputs.values() if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str))
        return found
    for node in graph.values():
        for role in prompt_nodes:
            value = node["inputs"].get(role)
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                prompt_nodes[role] |= trace(value[0], set())
    text_nodes = [key for key, node in graph.items() if isinstance(node["inputs"].get("text"), str)]
    result = []
    for field in candidates(graph, {}):
        inputs = graph[field["node"]]["inputs"]
        found = names.get(field["input"])
        if "aspect_ratio" in inputs and "divisible_by" in inputs:
            found = resolution.get(field["input"], found)
        if field["input"] == "text":
            roles = [role for role in prompt_nodes if field["node"] in prompt_nodes[role]]
            if len(roles) == 1:
                found = (roles[0], "Prompt" if roles[0] == "positive" else "Negative prompt")
            elif len(text_nodes) == 1:
                found = ("positive", "Prompt")
        if not found:
            continue
        role, label = found
        item = {"node": field["node"], "input": field["input"], "role": role, "label": label, "key": f"field-{len(result)}"}
        try:
            validate_mappings(graph, [item])
        except ValueError:
            continue
        result.append(item)
    counts = Counter(item["label"] for item in result)
    for item in result:
        if counts[item["label"]] > 1:
            source = graph[item["node"]]
            title = source.get("_meta", {}).get("title", source["class_type"])
            item["label"] += " · " + title
    return result[:200]


def fields_for(preset, info):
    available = {(c["node"], c["input"]): c for c in candidates(preset["graph"], info)}
    return [{**available[(m["node"], m["input"])], **m} for m in preset["mappings"]]


def render(preset, values, random_seed=False, disabled_loras=None, info=None):
    if not isinstance(values, dict) or type(random_seed) is not bool:
        raise ValueError("Invalid generation settings.")
    fields = fields_for(preset, info or {})
    if set(values) - {f["key"] for f in fields}:
        raise ValueError("Generation includes an unmapped input.")
    groups = {f["group"] for f in fields if f["role"] == "lora_strength"}
    disabled_loras = disabled_loras or []
    if not isinstance(disabled_loras, list) or any(g not in groups for g in disabled_loras):
        raise ValueError("Only LoRAs with mapped strength controls can be disabled.")
    graph, actual = deepcopy(preset["graph"]), {}
    for field in fields:
        value = values.get(field["key"], field["default"])
        if field["role"] == "seed" and random_seed:
            maximum = min(field["max"] if isinstance(field["max"], int) else 2**53 - 1, 2**53 - 1)
            minimum = max(field["min"] if isinstance(field["min"], int) else 0, 0)
            if maximum < minimum:
                raise ValueError("This seed input cannot use mobile randomization. Use a fixed seed.")
            value = minimum + secrets.randbelow(maximum - minimum + 1)
        if field["role"] == "lora_strength" and field["group"] in disabled_loras:
            value = 0 if field["kind"] == "int" else 0.0
        kind = field["kind"]
        if kind == "int" and isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,20}", value):
            value = int(value)
        if (kind == "bool" and type(value) is not bool or kind == "int" and type(value) is not int
                or kind == "float" and (type(value) not in (int, float) or abs(value) > 1e308 or not math.isfinite(value))
                or kind == "text" and (not isinstance(value, str) or len(value) > 20000)):
            raise ValueError(f"Invalid value for {field['label']}.")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if field["min"] is not None and value < field["min"] or field["max"] is not None and value > field["max"]:
                raise ValueError(f"{field['label']} is outside the node's allowed range.")
            if field["role"] in {"width", "height", "steps", "batch"} and value < 1:
                raise ValueError(f"{field['label']} must be positive.")
            if field["role"] == "batch" and value > 64:
                raise ValueError("Mobile batch size is limited to 64.")
        if field["options"] is not None and value not in field["options"]:
            raise ValueError(f"{field['label']} is not available in this ComfyUI installation.")
        graph[field["node"]]["inputs"][field["input"]] = value
        actual[field["key"]] = value
    return graph, actual


class Presets:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Invalid preset ID.")
        return self.directory / (identifier + ".json")

    def list(self):
        result = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                item = self.get(path.stem)
                result.append({"id": item["id"], "name": item["name"], "mapped": bool(item["mappings"])})
            except (ValueError, OSError, KeyError):
                continue
        return result

    def get(self, identifier):
        path = self.path(identifier)
        if not path.is_file():
            raise ValueError("Preset not found. Choose or import another workflow.")
        value = json.loads(path.read_text())
        graph_from(value["graph"])
        validate_mappings(value["graph"], value["mappings"])
        return value

    def create(self, name, graph):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Choose a preset name (up to 100 characters).")
        if len(self.list()) >= 100:
            raise ValueError("Maximum 100 presets. Remove an unused preset first.")
        item = {"id": uuid.uuid4().hex, "name": name.strip(), "graph": graph_from(graph), "mappings": []}
        save_json(self.path(item["id"]), item)
        return item

    def map(self, identifier, mappings):
        item = self.get(identifier)
        item["mappings"] = validate_mappings(item["graph"], mappings)
        save_json(self.path(identifier), item)
        return item
