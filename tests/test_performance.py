import pytest

from comfyui_control.performance import GenerationPerformance


def test_sampling_excludes_loading_segments_stages_and_uses_real_intervals():
    clock = [0.]
    stats = GenerationPerformance(lambda: clock[0])
    stats.event('execution_start', {'prompt_id':'one'}, 0)
    stats.event('executing', {'prompt_id':'one','node':'load-model'}, 10)
    assert stats.snapshot()['average'] is None
    stats.event('executing', {'prompt_id':'one','node':'sampler'}, 50)
    stats.event('progress', {'prompt_id':'one','value':0,'max':4}, 100)
    stats.event('progress', {'prompt_id':'one','value':1,'max':4}, 102)
    assert stats.snapshot()['current'] == 2
    assert stats.snapshot()['remaining'] is None
    stats.event('progress', {'prompt_id':'one','value':2,'max':4}, 106)
    assert stats.snapshot()['average'] == 3 and stats.snapshot()['remaining'] == 6
    # A second stage loads for 200 seconds; that time is never sampling time.
    stats.event('executing', {'prompt_id':'one','node':'second-sampler'}, 110)
    assert stats.snapshot()['current'] is None
    stats.event('progress', {'prompt_id':'one','value':0,'max':2}, 310)
    stats.event('progress', {'prompt_id':'one','value':1,'max':2}, 311)
    stats.event('progress', {'prompt_id':'one','value':2,'max':2}, 312)
    stats.event('execution_success', {'prompt_id':'one'}, 320)
    snapshot = stats.snapshot()
    assert snapshot['stage'] == 2 and snapshot['average'] == 2
    assert snapshot['elapsed'] == 320 and snapshot['last_average'] == 2
    assert snapshot['current'] is None and snapshot['remaining'] is None
    stats.event('execution_start', {'prompt_id':'two'}, 400)
    assert stats.snapshot()['average'] is None and stats.snapshot()['last_average'] == 2


def test_late_join_disconnect_cancellation_and_counter_resets():
    stats = GenerationPerformance(lambda: 100)
    stats.event('progress', {'prompt_id':'late','node':'a','value':4,'max':10}, 10)
    assert stats.snapshot()['elapsed'] is None and stats.snapshot()['current'] is None
    stats.event('progress', {'prompt_id':'late','node':'a','value':6,'max':10}, 14)
    assert stats.snapshot()['current'] == 2
    stats.disconnect()
    stats.event('progress', {'prompt_id':'late','node':'a','value':9,'max':10}, 40)
    assert stats.snapshot()['current'] is None  # The network gap isn't an iteration.
    stats.event('progress', {'prompt_id':'late','node':'a','value':0,'max':5}, 41)
    stats.event('progress', {'prompt_id':'late','node':'a','value':1,'max':5}, 42)
    assert stats.snapshot()['stage'] == 2
    stats.event('execution_interrupted', {'prompt_id':'late'}, 43)
    assert stats.snapshot()['status'] == 'cancelled'
    assert stats.snapshot()['last_average'] is None
    stats.event('execution_start', {'prompt_id':'error'}, 50)
    stats.event('execution_error', {'prompt_id':'error'}, 51)
    assert stats.snapshot()['elapsed'] == 1 and stats.snapshot()['current'] is None


def test_parallel_progress_does_not_invent_an_average():
    stats = GenerationPerformance()
    stats.event('execution_start', {'prompt_id':'parallel'}, 0)
    stats.event('progress_state', {'prompt_id':'parallel','nodes':{
        'a':{'state':'running','value':1,'max':4},'b':{'state':'running','value':2,'max':4}}}, 1)
    stats.event('execution_success', {'prompt_id':'parallel'}, 2)
    assert stats.snapshot()['average'] is None and stats.snapshot()['last_average'] is None


def test_owned_output_fallback_ignores_downloads_and_preserves_chunk_boundaries():
    clock = [0.]
    stats = GenerationPerformance(lambda: clock[0])
    stats.output('50%|xxx| 100/200 [00:10<00:10, 10MB/s]\n')
    assert stats.snapshot()['value'] is None
    stats.output('0%|xxx| 0/10 [00:00<?, ?it/s]\r')
    clock[0] = 2
    stats.output('10%|x| 1/')
    stats.output('10 [00:02<00:18, 2.00s/it]\r')
    assert stats.snapshot()['current'] == 2
    assert stats.snapshot()['elapsed'] is None
    stats.output('Prompt executed in 25.25 seconds\n')
    assert stats.snapshot()['elapsed'] == 25.25 and stats.snapshot()['last_average'] == 2


def test_batched_output_uses_latest_observed_count_not_first_line():
    clock=[0.]
    stats=GenerationPerformance(lambda:clock[0])
    stats.output('0%|x| 0/10 [00:00<?, ?it/s]\r')
    clock[0]=6
    stats.output('10%|x| 1/10 [00:02<00:18, 2s/it]\r20%|x| 2/10 [00:04<00:16, 2s/it]\r30%|x| 3/10 [00:06<00:14, 2s/it]\r')
    assert stats.snapshot()['current']==2 and stats.snapshot()['average']==2
