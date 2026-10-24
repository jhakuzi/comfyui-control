"""Saved-image capabilities and shared output-library marks, separate from job state.

Image workflow names and bindings are explicitly supplied by the user. Graphs
still come from ComfyUI; only these literal inputs are replaced for an action.
"""
import hashlib
import json
import time
import uuid
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


SHARED_LIBRARY_OWNER = hashlib.sha256(b'comfyui-control-shared-image-library').hexdigest()


class ImageLibrary:
    """Small atomic sidecar; existing presets, jobs and image files stay intact."""
    def __init__(self, path):
        self.path = path
        self.valid = True
        self.deleted = {}
        try:
            if path.stat().st_size > 4 * 1024**2:
                raise ValueError('Image library is too large.')
            self.kept = json.loads(path.read_text())
            if self.kept.get('version') == 2:
                saved = self.kept
                self.kept = saved['kept']
                self.deleted = saved['deleted']
                if not isinstance(self.deleted, dict) or not all(
                    isinstance(token, str) and isinstance(record, dict) and record.get('token') == token
                    and isinstance(record.get('owner'), str) and isinstance(record.get('scope'), str)
                    and isinstance(record.get('image'), dict) and isinstance(record.get('identity'), dict)
                    for token, record in self.deleted.items()
                ):
                    raise ValueError('Invalid Wastebin metadata.')
            if not isinstance(self.kept, dict) or not all(
                isinstance(key, str) and isinstance(value, dict) and
                all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
                for key, value in self.kept.items()
            ):
                raise ValueError('Invalid image library.')
        except FileNotFoundError:
            self.kept = {}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.deleted = {}
            self.kept = {}
            self.valid = False  # Never overwrite a damaged library automatically.
        self.index_kept()
        self.index_deleted()

    @staticmethod
    def key(scope, owner):
        return hashlib.sha256((scope + ':' + str(owner)).encode()).hexdigest()

    def contains(self, scope, owner, item):
        return self.kept.get(self.key(scope, owner), {}).get(item['id']) == item.get('modified', '')

    def index_kept(self):
        # Image IDs already include the controller/output scope. This also makes
        # old browser-owned marks visible before their first migration scan.
        self.kept_versions = {(identifier, modified) for entries in self.kept.values()
                              for identifier, modified in entries.items()}

    def contains_shared(self, item):
        return (item['id'], item.get('modified', '')) in self.kept_versions

    def merge_shared(self, scope, images):
        """Fold validated legacy marks into this output's shared bucket atomically."""
        if not self.valid:
            return  # Preserve corrupt metadata; mutations still fail closed.
        key = self.key(scope, SHARED_LIBRARY_OWNER)
        shared = dict(self.kept.get(key, {}))
        versions = {(item['id'], item.get('modified', '')) for item in images}
        updated = {}
        for source, entries in self.kept.items():
            if source == key:
                continue
            remaining = dict(entries)
            for identifier, modified in entries.items():
                if (identifier, modified) in versions:
                    shared[identifier] = modified
                    remaining.pop(identifier)
            updated[source] = remaining
        if shared or key in self.kept:
            updated[key] = shared
        if updated == self.kept:
            return
        self.save(updated, self.deleted)
        self.kept = updated
        self.index_kept()

    def mark_shared(self, scope, item, keep):
        # Remove old copies on an explicit update, otherwise an unhearted image
        # could reappear from another browser's pre-sharing bucket.
        key = self.key(scope, SHARED_LIBRARY_OWNER)
        entries = dict(self.kept.get(key, {}))
        if not self.valid:
            raise ValueError('The saved image library could not be read. Back it up before repairing it.')
        if type(keep) is not bool:
            raise ValueError('Favourite must be true or false.')
        if keep:
            if len(entries) >= 2000 and item['id'] not in entries:
                raise ValueError('Favourites is full (2,000 images). Remove a favourite first.')
            entries[item['id']] = item.get('modified', '')
        else:
            entries.pop(item['id'], None)
        updated = {source: {identifier: modified for identifier, modified in values.items() if identifier != item['id']}
                   for source, values in self.kept.items() if source != key}
        updated[key] = entries
        self.save(updated, self.deleted)
        self.kept = updated
        self.index_kept()

    def mark(self, scope, owner, item, keep):
        if not self.valid:
            raise ValueError('The saved image library could not be read. Back it up before repairing it.')
        if type(keep) is not bool:
            raise ValueError('Favourite must be true or false.')
        key = self.key(scope, owner)
        entries = dict(self.kept.get(key, {}))
        if keep:
            if len(entries) >= 2000 and item['id'] not in entries:
                raise ValueError('Favourites is full (2,000 images). Remove a favourite first.')
            entries[item['id']] = item.get('modified', '')
        else:
            entries.pop(item['id'], None)
        updated = {**self.kept, key: entries}
        if len(json.dumps(updated).encode()) > 4 * 1024**2:
            raise ValueError('The saved image library is full. Remove some favourites first.')
        self.save(updated, self.deleted)
        self.kept = updated
        self.index_kept()

    def save(self, kept, deleted):
        if not self.valid:
            raise ValueError('The saved image library could not be read. Back it up before repairing it.')
        updated = dict(version=2, kept=kept, deleted=deleted)
        if len(json.dumps(updated).encode()) > 4 * 1024**2:
            raise ValueError('The saved image library is full.')
        save_json(self.path, updated)

    def index_deleted(self):
        # Derived indexes keep gallery/SSE filtering independent of bin size.
        self.deleted_versions = {(record['scope'], record['image'].get('id'), record['image'].get('modified'))
                                 for record in self.deleted.values()}
        self.deleted_ids = {(scope, identifier) for scope, identifier, _ in self.deleted_versions}

    def deleted_image(self, scope, item):
        # Job journals may not yet contain a filesystem timestamp.
        if not item.get('modified'):
            return (scope, item.get('id')) in self.deleted_ids
        return (scope, item.get('id'), item['modified']) in self.deleted_versions

    def entries(self, scope, owner, *, shared=False):
        return [record for record in self.deleted.values()
                if record['scope'] == scope and (shared or record['owner'] == owner) and not record.get('purged')]

    def entry(self, scope, owner, token, *, shared=False):
        record = self.deleted.get(token)
        if not record or record['scope'] != scope or (not shared and record['owner'] != owner) or record.get('purged'):
            boundary = 'output folder' if shared else 'browser or output folder'
            raise ValueError(f'This Wastebin entry belongs to another {boundary}, or is no longer available.')
        return record

    def delete(self, scope, owner, item, identity, legacy=None):
        updated = dict(self.deleted)
        if len(updated) >= 2000:
            # Finished tombstones can age out; active/failed markers never do.
            finished = sorted((entry for entry in updated.values() if entry.get('purged')),
                              key=lambda entry: entry['created'])
            for entry in finished[:len(updated) - 1999]:
                updated.pop(entry['token'])
        if len(updated) >= 2000:
            raise ValueError('Wastebin is full (2,000 images). Restore or permanently delete some images first.')
        record = dict(token=legacy['token'] if legacy else uuid.uuid4().hex, scope=scope, owner=owner, image=item,
                      identity=identity, created=legacy['created'] if legacy else time.time(), error='', legacy=bool(legacy))
        updated[record['token']] = record
        self.save(self.kept, updated)
        self.deleted = updated
        self.index_deleted()
        return record

    def update_deleted(self, token, record=None):
        updated = dict(self.deleted)
        if record is None:
            updated.pop(token, None)
        else:
            updated[token] = record
        self.save(self.kept, updated)
        self.deleted = updated
        self.index_deleted()
