"""Shared PNG parsing, comparison parameters and owner-gated generation details."""
import json
import math
import re

from PySide6.QtGui import QImageReader
from PySide6.QtCore import QBuffer, QIODevice


def image_reader(source):
    if isinstance(source, bytes):
        buffer = QBuffer()
        buffer.setData(source)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        reader._source_buffer = buffer  # Keep the device alive with the reader.
        return reader
    return QImageReader(str(source))

from .workflows import candidates, fields_for, graph_from, suggested_mappings

LABELS = {'model':'Checkpoint', 'diffusion_model':'Diffusion model', 'vae':'VAE', 'text_encoder':'Text encoder',
          'sampler':'Sampler', 'scheduler':'Scheduler', 'steps':'Steps', 'cfg':'CFG', 'seed':'Seed',
          'width':'Width', 'height':'Height', 'resolution_mp':'Megapixels', 'aspect_ratio':'Aspect ratio',
          'lora_model':'LoRA', 'lora_strength':'LoRA strength'}


def parameters(controls, values):
    result, counts = [], {}
    for field in controls:
        role, key = field.get('role'), field.get('key')
        value = values.get(key)
        if role not in LABELS or type(value) not in (str, int, float, bool) or type(value) is float and not math.isfinite(value):
            continue
        count = counts.get(role, 0)
        counts[role] = count + 1
        result.append({'key':f'{role}:{count}', 'label':LABELS[role] + (f' {count+1}' if count else ''), 'value':value})
    return result


def png_graph(path):
    if path is None:
        return None
    if isinstance(path, bytes):
        if len(path) > 100 * 1024**2 or not path.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
    elif path.suffix.lower() != '.png' or path.stat().st_size > 100 * 1024**2:
        return None
    reader = image_reader(path)
    text = reader.text('prompt')
    if not text or len(text) > 1024**2:
        return None
    try:
        return graph_from(json.loads(text))
    except (ValueError, KeyError, TypeError):
        return None


def png_parameters(path, info):
    graph = png_graph(path)
    if graph is None:
        return []
    fields = fields_for({'graph':graph, 'mappings':suggested_mappings(graph,info)},info)
    return parameters(fields,{field['key']:field['default'] for field in fields})


def generation_details(controls, values, graph=None, info=None):
    """Mapped text is explicit. Unmapped custom inputs expose only numbers/bools
    or schema-enumerated choices, never arbitrary text or credential-like inputs.
    """
    controls = [{**field, 'role':field.get('model_role',field.get('role'))} for field in controls]
    values = dict(values)
    if graph:
        mapped = {(field.get('node'),field.get('input')) for field in controls}
        inferred = fields_for({'graph':graph, 'mappings':suggested_mappings(graph,info)},info or {})
        for index, field in enumerate(inferred):
            if (field['node'],field['input']) in mapped:
                continue
            key = f'inspector-{index}'
            while key in values:
                key += '-extra'
            controls.append({**field, 'key':key})
            values[key] = field['default']
    result = {'positive': [], 'negative': [], 'parameters': parameters(controls, values), 'additional': [], 'loras': []}
    groups = {}
    for field in controls:
        role, value = field.get('role',''), values.get(field.get('key'))
        if role.startswith('lora_') and type(value) in (str,int,float,bool) and not (type(value) is float and not math.isfinite(value)):
            group = field.get('group',field.get('node','LoRAs'))
            groups.setdefault(group,[]).append({'label':field.get('label',role), 'value':value, 'role':role})
    for index, fields in enumerate(groups.values()):
        name = next((field['value'] for field in fields if field['role']=='lora_model'),f'LoRA {index+1}')
        result['loras'].append({'name':name,'fields':fields})
    targets = {(field.get('node'), field.get('input')) for field in controls}
    sensitive = re.compile(r'password|passwd|token|secret|api.?key|credential|authorization|cookie|header|url|directory|path', re.I)
    for field in controls:
        role, key = field.get('role'), field.get('key')
        value = values.get(key)
        if role in ('positive', 'negative') and isinstance(value, str):
            result[role].append({'label':field.get('label',role), 'value':value})
        elif role not in LABELS and role not in ('positive', 'negative') and not sensitive.search(field.get('input','') + field.get('label','')):
            if type(value) in (str, int, float, bool) and (not isinstance(value,str) or len(value)<=2000) and not (type(value) is float and not math.isfinite(value)):
                result['additional'].append({'label':field.get('label',key), 'value':value})
    if graph:
        for field in candidates(graph, info or {}):
            if len(result['additional']) >= 200:
                break
            if (field['node'],field['input']) in targets or sensitive.search(field['input']):
                continue
            value = field['default']
            if type(value) in (int, float, bool) or field['options'] and value in field['options']:
                if type(value) is float and not math.isfinite(value):
                    continue
                result['additional'].append({'label':field['label'], 'value':value})
    return result


def image_size(path):
    if path is None or (len(path) if isinstance(path, bytes) else path.stat().st_size) > 100 * 1024**2:
        return None
    size = image_reader(path).size()
    return {'width':size.width(), 'height':size.height()} if size.isValid() else None


def png_details(path, info):
    graph = png_graph(path)
    fields = fields_for({'graph':graph, 'mappings':suggested_mappings(graph,info)},info) if graph else []
    result = generation_details(fields,{field['key']:field['default'] for field in fields},graph,info)
    result.update(image=image_size(path), source='png' if graph else None)
    return result
