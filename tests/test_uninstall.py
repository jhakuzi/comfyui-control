"""Deletion tests use disposable user homes, app environments and ComfyUI trees."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

from comfyui_control import uninstall as un


@pytest.fixture
def user_install(tmp_path, monkeypatch):
    home = tmp_path / 'a home with spaces'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(home/'data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home/'config'))
    # Unit tests remain isolated when RPM's test runner is root. Subprocess
    # integration tests separately verify the real no-sudo check.
    monkeypatch.setattr(un.os, 'geteuid', lambda: 1000)
    root, wrapper, desktop, settings = un.user_paths()
    (root/'venv/lib/python3.12/site-packages/comfyui_control').mkdir(parents=True)
    (root/'venv/lib/python3.12/site-packages/comfyui_control/__init__.py').touch()
    (root/'venv/pyvenv.cfg').write_text('home = /usr/bin\n')
    executable = root/'venv/bin/comfyui-control'
    executable.parent.mkdir()
    executable.write_text('#!/bin/sh\n')
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(executable)) + ' "$@"\n')
    desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nExec="' + str(executable) + '"\n')
    settings.mkdir(parents=True)
    comfy = home/'ComfyUI'
    (comfy/'comfy').mkdir(parents=True)
    (comfy/'main.py').write_text('import time\ntime.sleep(120)\n')
    (comfy/'folder_paths.py').touch()
    (comfy/'models').mkdir()
    (comfy/'models/large-model').write_bytes(b'model fixture')
    (comfy/'output').mkdir()
    (comfy/'output/local.png').write_bytes(b'image fixture')
    (settings/'config.json').write_text(__import__('json').dumps({'comfy_dir': str(comfy)}))
    (settings/'mobile').mkdir()
    (settings/'mobile/jobs.json').write_text('{"private":"keep"}')
    return root, comfy, settings


def test_app_only_keeps_comfy_and_settings_and_removes_owned_launchers(user_install):
    root, comfy, settings = user_install
    installation = un.discover_installation()
    assert installation.kind == 'zip'
    before = (settings/'config.json').read_bytes()
    plan = un.prepare_plan(installation)
    assert root.exists() and comfy.exists()  # planning does not delete anything
    message = un.execute_plan(plan)
    assert not root.exists()
    assert not un.user_paths()[1].exists() and not un.user_paths()[2].exists()
    assert (comfy/'models/large-model').exists() and (comfy/'output/local.png').exists()
    assert (settings/'config.json').read_bytes() == before
    assert (settings/'mobile/jobs.json').exists()
    assert 'ComfyUI was kept' in message


def test_confirmed_comfy_removal_keeps_external_symlink_targets_and_environment(user_install):
    root, comfy, settings = user_install
    external = comfy.parent/'NAS data'
    external.mkdir()
    (external/'image.png').write_bytes(b'keep NAS fixture')
    (comfy/'network-output').symlink_to(external, target_is_directory=True)
    environment = comfy.parent/'comfy-env'
    environment.mkdir()
    (environment/'keep').touch()
    plan = un.prepare_plan(un.discover_installation(), comfy)
    un.execute_plan(plan)
    assert not root.exists() and not comfy.exists()
    assert (external/'image.png').read_bytes() == b'keep NAS fixture'
    assert (environment/'keep').exists() and settings.exists()


def test_replaced_shortcuts_are_not_unlinked(user_install):
    root, _, _ = user_install
    _, wrapper, desktop, _ = un.user_paths()
    wrapper.write_text('#!/bin/sh\necho another application\n')
    desktop.write_text('[Desktop Entry]\nExec=another-application\n')
    un.execute_plan(un.prepare_plan(un.discover_installation()))
    assert not root.exists()
    assert wrapper.exists() and desktop.exists()


@pytest.mark.parametrize('which', ['app', 'comfy', 'environment'])
def test_changed_folder_identity_aborts_before_any_deletion(user_install, which):
    root, comfy, _ = user_install
    plan = un.prepare_plan(un.discover_installation(), comfy)
    target = root if which == 'app' else root/'venv' if which == 'environment' else comfy
    target.rename(target.with_name(target.name+'-original'))
    target.mkdir()
    if which == 'comfy':
        (target/'main.py').touch()
        (target/'folder_paths.py').touch()
        (target/'comfy').mkdir()
    with pytest.raises(un.UninstallError, match='changed'):
        un.execute_plan(plan)
    assert root.exists() and comfy.exists()


def test_app_only_keeps_additional_user_data_in_app_folder(user_install):
    root, comfy, settings = user_install
    nested = root/'personal ComfyUI'
    comfy.rename(nested)
    (settings/'config.json').write_text(__import__('json').dumps({'comfy_dir': str(nested)}))
    (root/'notes.txt').write_text('keep my notes')
    un.execute_plan(un.prepare_plan(un.discover_installation()))
    assert not (root/'venv').exists()
    assert (nested/'models/large-model').exists()
    assert (root/'notes.txt').read_text() == 'keep my notes'


@pytest.mark.parametrize('alias', [False, True])
def test_configured_data_inside_app_environment_must_be_moved_first(user_install, alias):
    root, comfy, settings = user_install
    nested = root/'venv/ComfyUI'
    comfy.rename(nested)
    location = nested
    if alias:
        comfy.symlink_to(nested, target_is_directory=True)
        location = comfy
    (settings/'config.json').write_text(__import__('json').dumps({'comfy_dir': str(location)}))
    with pytest.raises(un.UninstallError, match='inside the app environment'):
        un.prepare_plan(un.discover_installation())
    assert (nested/'models/large-model').exists()


@pytest.mark.parametrize('kind,relative', [('nfs4', 'models'), ('ext4', 'output'), ('autofs', '')])
def test_mounts_are_refused_even_bind_mounts_on_same_device(user_install, monkeypatch, kind, relative):
    root, comfy, _ = user_install
    monkeypatch.setattr(un, '_mounts', lambda: iter([(Path('/'), 'overlay'), (comfy/relative, kind)]))
    with pytest.raises(un.UninstallError, match='mounted/network'):
        un.prepare_plan(un.discover_installation(), comfy)
    assert root.exists() and comfy.exists()


def test_network_ancestor_and_symlink_root_are_refused(user_install, monkeypatch):
    root, comfy, _ = user_install
    alias = comfy.parent/'Comfy alias'
    alias.symlink_to(comfy, target_is_directory=True)
    with pytest.raises(un.UninstallError, match='symlink'):
        un.prepare_plan(un.discover_installation(), alias)
    monkeypatch.setattr(un, '_mounts', lambda: iter([(comfy.parent, 'nfs4')]))
    with pytest.raises(un.UninstallError, match='mounted/network'):
        un.prepare_plan(un.Installation('zip', root), comfy)
    assert root.exists() and comfy.exists()


def test_shared_unverified_and_root_folders_are_refused(user_install, tmp_path):
    root, comfy, _ = user_install
    for path in (Path('/'), Path.home(), tmp_path, comfy/'output'):
        with pytest.raises(un.UninstallError):
            un.prepare_plan(un.discover_installation(), path)
    assert root.exists() and comfy.exists()


def test_live_app_lock_and_invalid_lock_fail_closed(user_install):
    root, _, settings = user_install
    lock = settings/'control.lock'
    lock.write_text(f'{os.getpid()}\ncomfyui-control\nlocalhost\n')
    with pytest.raises(un.UninstallError, match='running'):
        un.prepare_plan(un.discover_installation())
    assert un.prepare_plan(un.discover_installation(), allow_pid=os.getpid())
    lock.write_text('invalid\n')
    with pytest.raises(un.UninstallError, match='lock'):
        un.prepare_plan(un.discover_installation())
    assert root.exists()


def test_separately_started_comfy_process_blocks_folder_removal(user_install):
    root, comfy, _ = user_install
    process = subprocess.Popen([sys.executable, str(comfy/'main.py')], cwd=comfy)
    try:
        with pytest.raises(un.UninstallError, match='ComfyUI is still running'):
            un.prepare_plan(un.discover_installation(), comfy)
        assert root.exists() and comfy.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_cli_defaults_cancel_and_dry_run_do_not_delete(user_install, capsys):
    root, comfy, _ = user_install
    with patch('builtins.input', return_value=''):
        assert un.main([]) == 0
    with patch('builtins.input', side_effect=['2', 'wrong path']):
        assert un.main([]) == 0
    with patch('builtins.input', side_effect=AssertionError('dry run must not ask')):
        assert un.main(['--with-comfyui', '--dry-run']) == 0
    assert root.exists() and comfy.exists()
    assert str(comfy) in capsys.readouterr().out


def test_cli_explicit_comfy_path_confirmation(user_install):
    root, comfy, settings = user_install
    with patch('builtins.input', return_value=str(comfy)):
        assert un.main(['--with-comfyui']) == 0
    assert not root.exists() and not comfy.exists() and settings.exists()


def test_interruption_during_removal_does_not_claim_nothing_was_deleted(user_install, capsys):
    with patch('builtins.input', return_value='y'), patch.object(un, 'execute_plan', side_effect=KeyboardInterrupt):
        assert un.main(['--app-only']) == 1
    output = capsys.readouterr().out
    assert 'Some confirmed files may already have been removed' in output
    assert 'Nothing was deleted' not in output


def test_root_is_refused(user_install, monkeypatch):
    root, _, _ = user_install
    monkeypatch.setattr(un.os, 'geteuid', lambda: 0)
    with pytest.raises(un.UninstallError, match='without sudo'):
        un.prepare_plan(un.discover_installation())
    assert root.exists()


def test_pip_environment_takes_priority_over_a_different_zip_install(user_install, monkeypatch, tmp_path):
    root, _, _ = user_install
    prefix = tmp_path/'another environment'
    package = prefix/'lib/python3.12/site-packages/comfyui_control/__init__.py'
    package.parent.mkdir(parents=True)
    package.touch()
    class Distribution:
        def locate_file(self, name):
            return package
        def read_text(self, name):
            return 'pip\n'
    monkeypatch.setattr(un.sys, 'prefix', str(prefix))
    monkeypatch.setattr(un.sys, 'base_prefix', '/usr')
    monkeypatch.setattr(un.importlib.metadata, 'distribution', lambda name: Distribution())
    assert un.discover_installation().kind == 'pip'
    # The independent installed ZIP helper always targets its own installation.
    monkeypatch.setattr(un, '__file__', str(root/'uninstall.py'))
    assert un.discover_installation().kind == 'zip'


def test_symlinked_data_parent_still_recognizes_the_current_zip_installation(user_install, monkeypatch):
    root, _, _ = user_install
    alias = root.parent.with_name('data-alias')
    alias.symlink_to(root.parent, target_is_directory=True)
    monkeypatch.setenv('XDG_DATA_HOME', str(alias))
    monkeypatch.setattr(un, '__file__', str(root/'venv/lib/python3.12/site-packages/comfyui_control/uninstall.py'))
    installation = un.discover_installation(current_only=True)
    assert installation.kind == 'zip'
    assert installation.root.resolve() == root.resolve()


def test_standalone_installed_script_removes_itself_and_keeps_comfy(user_install):
    if os.getuid() == 0:
        pytest.skip('Standalone removal requires an ordinary user, as documented.')
    root, comfy, settings = user_install
    source = Path(__file__).resolve().parents[1]
    shutil.copyfile(source/'uninstall.sh', root/'uninstall.sh')
    shutil.copyfile(source/'comfyui_control/uninstall.py', root/'uninstall.py')
    result = subprocess.run(['/bin/bash', str(root/'uninstall.sh'), '--app-only'],
                            input='y\n', text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not root.exists() and comfy.exists() and settings.exists()
