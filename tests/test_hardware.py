import subprocess
from types import SimpleNamespace

import pytest

from comfyui_control.hardware import HardwareReader, number


def test_cpu_deltas_ram_and_unavailable_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda _: None)
    reader = HardwareReader(tmp_path, tmp_path/'drm')
    assert reader.sample()['cpu'] is None
    assert reader.sample()['ram_total'] is None
    assert reader.sample()['gpus'] == []
    (tmp_path/'stat').write_text('cpu 10 0 20 70 0 0 0 0 5 0\n')
    (tmp_path/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 400 kB\n')
    assert reader.sample()['cpu'] is None
    (tmp_path/'stat').write_text('cpu 20 0 30 100 0 0 0 0 7 0\n')
    result = reader.sample()
    assert result['cpu'] == pytest.approx(40)
    assert (result['ram_used'], result['ram_total']) == (600*1024, 1000*1024)
    reader.reset()
    assert reader.sample()['cpu'] is None
    assert number('N/A') is None and number('nan') is None and number('-1') is None
    assert number('0 W') == 0


def test_amd_sysfs_units_and_missing_sensors(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda _: None)
    device = tmp_path/'card0/device'
    sensor = device/'hwmon/hwmon0'
    sensor.mkdir(parents=True)
    for name, value in {'vendor':'0x1002','gpu_busy_percent':'65','mem_info_vram_used':str(2**30), 'mem_info_vram_total':str(8*2**30)}.items():
        (device/name).write_text(value)
    (sensor/'temp1_input').write_text('63000')
    (sensor/'power1_average').write_text('140500000')
    reader = HardwareReader(tmp_path/'proc', tmp_path)
    gpu = reader.sample()['gpus'][0]
    assert gpu['utilization'] == 65 and gpu['temperature'] == 63
    assert gpu['power'] == 140.5 and gpu['vram_total'] == 8*2**30
    (sensor/'temp1_input').unlink()
    assert reader.sample()['gpus'][0]['temperature'] is None


def test_nvidia_and_rocm_capability_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/'+name)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0].endswith('nvidia-smi'):
            return SimpleNamespace(stdout='0, NVIDIA Test, 70, 1024, 8192, N/A, [Not Supported]\n')
        return SimpleNamespace(stdout='{"card0":{"GPU use (%)":"42","VRAM Total Memory (B)":"8192","VRAM Total Used Memory (B)":"1024","Temperature (Sensor edge) (C)":"55","Average Graphics Package Power (W)":"120"}}')
    reader = HardwareReader(tmp_path, tmp_path, run)
    gpus = reader.sample()['gpus']
    assert len(gpus) == 2
    assert gpus[0]['temperature'] is None and gpus[0]['power'] is None
    assert gpus[0]['vram_used'] == 1024**3
    assert gpus[1]['utilization'] == 42 and gpus[1]['power'] == 120
    assert all(call[1]['timeout'] < 1 for call in calls)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], .8)
    assert HardwareReader(tmp_path, tmp_path, timeout).sample()['gpus'] == []


def test_process_group_rss_excludes_unowned_processes(tmp_path):
    def process(pid, group, pages):
        folder = tmp_path/str(pid)
        folder.mkdir()
        fields = ['S','1',str(group)] + ['0']*18 + [str(pages)]
        (folder/'stat').write_text(f'{pid} (a process with spaces) '+' '.join(fields))
    process(100, 100, 10)
    process(101, 100, 20)
    process(102, 102, 999)
    reader = HardwareReader(tmp_path, tmp_path)
    import os
    assert reader.process_memory(100) == 30 * os.sysconf('SC_PAGE_SIZE')
    assert reader.process_memory(101) is None
    assert reader.process_memory(0) is None
