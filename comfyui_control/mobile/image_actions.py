"""Saved-image capabilities and per-browser Keep marks, separate from job state.

Edit/upscale deliberately have no execution handler yet. Future integrations
must bind a verified source image to an existing preset, then use submit();
they must never replace the source file or introduce another queue.
"""
import hashlib
import json

from .settings import save_json


IMAGE_WORKFLOWS = {
    'edit': {'label': 'Edit', 'reason': 'Editing workflow is not configured yet.'},
    'upscale': {'label': 'Upscale', 'reason': 'Upscaling workflow is not configured yet.'},
}


def workflow_capabilities():
    return {key: {'available': False, **value} for key, value in IMAGE_WORKFLOWS.items()}


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
