"""Resolution dropdowns retain their native types and linked latent dimensions."""
import asyncio
from copy import deepcopy
import time

import pytest

from comfyui_control.mobile.service import MobileService, revision
from comfyui_control.mobile.settings import MobileSettings, save_json
from comfyui_control.mobile.workflow_sources import editor_to_api
from comfyui_control.mobile.workflows import (
    fields_for, render, suggested_mappings, validate_mappings, with_resolution_controls,
)


@pytest.fixture
def controlaltai_resolution():
    # ControlAltAI FluxResolutionNode declares numeric values as STRING combos,
    # not FLOAT/INT widgets. Use its choices, with the user's reported defaults.
    ratios = ['1:1 (Perfect Square)', '2:3 (Classic Portrait)', '3:4 (Golden Ratio)',
              '3:5 (Elegant Vertical)', '4:5 (Artistic Frame)', '5:7 (Balanced Portrait)',
              '5:8 (Tall Portrait)', '7:9 (Modern Portrait)', '9:16 (Slim Vertical)',
              '9:19 (Tall Slim)', '9:21 (Ultra Tall)', '9:32 (Skyline)',
              '3:2 (Golden Landscape)', '4:3 (Classic Landscape)', '5:3 (Wide Horizon)',
              '5:4 (Balanced Frame)', '7:5 (Elegant Landscape)', '8:5 (Cinematic View)',
              '9:7 (Artful Horizon)', '16:9 (Panorama)', '19:9 (Cinematic Ultrawide)',
              '21:9 (Epic Ultrawide)', '32:9 (Extreme Ultrawide)']
    graph = {
        '59': {'class_type': 'FluxResolutionNode', 'inputs': {
            'megapixel': '2.0', 'aspect_ratio': '2:3 (Classic Portrait)',
            'divisible_by': '64', 'custom_ratio': False, 'custom_aspect_ratio': '1:1'}},
        '60': {'class_type': 'EmptySD3LatentImage', 'inputs': {
            'width': ['59', 0], 'height': ['59', 1], 'batch_size': 1}},
        '6': {'class_type': 'Text', 'inputs': {'text': 'A landscape'}},
        '3': {'class_type': 'Sampler', 'inputs': {'latent_image': ['60', 0], 'positive': ['6', 0]}},
    }
    info = {
        'FluxResolutionNode': {'input': {'required': {
            'megapixel': [[f'{i / 10:.1f}' for i in range(1, 26)], {'default': '1.0'}],
            'aspect_ratio': [ratios, {'default': ratios[0]}],
            'divisible_by': [['8', '16', '32', '64'], {'default': '64'}],
            'custom_ratio': ['BOOLEAN', {'default': False}]},
            'optional': {'custom_aspect_ratio': ['STRING', {'default': '1:1'}]}},
            'output': ['INT', 'INT', 'STRING', 'IMAGE']},
        'EmptySD3LatentImage': {'input': {'required': {
            'width': ['INT'], 'height': ['INT'], 'batch_size': ['INT']}}},
        'Text': {'input': {'required': {'text': ['STRING']}}},
        'Sampler': {'input': {'required': {'latent_image': ['LATENT'], 'positive': ['CONDITIONING']}}},
    }
    return graph, info


def test_native_resolution_combos_and_links(controlaltai_resolution):
    graph, info = controlaltai_resolution
    original = deepcopy(graph)
    mappings = validate_mappings(graph, suggested_mappings(graph, info))
    preset = {'graph': graph, 'mappings': mappings}
    fields = {f['role']: f for f in fields_for(preset, info)}
    assert fields['resolution_mp']['default'] == '2.0'
    assert fields['resolution_mp']['kind'] == 'text'
    assert fields['alignment']['options'] == ['8', '16', '32', '64']
    assert fields['custom_ratio']['kind'] == 'bool'
    assert 'width' not in fields and 'height' not in fields
    values = {fields[role]['key']: value for role, value in {
        'resolution_mp': '1.5', 'aspect_ratio': '16:9 (Panorama)',
        'alignment': '32', 'custom_ratio': True, 'custom_aspect_ratio': '7:5'}.items()}
    changed, _ = render(preset, values, info=info)
    assert changed['59']['inputs'] == {'megapixel': '1.5', 'aspect_ratio': '16:9 (Panorama)',
        'divisible_by': '32', 'custom_ratio': True, 'custom_aspect_ratio': '7:5'}
    assert changed['60'] == graph['60'] and changed['3'] == graph['3'] and graph == original
    for role, value in [('resolution_mp', '3.0'), ('alignment', '128'), ('aspect_ratio', 'invented')]:
        with pytest.raises(ValueError, match='not available'):
            render(preset, {fields[role]['key']: value}, info=info)
    with pytest.raises(ValueError, match='Invalid value'):
        render(preset, {fields['resolution_mp']['key']: 1.5}, info=info)


def test_resolution_editor_widgets_preserve_types_and_connections(controlaltai_resolution):
    graph, info = controlaltai_resolution
    editor = {'nodes': [
        {'id': 59, 'type': 'FluxResolutionNode', 'widgets_values': list(graph['59']['inputs'].values())},
        {'id': 60, 'type': 'EmptySD3LatentImage', 'widgets_values': [1024, 1024, 1],
         'inputs': [{'name': 'width', 'link': 1}, {'name': 'height', 'link': 2}]}],
        'links': [[1, 59, 0, 60, 0, 'INT'], [2, 59, 1, 60, 1, 'INT']]}
    original = deepcopy(editor)
    converted = editor_to_api(editor, info)
    assert converted == {key: {**graph[key], '_meta': {'title': graph[key]['class_type']}}
                         for key in ('59', '60')}
    assert editor == original


def test_existing_resolution_mapping_keeps_key_and_role(controlaltai_resolution):
    graph, info = controlaltai_resolution
    preset = {'graph': graph, 'mappings': validate_mappings(graph, [
        {'node': '59', 'input': 'megapixel', 'role': 'advanced', 'key': 'my-mp', 'label': 'My size'}])}
    upgraded = with_resolution_controls(preset, info)
    assert upgraded['mappings'][0] == preset['mappings'][0]
    assert len(upgraded['mappings']) == 5
    field = next(f for f in fields_for(upgraded, info) if f['key'] == 'my-mp')
    assert field['resolution_role'] == 'resolution_mp' and field['role'] == 'advanced'
    assert with_resolution_controls(upgraded, info) == upgraded
    # Recognition follows the input schema, not node IDs or class names.
    other = deepcopy(preset)
    other['graph']['calculator'] = other['graph'].pop('59')
    other['graph']['calculator']['class_type'] = 'AnotherResolutionPlugin'
    assert any(m['node'] == 'calculator' and m['role'] == 'resolution_mp'
               for m in suggested_mappings(other['graph']))


def test_legacy_resolution_upgrade_and_explicit_hide(tmp_path, controlaltai_resolution):
    graph, info = controlaltai_resolution

    async def scenario():
        service = MobileService(tmp_path / 'data', MobileSettings(require_auth=False), tmp_path / 'out')
        legacy = service.presets.create('VeryComfy', graph)
        legacy = service.presets.map(legacy['id'], [
            {'node': '6', 'input': 'text', 'role': 'positive', 'key': 'resolution-1', 'label': 'My prompt'}])
        # Simulate a persisted pre-upgrade preset (already at the loader version).
        legacy.pop('resolution_controls_version')
        save_json(service.presets.path(legacy['id']), legacy)
        service.info, service.info_time = info, time.monotonic()
        described = await service.describe(legacy)
        stored = service.presets.get(legacy['id'])
        assert described['model_upgrade_revision'] == revision(legacy)
        assert stored['graph'] == graph and stored['mappings'][0] == legacy['mappings'][0]
        assert len(stored['mappings']) == 6 and len({m['key'] for m in stored['mappings']}) == 6
        assert any(f['role'] == 'aspect_ratio' and f['default'] == '2:3 (Classic Portrait)'
                   for f in described['fields'])
        assert await service.describe(stored) == described
        hidden = service.presets.map(legacy['id'], legacy['mappings'])
        assert len((await service.describe(hidden))['fields']) == 1

    asyncio.run(scenario())
