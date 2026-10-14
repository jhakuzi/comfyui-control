import json
import sys

import pytest

from comfyui_control.config import Config


def test_atomic_round_trip_and_quoted_flags(tmp_path):
    (tmp_path / "main.py").touch()
    config = Config(comfy_dir=str(tmp_path), python=sys.executable, arguments='--output-directory "/path with spaces" --port 8188')
    config.validate()
    assert config.command()[-4:] == ["--output-directory", "/path with spaces", "--port", "8188"]
    path = tmp_path / "settings" / "config.json"
    config.save(path)
    assert Config.load(path) == config
    assert list(path.parent.iterdir()) == [path]


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


@pytest.mark.parametrize("data", [[], {"python": 42}, {"install_requirements": "false"}, {"mode": "shell"}])
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
