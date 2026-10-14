import json
import os
import shlex
import subprocess
import sys

import pytest

from comfyui_control.launch_script import create_launch_script


def test_generated_script_activates_venv_and_passes_exact_preset(tmp_path):
    directory = tmp_path / "ComfyUI with 'quotes' $dollars `backticks`"
    bin_dir = directory / "comfy-env" / "bin"
    bin_dir.mkdir(parents=True)
    (directory / "main.py").touch()
    # A stand-in environment records what the launched interpreter receives.
    (bin_dir / "activate").write_text("export ACTIVATION_MARKER=activated\n")
    interpreter = bin_dir / "python"
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'cwd': os.getcwd(), 'activated': os.environ.get('ACTIVATION_MARKER'), "
        "'hip': os.environ.get('PYTORCH_HIP_ALLOC_CONF'), 'args': sys.argv[1:]}))\n"
    )
    interpreter.chmod(0o700)
    destination = tmp_path / "launch script.sh"
    create_launch_script(directory, destination)
    subprocess.run(["bash", "-n", str(destination)], check=True)
    result = subprocess.run(
        [str(destination), "--output-directory", "a path with spaces"],
        cwd=tmp_path, check=True, text=True, capture_output=True,
    )
    recorded = json.loads(result.stdout)
    assert recorded == {
        "cwd": str(directory), "activated": "activated",
        "hip": "expandable_segments:True",
        "args": ["main.py", "--use-pytorch-cross-attention", "--disable-smart-memory",
                 "--reserve-vram", "1", "--output-directory", "a path with spaces"],
    }
    assert os.access(destination, os.X_OK)


@pytest.mark.parametrize("symlink", [False, True])
def test_existing_script_is_not_overwritten(tmp_path, symlink):
    (tmp_path / "main.py").touch()
    original = tmp_path / "original.sh"
    original.write_text("my existing launch script\n")
    destination = tmp_path / "launch.sh" if symlink else original
    if symlink:
        destination.symlink_to(original)
    with pytest.raises(FileExistsError):
        create_launch_script(tmp_path, destination)
    assert original.read_text() == "my existing launch script\n"


def test_activation_failure_does_not_launch_server(tmp_path):
    (tmp_path / "main.py").touch()
    bin_dir = tmp_path / "comfy-env" / "bin"
    bin_dir.mkdir(parents=True)
    marker = tmp_path / "server-started"
    (bin_dir / "activate").write_text("return 1\n")
    interpreter = bin_dir / "python"
    interpreter.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n")
    interpreter.chmod(0o700)
    destination = tmp_path / "launch.sh"
    create_launch_script(tmp_path, destination)
    result = subprocess.run(["bash", str(destination)], capture_output=True)
    assert result.returncode != 0
    assert not marker.exists()
