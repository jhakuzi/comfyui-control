"""Read-only Linux metrics. All command/file work is run outside the Qt thread."""
import csv
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess


def number(value, scale=1):
    try:
        result = float(str(value).strip().split()[0]) * scale
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, IndexError):
        return None


def read_number(path, scale=1):
    try:
        return number(Path(path).read_text(), scale)
    except OSError:
        return None


class HardwareReader:
    def __init__(self, proc=Path('/proc'), drm=Path('/sys/class/drm'), run=subprocess.run):
        self.proc, self.drm, self.run = Path(proc), Path(drm), run
        self.previous_cpu = None

    def reset(self):
        self.previous_cpu = None

    def cpu(self):
        try:
            values = [int(v) for v in (self.proc/'stat').read_text().splitlines()[0].split()[1:9]]
            if len(values) < 5:
                return None
            total, idle = sum(values), values[3] + values[4]
            previous, self.previous_cpu = self.previous_cpu, (total, idle)
            if previous and total > previous[0] and idle >= previous[1]:
                return max(0, min(100, 100 * (1 - (idle - previous[1]) / (total - previous[0]))))
        except (OSError, ValueError, IndexError):
            self.previous_cpu = None
        return None

    def ram(self):
        try:
            values = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in (self.proc/'meminfo').read_text().splitlines()}
            total, available = values['MemTotal'], values['MemAvailable']
            return (total - available, total) if 0 <= available <= total else (None, None)
        except (OSError, ValueError, KeyError, IndexError):
            return None, None

    def process_memory(self, pid):
        if not pid:
            return None
        # Include only the app-owned process group. RSS can count shared pages
        # more than once; the UI labels it accordingly rather than claiming PSS.
        try:
            root = (self.proc/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()
            group = int(root[2])
            if group != pid:
                return None
        except (OSError, ValueError, IndexError):
            return None
        total, found = 0, False
        try:
            entries = self.proc.iterdir()
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                try:
                    fields = (entry/'stat').read_text().rsplit(')', 1)[1].split()
                    if int(fields[2]) == group:
                        total += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
                        found = True
                except (OSError, ValueError, IndexError):
                    continue
        except OSError:
            return None
        return total if found else None

    def command(self, args):
        try:
            return self.run(args, capture_output=True, text=True, timeout=.8, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return ''

    def nvidia(self):
        executable = shutil.which('nvidia-smi')
        if not executable:
            return []
        query = 'index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw'
        output = self.command([executable, '--query-gpu='+query, '--format=csv,noheader,nounits'])
        result = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) != 7:
                continue
            index, name, use, used, total, temp, power = (v.strip() for v in row)
            result.append(dict(id='nvidia-'+index, name=name, utilization=number(use),
                vram_used=number(used, 1024**2), vram_total=number(total, 1024**2),
                temperature=number(temp), power=number(power)))
        return result

    def amd(self):
        result = []
        for card in sorted(self.drm.glob('card[0-9]*')):
            if not card.name[4:].isdecimal():
                continue
            device = card/'device'
            try:
                if (device/'vendor').read_text().strip().lower() != '0x1002':
                    continue
            except OSError:
                continue
            gpu = dict(id=card.name, name='AMD GPU · '+card.name,
                utilization=read_number(device/'gpu_busy_percent'),
                vram_used=read_number(device/'mem_info_vram_used'),
                vram_total=read_number(device/'mem_info_vram_total'), temperature=None, power=None)
            for hwmon in sorted((device/'hwmon').glob('hwmon*')):
                if gpu['temperature'] is None:
                    gpu['temperature'] = read_number(hwmon/'temp1_input', .001)
                if gpu['power'] is None:
                    for name in ('power1_average', 'power1_input'):
                        gpu['power'] = read_number(hwmon/name, .000001)
                        if gpu['power'] is not None:
                            break
            result.append(gpu)
        return result

    def rocm(self):
        executable = shutil.which('rocm-smi')
        if not executable:
            return []
        output = self.command([executable, '--showuse', '--showmeminfo', 'vram', '--showtemp', '--showpower', '--json'])
        try:
            data = json.loads(output)
        except (ValueError, TypeError):
            return []
        result = []
        for key, fields in data.items() if isinstance(data, dict) else []:
            if not isinstance(fields, dict) or not key.startswith('card'):
                continue
            def metric(*names):
                return next((number(fields[n]) for n in names if n in fields), None)
            result.append(dict(id=key, name='AMD GPU · '+key,
                utilization=metric('GPU use (%)'), vram_used=metric('VRAM Total Used Memory (B)'),
                vram_total=metric('VRAM Total Memory (B)'),
                temperature=metric('Temperature (Sensor edge) (C)', 'Temperature (Sensor junction) (C)'),
                power=metric('Average Graphics Package Power (W)', 'Current Socket Graphics Package Power (W)')))
        return result

    def sample(self, pid=0):
        used, total = self.ram()
        amd = self.amd()
        if not amd or all(all(gpu[k] is None for k in ('utilization', 'vram_used', 'temperature', 'power')) for gpu in amd):
            amd = self.rocm() or amd
        return dict(cpu=self.cpu(), ram_used=used, ram_total=total,
                    process_memory=self.process_memory(pid), gpus=self.nvidia()+amd)
