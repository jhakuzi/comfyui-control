import json
import sys

import pytest

from comfyui_control.config import Config, installed_version


def test_atomic_round_trip_and_quoted_flags(tmp_path):
    (tmp_path / "main.py").touch()
    config = Config(comfy_dir=str(tmp_path), python=sys.executable, arguments='--output-directory "/path with spaces" --port 8188')
    config.validate()
    assert config.command()[-4:] == ["--output-directory", "/path with spaces", "--port", "8188"]
    path = tmp_path / "settings" / "config.json"
    config.save(path)
    assert Config.load(path) == config
    assert list(path.parent.iterdir()) == [path]


def test_version_metadata_is_read_without_executing_installation_code(tmp_path):
    marker = tmp_path / 'must-not-execute'
    (tmp_path / 'comfyui_version.py').write_text(f'raise RuntimeError("Do not import")\n__version__ = "0.40.0"\nopen({str(marker)!r}, "w").close()')
    assert installed_version(tmp_path) == '0.40.0'
    assert not marker.exists()
    (tmp_path / 'comfyui_version.py').write_text('__version__ = get_version()')
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "0.41.0-rc.1"')
    assert installed_version(tmp_path) == '0.41.0-rc.1'


def test_version_metadata_without_optional_toml_parser(tmp_path, monkeypatch):
    from comfyui_control import config
    monkeypatch.setattr(config, 'tomllib', None)
    version = tmp_path / 'comfyui_version.py'
    version.write_text('__version__ = "0.40.0"')
    assert installed_version(tmp_path) == '0.40.0'
    version.unlink()
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "0.41.0"')
    assert installed_version(tmp_path) == ''


@pytest.mark.parametrize('contents', ['__version__ = "<b>wrong</b>"', '__version__ = 123', '__version__ = "first\\nsecond"', '!' * 65537, 'not python at all'])
def test_missing_or_invalid_install_version_is_not_invented(tmp_path, contents):
    assert installed_version(tmp_path) == ''
    (tmp_path / 'comfyui_version.py').write_text(contents)
    assert installed_version(tmp_path) == ''


def test_detect_venv_and_script_arguments(tmp_path):
    (tmp_path / "main.py").touch()
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    script = tmp_path / "launch script.sh"
    script.touch()
    config = Config(comfy_dir=str(tmp_path), mode="script", script=str(script), arguments='--port 8188')
    config.validate()
    assert config.interpreter() == str(interpreter)
    assert config.command() == ["/bin/bash", str(script), "--port", "8188"]


@pytest.mark.parametrize("data", [[], {"python": 42}, {"install_requirements": "false"}, {"mode": "shell"}, {"update_method": "shell"}, {"comfy_cli": False},
    {'monitoring_enabled':'false'}, {'auto_restart':1}, {'restart_limit':True}, {'restart_limit':0}, {'restart_limit':21}, {'restart_backoff':0}, {'restart_backoff':61}, {'application_style': False}, {'close_behavior': False}, {'close_behavior':'invalid'}])
def test_invalid_config_rejected_without_overwriting(tmp_path, data):
    path = tmp_path / "config.json"
    original = json.dumps(data)
    path.write_text(original)
    with pytest.raises(ValueError):
        Config.load(path)
    assert path.read_text() == original


def test_bad_folder_and_unmatched_argument_quote(tmp_path):
    config = Config(comfy_dir=str(tmp_path))
    with pytest.raises(ValueError, match="main.py"):
        config.validate()
    (tmp_path / "main.py").touch()
    config.arguments = '--name "broken'
    with pytest.raises(ValueError):
        config.validate()


def test_custom_folder_does_not_modify_launch_flags(tmp_path):
    config = Config(comfy_dir=str(tmp_path), output_dir=str(tmp_path / "different"))
    assert config.folder("output") == tmp_path / "different"
    assert config.folder("models") == tmp_path / "models"
    assert config.arguments == ""


def test_existing_selection_detects_companion_environment(tmp_path):
    directory = tmp_path / "ComfyUI"
    directory.mkdir()
    (directory / "main.py").touch()
    interpreter = tmp_path / "ComfyUI-env" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    config = Config(comfy_dir=str(directory))
    config.validate()
    assert config.interpreter() == str(interpreter)


@pytest.mark.parametrize("kind", ["venv", "conda"])
def test_cli_resolves_global_tool_but_targets_selected_environment(tmp_path, monkeypatch, kind):
    prefix = tmp_path / "environment with spaces"
    (prefix / "bin").mkdir(parents=True)
    python = prefix / "bin" / "python"
    python.symlink_to(sys.executable)
    if kind == "venv":
        (prefix / "pyvenv.cfg").touch()
    else:
        (prefix / "conda-meta").mkdir()
    tools = tmp_path / "global tools"
    tools.mkdir()
    cli = tools / "comfy"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools))
    config = Config(comfy_dir=str(tmp_path / "selected ComfyUI"), python=str(python), update_method="cli")
    command, environment = config.cli_update()
    assert command == [str(cli), "--workspace", config.comfy_dir, "--skip-prompt", "update"]
    assert environment["VIRTUAL_ENV" if kind == "venv" else "CONDA_PREFIX"] == str(prefix)
    assert environment["PATH"].split(":")[0] == str(prefix / "bin")
    config.comfy_cli = str(tools / "missing")
    with pytest.raises(ValueError, match="Comfy CLI was not found"):
        config.cli_update()


def test_cli_rejects_system_python_instead_of_updating_gui_environment(tmp_path):
    config = Config(comfy_dir=str(tmp_path), python="/usr/bin/python3", update_method="cli")
    with pytest.raises(ValueError, match="environment"):
        config.cli_update()


@pytest.mark.parametrize("marker", ["pyvenv.cfg", "bin/activate"])
def test_environment_folder_preserves_python_symlink_and_supports_virtualenv_layouts(tmp_path, marker):
    prefix = tmp_path / "comfy-env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin/python").symlink_to(sys.executable)
    (prefix / marker).touch()
    cli = prefix / "bin/comfy"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o700)
    config = Config(comfy_dir=str(tmp_path / "ComfyUI"), python=str(prefix), update_method="cli")
    assert config.interpreter() == str(prefix / "bin/python")
    command, environment = config.cli_update()
    assert command[0] == str(cli)
    assert environment["VIRTUAL_ENV"] == str(prefix)
