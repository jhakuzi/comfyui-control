"""Saved-image capabilities and per-browser Keep marks, separate from job state.

Image workflow names and bindings are explicitly supplied by the user. Graphs
still come from ComfyUI; only these literal inputs are replaced for an action.
"""
import hashlib
import json
from pathlib import PurePosixPath

from .settings import save_json


IMAGE_WORKFLOWS = {
    'edit': {'label': 'Edit', 'name': 'VeryComfy_Qwen21_Turbo_EDIT_ONLY',
             'image': ('88', 'image'), 'prompt': ('89', 'prompt')},
    'upscale': {'label': 'Upscale', 'name': 'OfficialComfy-SeedVR_Upscaler',
                'image': ('1', 'image')},
}


def workflow_capabilities():
    return {key: {'available': False, 'label': value['label'], 'workflow': value['name'],
                  'reason': f"{'Editing' if key == 'edit' else 'Upscaling'} workflow is not configured yet. "
                            f"Save {value['name']}.json in ComfyUI's Workflows list, then refresh this page."}
            for key, value in IMAGE_WORKFLOWS.items()}


def workflow_name(action, names):
    expected = IMAGE_WORKFLOWS[action]['name']
    # The editable workflow remains the source of truth. API companions are a
    # fallback for unsupported editor formats, not a replacement for new edits.
    for filename in (expected + '.json', expected + '.api.json'):
        if filename in names:
            return filename
        matches = [name for name in names if PurePosixPath(name).name == filename]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f'Multiple saved workflows are named {filename}. Keep one uniquely named copy.')
    raise ValueError(workflow_capabilities()[action]['reason'])


def workflow_import_error(action, name, error):
    expected = IMAGE_WORKFLOWS[action]['name']
    return (f'Could not prepare {name}: {error} '
            'Nothing was queued. First open this exact saved workflow in ComfyUI, run it once, then retry here. '
            'If it still fails, use ComfyUI\'s Export (API) / Save (API Format) option '
            '(enable Dev Mode in ComfyUI settings if it is hidden). '
            f'Save that API export as {expected}.api.json in the same ComfyUI user workflows folder '
            '(normally ComfyUI/user/default/workflows/), then refresh this WebUI. '
            'Keep the original editor workflow; renaming editor JSON alone will not convert it.')


def workflow_bindings(action, graph):
    """Validate the supplied API entries; never repair/reconnect an unknown graph."""
    config = IMAGE_WORKFLOWS[action]
    image_node, image_input = config['image']
    node = graph.get(image_node, {})
    if node.get('class_type') != 'LoadImage' or not isinstance(node.get('inputs', {}).get(image_input), str):
        raise ValueError(f"{config['name']} needs LoadImage node {image_node}, input {image_input}. "
                         'Its saved inputs differ from the configured image binding.')
    bindings = [dict(node=image_node, input=image_input, role='advanced', key='action-image', label='Source image')]
    if action == 'edit':
        prompt_node, prompt_input = config['prompt']
        node = graph.get(prompt_node, {})
        connection = node.get('inputs', {}).get('images.image_1')
        if (node.get('class_type') != 'TextEncodeQwenImage21'
                or not isinstance(node.get('inputs', {}).get(prompt_input), str)
                or not isinstance(connection, list) or len(connection) != 2
                or str(connection[0]) != image_node or connection[1] != 0):
            raise ValueError(f"{config['name']} needs TextEncodeQwenImage21 node {prompt_node}, input {prompt_input}, "
                             f'with images.image_1 connected to node {image_node}, output 0. No connections were changed.')
        bindings.append(dict(node=prompt_node, input=prompt_input, role='positive', key='action-prompt', label='Edit instruction'))
    return bindings


def upscale_multiplier_binding(graph):
    targets = [(node_id, name, value) for node_id, node in graph.items() for name, value in node['inputs'].items()
               if name == 'scale_multiplier' or (name == 'resize_type.multiplier'
                                                and node['inputs'].get('resize_type') == 'scale by multiplier')]
    if len(targets) != 1:
        raise ValueError('The upscale workflow needs exactly one multiplier input (scale_multiplier or resize_type.multiplier in scale-by-multiplier mode). '
                         'Leave the multiplier blank to use the saved workflow settings.')
    node_id, name, value = targets[0]
    if type(value) not in (int, float):
        raise ValueError(f'Node {node_id}: {name} must be a numeric literal, not a connection. '
                         'Leave the multiplier blank to preserve the saved workflow.')
    return dict(node=node_id, input=name, role='advanced', key='action-scale', label='Upscale multiplier')


class ImageLibrary:
    """Small atomic sidecar; existing presets, jobs and image files stay intact."""
    def __init__(self, path):
        self.path = path
        self.valid = True
        try:
            if path.stat().st_size > 4 * 1024**2:
                raise ValueError('Image library is too large.')
            self.kept = json.loads(path.read_text())
            if not isinstance(self.kept, dict) or not all(
                isinstance(key, str) and isinstance(value, dict) and
                all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
                for key, value in self.kept.items()
            ):
                raise ValueError('Invalid image library.')
        except FileNotFoundError:
            self.kept = {}
        except (OSError, ValueError):
            self.kept = {}
            self.valid = False  # Never overwrite a damaged library automatically.

    @staticmethod
    def key(scope, owner):
        return hashlib.sha256((scope + ':' + str(owner)).encode()).hexdigest()

    def contains(self, scope, owner, item):
        return self.kept.get(self.key(scope, owner), {}).get(item['id']) == item.get('modified', '')

    def mark(self, scope, owner, item, keep):
        if not self.valid:
            raise ValueError('The saved image library could not be read. Back it up before repairing it.')
        if type(keep) is not bool:
            raise ValueError('Keep must be true or false.')
        key = self.key(scope, owner)
        entries = dict(self.kept.get(key, {}))
        if keep:
            if len(entries) >= 2000 and item['id'] not in entries:
                raise ValueError('The Kept list is full (2,000 images). Remove a mark first.')
            entries[item['id']] = item.get('modified', '')
        else:
            entries.pop(item['id'], None)
        updated = {**self.kept, key: entries}
        if len(json.dumps(updated).encode()) > 4 * 1024**2:
            raise ValueError('The saved image library is full. Remove some Keep marks first.')
        save_json(self.path, updated)
        self.kept = updated
