"""Real serialized workflow regressions, with prompts/model/output names redacted.

Schemas reflect the inspected ComfyUI native definitions. Protocol fixtures do
not exercise inference or install model weights; user graphs are not bundled.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import uuid

from aiohttp.test_utils import TestServer
import pytest

from comfyui_control.mobile.workflow_sources import editor_to_api
from comfyui_control.mobile.workflows import input_schema, fields_for, render
from comfyui_control.mobile.image_actions import IMAGE_WORKFLOWS, upscale_multiplier_binding
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from test_image_workflows import ImageWorkflowStub, picture, ALICE
from test_mobile_integration import until

FIXTURES = Path(__file__).parent / 'fixtures/workflow_conversion'


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def metadata():
    combo = lambda *values: [list(values)]
    seed = ['INT', {'control_after_generate': True, 'min': 0, 'max': 2**64-1}]
    tile = dict(tile_size=['INT'], overlap=['INT'], temporal_size=['INT'], temporal_overlap=['INT'])
    definitions = {
        'LoadImage': dict(image=[['editor-edit-source.png', 'editor-upscale-source.png'], {'image_upload': True}]),
        'SaveImage': dict(images=['IMAGE'], filename_prefix=['STRING']),
        'CLIPLoader': dict(clip_name=combo('fixture-encoder.safetensors'), type=combo('qwen_image'), device=combo('default', 'cpu')),
        'VAELoader': dict(vae_name=combo('fixture-qwen-vae.safetensors', 'fixture-upscale-vae.safetensors')),
        'LoaderGGUF': dict(gguf_name=combo('fixture-qwen.gguf')),
        'QwenImage21Cache': dict(model=['MODEL'], device=combo('auto', 'gpu', 'cpu', 'off'), dtype=combo('default')),
        'RandomNoise': dict(noise_seed=seed),
        'CFGGuider': dict(model=['MODEL'], positive=['CONDITIONING'], negative=['CONDITIONING'], cfg=['FLOAT']),
        'KSamplerSelect': dict(sampler_name=combo('euler')),
        'ManualSigmas': dict(sigmas=['STRING']),
        'SamplerCustomAdvanced': dict(noise=['NOISE'], guider=['GUIDER'], sampler=['SAMPLER'], sigmas=['SIGMAS'], latent_image=['LATENT']),
        'VAEDecode': dict(samples=['LATENT'], vae=['VAE']),
        'VAEEncodeTiled': dict(pixels=['IMAGE'], vae=['VAE'], **tile),
        'VAEDecodeTiled': dict(samples=['LATENT'], vae=['VAE'], **tile),
        'JoinImageWithAlpha': dict(image=['IMAGE'], alpha=['MASK']),
        'UNETLoader': dict(unet_name=combo('fixture-upscale.safetensors'), weight_dtype=combo('default')),
        'KSampler': dict(model=['MODEL'], positive=['CONDITIONING'], negative=['CONDITIONING'], latent_image=['LATENT'],
                         seed=seed, steps=['INT'], cfg=['FLOAT'], sampler_name=combo('euler'), scheduler=combo('simple'), denoise=['FLOAT']),
        'ResizeImageMaskNode': dict(input=['IMAGE,MASK'], resize_type=['COMFY_DYNAMICCOMBO_V3', {'options': [
            {'key':'scale by multiplier', 'inputs': {'required': {'multiplier': ['FLOAT', {'min':.01,'max':8.,'step':.01}]}}},
            {'key':'scale dimensions', 'inputs': {'required': {'width':['INT'], 'height':['INT']}}},
        ]}], scale_method=combo('lanczos')),
        'SeedVR2Preprocess': dict(resized_images=['IMAGE']),
        'SeedVR2PostProcessing': dict(images=['IMAGE'], original_resized_images=['IMAGE'], color_correction_method=combo('none')),
        'SeedVR2Conditioning': dict(model=['MODEL'], vae_conditioning=['LATENT']),
        'ImageCompare': dict(compare_view=['IMAGECOMPARE', {'socketless': True}]),
        'TextEncodeQwenImage21': dict(clip=['CLIP'], prompt=['STRING'], negative_prompt=['STRING'], resolution=['INT']),
    }
    info = {name: {'input': {'required': inputs}, 'output_node': name in {'SaveImage','ImageCompare'}} for name, inputs in definitions.items()}
    info['TextEncodeQwenImage21']['input']['optional'] = {
        'vae': ['VAE'], 'images': ['COMFY_AUTOGROW_V3', {'template': {
            'input': {'required': {'image': ['IMAGE', {'forceInput': True}]}},
            'names': [f'image_{i}' for i in range(1,17)], 'min': 0}}]}
    info['ImageCompare']['input']['optional'] = dict(image_a=['IMAGE'], image_b=['IMAGE'])
    info['LoaderGGUF']['output'] = ['MODEL']
    return info


def executable(graph):
    return {key: {k: v for k, v in node.items() if k != '_meta'} for key, node in graph.items()}


def test_qwen_editor_preserves_current_widgets_and_complete_reference_and_model_connections():
    editor, api = fixture('qwen-editor'), fixture('qwen-api')
    original = deepcopy(editor)
    graph = editor_to_api(editor, metadata())
    expected = deepcopy(api)
    expected['86']['inputs']['device'] = 'default'
    expected['88']['inputs']['image'] = 'editor-edit-source.png'
    expected['89']['inputs']['prompt'] = 'Current edit instruction'
    expected['90']['inputs']['model'] = ['99', 0]  # Present in editor; absent from supplied API export.
    expected['91']['inputs']['noise_seed'] = 740861902239610
    expected['97']['inputs']['filename_prefix'] = 'fixture/edited'
    assert executable(graph) == executable(expected)
    assert graph['89']['inputs']['images.image_1'] == ['88',0]
    assert 'upload' not in graph['88']['inputs'] and '98' not in graph
    assert editor == original


def test_seedvr_editor_matches_api_topology_and_uses_exposed_widget_values():
    editor, api = fixture('seedvr-editor'), fixture('seedvr-api')
    original = deepcopy(editor)
    graph = editor_to_api(editor, metadata())
    expected = deepcopy(api)
    expected['1']['inputs']['image'] = 'editor-upscale-source.png'
    expected['9']['inputs']['filename_prefix'] = 'fixture/upscaled'
    expected['66:57']['inputs']['resize_type.multiplier'] = 3  # Parent instance overrides definition's 4.
    assert executable(graph) == executable(expected)
    binding = upscale_multiplier_binding(graph)
    assert binding['node'] == '66:57' and binding['input'] == 'resize_type.multiplier'
    schema = input_schema(graph, '66:57', binding['input'], metadata())
    assert schema[0] == 'FLOAT' and schema[1]['max'] == 8
    preset = {'graph': graph, 'mappings': [binding]}
    assert fields_for(preset, metadata())[0]['kind'] == 'float'
    changed, values = render(preset, {'action-scale':1.5}, info=metadata())
    assert changed['66:57']['inputs']['resize_type.multiplier'] == 1.5
    assert values['action-scale'] == 1.5 and editor == original
    with pytest.raises(ValueError, match='allowed range'):
        render(preset, {'action-scale':9}, info=metadata())


@pytest.mark.parametrize('action, source', [('edit','qwen-editor'), ('upscale','seedvr-editor')])
def test_real_saved_editors_execute_through_existing_action_queue_and_ignore_stale_companions(tmp_path, action, source):
    async def scenario():
        stub = ImageWorkflowStub()
        name = IMAGE_WORKFLOWS[action]['name'] + '.json'
        stub.saved = {name: fixture(source)}
        # A stale/incomplete export must not override the current saved editor.
        stub.saved[name.removesuffix('.json') + '.api.json'] = {'invalid': 'old export'}
        stub.object_info = metadata()
        stub.image_names = stub.object_info['LoadImage']['input']['required']['image'][0]
        before = deepcopy(stub.saved[name])
        upstream = TestServer(stub.app())
        await upstream.start_server()
        picture(tmp_path / 'out/one.png')
        service = MobileService(tmp_path / 'data', MobileSettings(comfy_url=str(upstream.make_url('/'))), tmp_path / 'out')
        try:
            await service.start()
            await until(lambda: service.online)
            item = (await service.gallery(ALICE))[0]
            body = dict(action=action, request_id=str(uuid.uuid4()), modified=item['modified'])
            if action == 'edit': body['prompt'] = 'Apply this instruction'
            else: body['multiplier'] = 1.5
            result = await service.image_action(item['id'], ALICE, body)
            expected = editor_to_api(before, stub.object_info)
            image_node = '88' if action == 'edit' else '1'
            expected[image_node]['inputs']['image'] = stub.uploads[0]['name']
            if action == 'edit': expected['89']['inputs']['prompt'] = body['prompt']
            else: expected['66:57']['inputs']['resize_type.multiplier'] = 1.5
            assert stub.submissions[0]['prompt'] == expected
            assert result['job']['prompt_id']
            await until(lambda: service.jobs[result['job']['id']]['status'] == 'queued')
            assert stub.saved[name] == before
            await service.image_action(item['id'], ALICE, body)
            assert len(stub.submissions) == len(stub.uploads) == 1
        finally:
            await service.stop()
            await upstream.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('problem', ['unknown-upload-value', 'missing-upload-declaration', 'unknown-upload-tail', 'unknown-dynamic-image'])
def test_unknown_frontend_serialization_is_not_silently_discarded(problem):
    editor = fixture('qwen-editor')
    load = next(n for n in editor['nodes'] if n['id'] == 88)
    if problem == 'unknown-upload-value': load['widgets_values'][-1] = 'unknown'
    elif problem == 'missing-upload-declaration': load['inputs'] = load['inputs'][:1]
    elif problem == 'unknown-upload-tail': load['widgets_values'].append('unknown')
    else:
        text = next(n for n in editor['nodes'] if n['id'] == 89)
        next(entry for entry in text['inputs'] if entry['name'] == 'images.image_1')['name'] = 'images.image_99'
    with pytest.raises(ValueError, match='custom widgets'):
        editor_to_api(editor, metadata())


@pytest.mark.parametrize('problem', ['bad-input-port', 'bad-output-port', 'bad-boundary-link', 'conflicting-widgets', 'unknown-widget-value', 'recursive', 'muted'])
def test_ambiguous_or_invalid_subgraph_data_fails_closed(problem):
    editor = fixture('seedvr-editor')
    definition = editor['definitions']['subgraphs'][0]
    instance = next(n for n in editor['nodes'] if n['id'] == 66)
    if problem == 'bad-input-port': instance['inputs'][0]['name'] = 'wrong-port'
    elif problem == 'bad-output-port': definition['outputs'][0]['linkIds'].append(999)
    elif problem == 'bad-boundary-link': definition['inputs'][0]['linkIds'] = []
    elif problem == 'conflicting-widgets': instance['widgets_values_named']['resize_type.multiplier'] = 7
    elif problem == 'unknown-widget-value': instance['widgets_values'].append('unrecognized')
    elif problem == 'recursive':
        definition['nodes'].append(dict(id=123, type=definition['id'], inputs=[], outputs=[], widgets_values=[]))
    else: instance['mode'] = 2
    with pytest.raises(ValueError):
        editor_to_api(editor, metadata())


def test_reused_and_nested_subgraphs_get_distinct_namespaced_ids():
    editor = fixture('seedvr-editor')
    original = next(n for n in editor['nodes'] if n['id'] == 66)
    duplicate = deepcopy(original)
    duplicate['id'] = 67
    duplicate['widgets_values'][0] = 2
    duplicate['widgets_values_named']['resize_type.multiplier'] = 2
    for slot, entry in enumerate(duplicate['inputs']):
        if entry.get('link') is not None:
            link = next(link for link in editor['links'] if link[0] == entry['link'])
            copied = [100 + slot, link[1], link[2], 67, slot, link[5]]
            editor['links'].append(copied)
            entry['link'] = copied[0]
    editor['nodes'].append(duplicate)
    graph = editor_to_api(editor, metadata())
    assert graph['66:57']['inputs']['resize_type.multiplier'] == 3
    assert graph['67:57']['inputs']['resize_type.multiplier'] == 2
    assert graph['66:48']['inputs']['pixels'] == ['66:58',0]
    assert graph['67:48']['inputs']['pixels'] == ['67:58',0]
    assert graph['67:50']['inputs']['image'] == ['1',0]
    # Wrap the entire outer graph in another saved subgraph definition. Its
    # output exposes the saved comparison's input, and all original links remain.
    inner_id = 'nested-fixture'
    inner = {**editor, 'id': inner_id, 'inputs': [], 'inputNode': {'id': -10},
             'outputNode': {'id': -20}, 'outputs':[{'name':'image','type':'IMAGE','linkIds':[999]}]}
    inner['links'] = [*editor['links'], [999,9,0,-20,0,'IMAGE']]
    nested = {'nodes':[dict(id='outer', type=inner_id, inputs=[], outputs=[{'type':'IMAGE'}], widgets_values=[])],
              'links':[], 'definitions': {'subgraphs': [*editor['definitions']['subgraphs'], inner]}}
    graph = editor_to_api(nested, metadata())
    assert graph['outer:66:57']['inputs']['resize_type.multiplier'] == 3
    assert graph['outer:67:57']['inputs']['resize_type.multiplier'] == 2
    assert graph['outer:9']['inputs']['images'] == ['outer:66:59',0]


def test_dynamic_metadata_preserves_selected_branch_limits_and_declared_slot_names():
    from comfyui_control.mobile.input_metadata import expanded_inputs
    info = metadata()
    schema = info['ResizeImageMaskNode']['input']
    before = deepcopy(schema)
    scaling = expanded_inputs(schema, {'resize_type':'scale by multiplier'})
    dimensions = expanded_inputs(schema, {'resize_type':'scale dimensions'})
    assert scaling['required']['resize_type.multiplier'][1]['max'] == 8
    assert 'resize_type.width' not in scaling['required']
    assert dimensions['required']['resize_type.width'][0] == 'INT'
    assert 'resize_type.multiplier' not in dimensions['required'] and schema == before
    template = {'input': {'required': {'image':['IMAGE']}}, 'prefix':'slot_', 'max':3, 'min':1}
    slots = expanded_inputs({'required': {'images':['COMFY_AUTOGROW_V3', {'template':template}]}}, {})
    assert set(slots['required']) == {'images.slot_0'}
    assert set(slots['optional']) == {'images.slot_1','images.slot_2'}
    template['max'] = 101
    with pytest.raises(ValueError, match='slot limit'):
        expanded_inputs({'required': {'images':['COMFY_AUTOGROW_V3', {'template':template}]}}, {})
