"""Regression coverage for the reported Bash script and real output routing."""
from dataclasses import replace
import asyncio
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from unittest.mock import patch

import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from comfyui_control.app import SettingsDialog
from comfyui_control.config import Config, OutputScriptError
from comfyui_control.controller import Controller
from comfyui_control.launch_script import prepare_script_update
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings
from comfyui_control.script_flags import inspect_script


def wait(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    base = tmp_path / 'Installation with spaces'
    comfy = base / 'ComfyUI'
    comfy.mkdir(parents=True)
    binary = base / 'comfy-env/bin'
    binary.mkdir(parents=True)
    (binary / 'python').symlink_to(sys.executable)
    (binary / 'activate').write_text(f'export VIRTUAL_ENV={shlex.quote(str(binary.parent))}\nexport PATH={shlex.quote(str(binary))}:"$PATH"\n')
    image = QImage(8, 12, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(base / 'template.png'))
    (comfy / 'main.py').write_text('''import argparse, json, os, pathlib, shutil
p=argparse.ArgumentParser()
p.add_argument('--output-directory', required=True)
p.add_argument('--use-pytorch-cross-attention', action='store_true')
p.add_argument('--reserve-vram', type=int)
p.add_argument('--listen', action='store_true')
p.add_argument('--enable-manager', action='store_true')
a=p.parse_args()
out=pathlib.Path(a.output_directory)
out.mkdir(parents=True, exist_ok=True)
shutil.copyfile(pathlib.Path(__file__).parent.parent/'template.png', out/'generated.png')
(out/'launch.json').write_text(json.dumps(dict(arguments=vars(a), venv=os.environ.get('VIRTUAL_ENV'), cwd=os.getcwd())))
''')
    script = base / 'start-comfy.sh'
    # Same command and flags as the user's script, with a disposable test path.
    script.write_text(f'''#!/usr/bin/env bash

cd {shlex.quote(str(base))}; or exit 1
source comfy-env/bin/activate; or exit 1
cd ComfyUI; or exit 1

python main.py \\
  --use-pytorch-cross-attention \\
  --reserve-vram 3 \\
  --listen \\
  --enable-manager
''')
    script.chmod(0o750)
    return base, comfy, script


@pytest.mark.parametrize('network', [False, True])
def test_reported_script_is_updated_and_actual_files_follow_folder_and_gallery(app, installation, network):
    base, comfy, script = installation
    original = script.read_bytes()
    selected = base / 'already mounted NAS folder with spaces'
    config = Config(comfy_dir=str(comfy), python=str(base / 'comfy-env/bin/python'), mode='script',
                    script=str(script), output_dir=str(selected), nfs_enabled=network,
                    nfs_server='192.0.2.10', nfs_export='/images', nfs_auto_connect=False,
                    monitoring_enabled=False)
    dialog = SettingsDialog(config)
    with patch.object(QMessageBox, 'warning') as warning:
        dialog._save()
        warning.assert_not_called()
    config = dialog.result_config
    assert config is not None
    assert dialog.script_backup.read_bytes() == original
    assert 'Bash error handling' in ' '.join(dialog.script_changes)
    assert script.stat().st_mode & 0o777 == 0o750
    assert ' || exit 1' in script.read_text() and '; or exit' not in script.read_text()
    assert inspect_script(script).arguments == ('--use-pytorch-cross-attention', '--reserve-vram', '3', '--listen', '--enable-manager')
    assert inspect_script(script).forwards_arguments
    config.validate()
    subprocess.run(['/bin/bash', '-n', str(script)], check=True)
    output = comfy / 'output' if network else selected
    controller = Controller(config)
    logs, problems = [], []
    controller.output.connect(logs.append)
    controller.problem.connect(problems.append)
    controller.start()
    wait(lambda: controller.process is None)
    assert not problems and 'command not found' not in ''.join(logs)
    assert (output / 'generated.png').is_file()
    launch = json.loads((output / 'launch.json').read_text())
    assert launch['venv'] == str(base / 'comfy-env')
    assert launch['arguments']['reserve_vram'] == 3
    assert launch['arguments']['listen'] and launch['arguments']['enable_manager']
    assert launch['cwd'] == str(comfy)

    async def gallery():
        service = MobileService(base / 'mobile-data', MobileSettings(), config.folder('output'))
        images = await service.gallery(force=True)
        assert [item['filename'] for item in images] == ['generated.png']
        assert service.local_image(images[0]) == output / 'generated.png'
    asyncio.run(gallery())
    # Choosing another existing local mount does not require another rewrite.
    next_config = replace(config, nfs_enabled=False, output_dir=str(base / 'another mount'))
    second = SettingsDialog(next_config)
    second._save()
    assert second.script_backup is None
    controller.set_config(second.result_config)
    controller.start()
    wait(lambda: controller.process is None)
    assert (base / 'another mount/generated.png').is_file()
    assert len(list(base.glob('start-comfy.sh.bak-*'))) == 1
    controller.shutdown()


@pytest.mark.parametrize('option', ['--output-directory "/old folder"', '--output-directory="/old folder"', '--output-directory "$OLD_OUTPUT"'])
def test_replaces_script_output_override_without_rewriting_other_shell_tokens(tmp_path, option):
    script = tmp_path / 'launch.sh'
    source = f'#!/bin/bash\n# preserve comment\nFLAG="keep me"\nexec env HIP_FLAG=1 "$SCRIPT_DIR/bin/python" main.py --reserve-vram 3 {option} --listen # keep inline comment\n'
    script.write_text(source)
    update = prepare_script_update(script)
    update.apply()
    after = script.read_text()
    assert '"$SCRIPT_DIR/bin/python"' in after and 'HIP_FLAG=1' in after
    assert '# preserve comment' in after and '# keep inline comment' in after
    assert '"$@" # keep inline comment' in after
    assert inspect_script(script).arguments == ('--reserve-vram', '3', '--listen')
    assert update.backup.read_text() == source
    assert prepare_script_update(script) is None


@pytest.mark.parametrize('source', [
    'start_comfy\n',
    'python main.py\npython main.py --cpu\n',
    'run() {\npython main.py\n}\nrun\n',
    'set -- --cpu\npython main.py\n',
    'shift\npython main.py\n',
    'for x in one; do\npython main.py\ndone\n',
    'python main.py >server.log\n',
    'cat <<EOF\npython main.py\nEOF\n',
])
def test_complex_scripts_are_not_guessed_or_partly_rewritten(tmp_path, source):
    script = tmp_path / 'complex.sh'
    script.write_text(source)
    with pytest.raises(ValueError):
        prepare_script_update(script)
    assert script.read_text() == source and not list(tmp_path.glob('*.bak-*'))


def test_script_inspection_never_executes_and_guard_like_quoted_text_is_preserved(tmp_path):
    script, marker = tmp_path / 'script.sh', tmp_path / 'not-executed'
    source = f'touch {shlex.quote(str(marker))}\ncd "/folder; or exit 1"\npython main.py --cpu\n'
    script.write_text(source)
    prepare_script_update(script).apply()
    assert not marker.exists()
    assert 'cd "/folder; or exit 1"' in script.read_text()


@pytest.mark.parametrize('forwarding', ['$@', "'$@'", '${@}'])
def test_bare_or_literal_forwarding_is_quoted_for_paths_with_spaces(tmp_path, forwarding):
    script = tmp_path / 'script.sh'
    script.write_text(f'python main.py {forwarding}\n')
    prepare_script_update(script).apply()
    assert script.read_text() == 'python main.py "$@"\n'


@pytest.mark.parametrize('failure', ['readonly', 'symlink', 'concurrent'])
def test_automatic_update_does_not_overwrite_unwritable_or_changed_scripts(tmp_path, failure):
    script = tmp_path / 'script.sh'
    script.write_text('python main.py\n')
    if failure == 'symlink':
        target = tmp_path / 'target.sh'
        script.rename(target)
        script.symlink_to(target)
        with pytest.raises(ValueError, match='symlink'):
            prepare_script_update(script)
        assert target.read_text() == 'python main.py\n'
    else:
        if failure == 'readonly':
            script.chmod(0o444)
        plan = prepare_script_update(script)
        if failure == 'concurrent':
            script.write_text('python main.py --new-edit\n')
        current = script.read_bytes()
        with pytest.raises(ValueError, match='writable|changed'):
            plan.apply()
        assert script.read_bytes() == current
    assert not list(tmp_path.glob('*.bak-*'))


def test_settings_save_failure_rolls_back_script_and_keeps_exact_backup(app, installation):
    base, comfy, script = installation
    original = script.read_bytes()
    old = Config(comfy_dir=str(comfy), mode='script', script=str(script))
    old.save()
    dialog = SettingsDialog(replace(old, output_dir=str(base / 'output')))
    with patch.object(Config, 'save', side_effect=OSError('Settings disk full')), patch.object(QMessageBox, 'warning') as warning:
        dialog._save()
    assert dialog.result_config is None and script.read_bytes() == original
    assert 'rolled back' in warning.call_args.args[-1]
    assert Config.load().output_dir == ''
    backups = list(base.glob('start-comfy.sh.bak-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == original


def test_failed_backup_is_not_left_as_a_misleading_partial_original(tmp_path):
    script = tmp_path / 'script.sh'
    script.write_text('python main.py\n')
    plan = prepare_script_update(script)
    with patch('comfyui_control.launch_script.os.fsync', side_effect=[None, OSError('Backup disk full')]):
        with pytest.raises(OSError, match='Backup disk full'):
            plan.apply()
    assert script.read_text() == 'python main.py\n'
    assert not list(tmp_path.glob('*.bak-*'))
    assert list(tmp_path.iterdir()) == [script]


@pytest.mark.parametrize('choice', ['save', 'cancel'])
def test_complex_script_can_save_mount_settings_without_starting_wrong_output(app, installation, choice):
    base, comfy, script = installation
    script.write_text('custom_launcher --my-setup\n')
    config = Config(comfy_dir=str(comfy), mode='script', script=str(script), nfs_enabled=True,
                    nfs_server='nas', nfs_export='/images', nfs_auto_connect=False)
    dialog = SettingsDialog(config)
    def choose(box):
        assert 'identify' in box.text()
        assert 'before any NAS connection' in box.informativeText()
        assert 'single Python main.py' in box.informativeText()
        assert str(script) in box.detailedText()
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        button = next(button for button in box.buttons() if button.text() == 'Save settings for mount setup') if choice == 'save' else box.button(QMessageBox.StandardButton.Cancel)
        button.click()
        return 0
    with patch.object(QMessageBox, 'exec', choose):
        dialog._save()
    assert script.read_text() == 'custom_launcher --my-setup\n'
    assert not list(base.glob('*.bak-*'))
    if choice == 'save':
        assert Config.load().nfs_enabled and dialog.result_config
        with pytest.raises(OutputScriptError, match='cannot identify'):
            dialog.result_config.validate()
        controller = Controller(dialog.result_config)
        problems = []
        controller.problem.connect(problems.append)
        controller.start()
        assert controller.process is None and problems
    else:
        assert dialog.result_config is None
