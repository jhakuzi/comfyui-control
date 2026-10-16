"""Allowlisted comparison parameters; never return prompts or arbitrary PNG text."""
import json

from PySide6.QtGui import QImageReader

from .workflows import fields_for, graph_from, suggested_mappings

LABELS = {'model':'Checkpoint', 'diffusion_model':'Diffusion model', 'vae':'VAE', 'text_encoder':'Text encoder',
          'sampler':'Sampler', 'scheduler':'Scheduler', 'steps':'Steps', 'cfg':'CFG', 'seed':'Seed',
          'width':'Width', 'height':'Height', 'resolution_mp':'Megapixels', 'aspect_ratio':'Aspect ratio',
          'lora_model':'LoRA', 'lora_strength':'LoRA strength'}


def parameters(controls, values):
    result, counts = [], {}
    for field in controls:
        role, key = field.get('role'), field.get('key')
        value = values.get(key)
        if role not in LABELS or type(value) not in (str, int, float, bool):
            continue
        count = counts.get(role, 0)
        counts[role] = count + 1
        result.append({'key':f'{role}:{count}', 'label':LABELS[role] + (f' {count+1}' if count else ''), 'value':value})
    return result


def png_parameters(path, info):
    if path is None or path.suffix.lower() != '.png' or path.stat().st_size > 100 * 1024**2:
        return []
    reader = QImageReader(str(path))
    text = reader.text('prompt')
    if not text or len(text) > 1024**2:
        return []
    try:
        graph = graph_from(json.loads(text))
        fields = fields_for({'graph':graph, 'mappings':suggested_mappings(graph,info)},info)
        return parameters(fields,{field['key']:field['default'] for field in fields})
    except (ValueError, KeyError, TypeError):
        return []
