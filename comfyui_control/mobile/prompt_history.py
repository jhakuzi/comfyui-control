"""Bounded prompt pairs, stored separately from jobs and scoped to browser identities."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .settings import save_json


class PromptHistory:
    max_entries = 200
    max_favorites = 100
    max_bytes = 4 * 1024**2

    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, owner):
        if not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise ValueError('Reopen the mobile page to restore your browser identity.')
        return self.directory / (owner + '.json')

    def list(self, owner):
        path = self.path(owner)
        if not path.exists():
            return []
        if path.stat().st_size > self.max_bytes:
            raise ValueError('Prompt history is too large to read safely.')
        entries = json.loads(path.read_text(encoding='utf-8'))
        valid = isinstance(entries, list) and all(
            isinstance(item, dict) and isinstance(item.get('id'), str) and re.fullmatch(r'[a-f0-9]{64}', item['id'])
            and type(item.get('updated')) in (int, float) and math.isfinite(item['updated'])
            and type(item.get('favorite')) is bool
            and all(isinstance(item.get(role), list) and all(isinstance(field, dict) and isinstance(field.get('value'), str)
                    and isinstance(field.get('label'), str) for field in item[role]) for role in ('positive', 'negative'))
            for item in entries)
        if not valid:
            raise ValueError('Prompt history could not be read. The existing file was kept.')
        return sorted(entries, key=lambda item: item['updated'], reverse=True)

    def _save(self, owner, entries, protected=None):
        while len(entries) > self.max_entries or len(json.dumps(entries, ensure_ascii=False).encode()) > self.max_bytes:
            index = next((i for i in range(len(entries)-1, -1, -1)
                          if not entries[i]['favorite'] and entries[i]['id'] != protected), None)
            if index is None:
                raise ValueError('Prompt history is full. Delete an entry or remove a favorite to make room.')
            entries.pop(index)
        save_json(self.path(owner), entries)

    def record(self, owner, controls, values):
        prompts = {role: [{'label': field.get('label', role)[:120], 'value': values[field['key']]}
                          for field in controls if field.get('role') == role and isinstance(values.get(field.get('key')), str)]
                   for role in ('positive', 'negative')}
        if not any(prompts.values()):
            return None
        if sum(len(field['value']) for fields in prompts.values() for field in fields) > 100000:
            raise ValueError('This prompt is too large for prompt history. The generation is still submitted.')
        identity = [[field['value'] for field in prompts[role]] for role in ('positive', 'negative')]
        identifier = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        entries = self.list(owner)
        previous = next((item for item in entries if item['id'] == identifier), {})
        now = time.time()
        entry = dict(id=identifier, **prompts, favorite=previous.get('favorite', False),
                     created=previous.get('created', now), updated=now)
        entries = [entry] + [item for item in entries if item['id'] != identifier]
        self._save(owner, entries, protected=identifier)
        return entry

    def favorite(self, owner, identifier, value):
        if type(value) is not bool:
            raise ValueError('Favorite must be true or false.')
        entries = self.list(owner)
        entry = next((item for item in entries if item['id'] == identifier), None)
        if entry is None:
            raise ValueError('This prompt is no longer in your history.')
        if value and not entry['favorite'] and sum(bool(item['favorite']) for item in entries) >= self.max_favorites:
            raise ValueError('Keep up to 100 favorites. Remove a favorite before adding another.')
        entry['favorite'] = value
        self._save(owner, entries)
        return entry

    def delete(self, owner, identifier):
        self._save(owner, [item for item in self.list(owner) if item['id'] != identifier])

    def clear(self, owner):
        self._save(owner, [])
