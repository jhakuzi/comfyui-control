from copy import deepcopy

import pytest

from comfyui_control.mobile.workflows import fields_for, render, suggested_mappings, validate_mappings


def workflow():
    return {
        'prompt': {'class_type': 'PrimitiveStringMultiline', 'inputs': {'value': 'A scene'}},
        'encode': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ['prompt', 0]}},
        'zero': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['encode', 0]}},
        'guider': {'class_type': 'CFGGuider', 'inputs': {'positive': ['encode', 0], 'negative': ['zero', 0]}},
        'stack': {'class_type': 'Stack', 'inputs': {'lora_01': 'one.safetensors', 'strength_01': 0.8,
                                                     'lora_02': 'None', 'strength_02': 1.0,
                                                     'strength_03': 2.0}},
        'latent': {'class_type': 'Latent', 'inputs': {'dimensions': ' 832 x 1216  (portrait)', 'batch_size': 1}},
    }


def test_connected_prompt_numbered_loras_and_dimensions_render_safely():
    graph = workflow()
    original = deepcopy(graph)
    preset = {'graph': graph, 'mappings': validate_mappings(graph, suggested_mappings(graph))}
    fields = {(x['node'], x['input']): x for x in preset['mappings']}
    assert fields['prompt', 'value']['role'] == 'positive'
    assert ('stack', 'strength_03') not in fields
    assert fields['stack', 'lora_01']['group'] == fields['stack', 'strength_01']['group']
    assert fields['stack', 'lora_01']['group'] != fields['stack', 'lora_02']['group']
    assert fields['latent', 'dimensions']['role'] == 'aspect_ratio'
    choice = ' 832 x 1216 (portrait)'
    info = {'Latent': {'input': {'required': {'dimensions': [[choice, '1024 x 1024 (square)']]}}}}
    shown = {(x['node'], x['input']): x for x in fields_for(preset, info)}
    assert shown['latent', 'dimensions']['default'] == choice
    result, _ = render(preset, {fields['prompt', 'value']['key']: 'Changed'},
                       disabled_loras=[fields['stack', 'lora_01']['group']], info=info)
    assert result['prompt']['inputs']['value'] == 'Changed'
    assert result['stack']['inputs']['strength_01'] == 0
    assert result['stack']['inputs']['strength_02'] == 1.0
    assert result['latent']['inputs']['dimensions'] == choice
    assert result['encode']['inputs']['text'] == ['prompt', 0]
    assert graph == original


def test_ambiguous_prompt_and_dimension_choices_are_not_guessed():
    graph = workflow()
    graph['guider']['inputs']['negative'] = ['encode', 0]
    mappings = validate_mappings(graph, suggested_mappings(graph))
    assert not any(m['node'] == 'prompt' for m in mappings)
    preset = {'graph': graph, 'mappings': mappings}
    options = ['832 x 1216 (portrait)', ' 832 x 1216 (portrait)']
    info = {'Latent': {'input': {'required': {'dimensions': [options]}}}}
    with pytest.raises(ValueError, match='not available'):
        render(preset, {}, info=info)


def test_sampling_stages_follow_graph_connections_and_exclude_shared_controls():
    graph = {
        'n2': {'class_type': 'Noise', 'inputs': {'noise_seed': 2}},
        's2': {'class_type': 'Select', 'inputs': {'sampler_name': 'b'}},
        'g2': {'class_type': 'Guider', 'inputs': {'cfg': 2}},
        'd2': {'class_type': 'Scheduler', 'inputs': {'scheduler': 'b', 'steps': 2}},
        'second': {'class_type': 'Sampler', 'inputs': {'noise': ['n2', 0], 'sampler': ['s2', 0], 'guider': ['g2', 0], 'sigmas': ['d2', 0], 'latent_image': ['first', 0]}},
        'n1': {'class_type': 'Noise', 'inputs': {'noise_seed': 1}},
        's1': {'class_type': 'Select', 'inputs': {'sampler_name': 'a'}},
        'g1': {'class_type': 'Guider', 'inputs': {'cfg': 1}},
        'd1': {'class_type': 'Scheduler', 'inputs': {'scheduler': 'a', 'steps': 1}},
        'first': {'class_type': 'Sampler', 'inputs': {'noise': ['n1', 0], 'sampler': ['s1', 0], 'guider': ['g1', 0], 'sigmas': ['d1', 0]}},
    }
    preset = {'graph': graph, 'mappings': validate_mappings(graph, suggested_mappings(graph))}
    fields = fields_for(preset, {})
    assert {f['sampling_stage'] for f in fields if f['node'] in {'n1','s1','g1','d1'}} == {1}
    assert {f['sampling_stage'] for f in fields if f['node'] in {'n2','s2','g2','d2'}} == {2}
    graph['second']['inputs']['noise'] = ['n1', 0]
    fields = fields_for(preset, {})
    assert 'sampling_stage' not in next(f for f in fields if f['node'] == 'n1')
