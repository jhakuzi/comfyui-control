"""Expand ComfyUI's declared dynamic inputs without inventing node-specific fields."""
from copy import deepcopy


def expanded_inputs(schema, values, prefix='', depth=0):
    if depth > 12:
        raise ValueError('Dynamic input nesting is too deep. Use a ComfyUI API export.')
    result = {'required': {}, 'optional': {}}
    for category in result:
        for name, definition in schema.get(category, {}).items():
            key = prefix + name
            if not isinstance(definition, (list, tuple)) or not definition:
                result[category][key] = definition
                continue
            kind = definition[0]
            options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
            if kind == 'COMFY_DYNAMICCOMBO_V3':
                choices = options.get('options', [])
                if not isinstance(choices, list) or any(not isinstance(item, dict) or not isinstance(item.get('key'), str) for item in choices):
                    raise ValueError(f'Input {key}: unsupported dynamic choices. Use a ComfyUI API export.')
                result[category][key] = [[item['key'] for item in choices], {k: v for k, v in options.items() if k != 'options'}]
                selected = next((item for item in choices if item['key'] == values.get(key)), None)
                if selected:
                    nested = expanded_inputs(selected.get('inputs', {}), values, key + '.', depth + 1)
                    for group in result:
                        result[group].update(nested[group])
            elif kind == 'COMFY_AUTOGROW_V3':
                template = options.get('template', {})
                names = template.get('names')
                if names is None and isinstance(template.get('prefix'), str) and type(template.get('max')) is int:
                    if not 1 <= template['max'] <= 100:
                        raise ValueError(f'Input {key}: invalid dynamic slot limit.')
                    names = [template['prefix'] + str(i) for i in range(template['max'])]
                if (not isinstance(names, list) or len(names) > 100 or any(not isinstance(n, str) for n in names)
                        or len(set(names)) != len(names)):
                    raise ValueError(f'Input {key}: unsupported dynamic slot names. Use a ComfyUI API export.')
                entries = [(group, item) for group in result for item in template.get('input', {}).get(group, {}).values()]
                if len(entries) != 1:
                    raise ValueError(f'Input {key}: unsupported dynamic slot template. Use a ComfyUI API export.')
                group, item = entries[0]
                minimum = template.get('min', 0)
                if type(minimum) is not int or not 0 <= minimum <= len(names):
                    raise ValueError(f'Input {key}: invalid dynamic slot count.')
                for index, name in enumerate(names):
                    target = 'required' if group == 'required' and index < minimum else 'optional'
                    result[target][key + '.' + name] = deepcopy(item)
            else:
                result[category][key] = definition
    return result
