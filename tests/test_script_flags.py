import shlex

from comfyui_control.launch_script import create_launch_script
from comfyui_control.script_flags import inspect_script


def test_reads_users_multiline_script_without_running_it(tmp_path):
    marker = tmp_path / "never-execute"
    script = tmp_path / "start-comfy.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"touch {shlex.quote(str(marker))}\n"
        "cd /some/install; or exit 1\n"
        "source comfy-env/bin/activate; or exit 1\n"
        "cd ComfyUI; or exit 1\n"
        "python main.py \\\n"
        " --use-pytorch-cross-attention \\\n"
        " --reserve-vram 3 \\\n"
        " --listen \\\n"
        " --enable-manager\n"
    )
    result = inspect_script(script)
    assert result.arguments == ("--use-pytorch-cross-attention", "--reserve-vram", "3", "--listen", "--enable-manager")
    assert not result.message
    assert not marker.exists()


def test_exec_env_and_quoted_values_exclude_forwarding_and_redirection(tmp_path):
    script = tmp_path / "launch.sh"
    script.write_text('exec env HIP_FLAG=1 "/a path/bin/python3.14" -u main.py --output-directory "a path" --cpu "$@" >server.log\n')
    assert inspect_script(script).arguments == ("--output-directory", "a path", "--cpu")


def test_recognizes_standalone_defaults_in_app_created_script(tmp_path):
    (tmp_path / "main.py").touch()
    script = tmp_path / "launch.sh"
    create_launch_script(tmp_path, script, ["--cpu", "--reserve-vram", "2"])
    assert inspect_script(script).arguments == ("--cpu", "--reserve-vram", "2")


def test_does_not_guess_between_conditional_launch_commands(tmp_path):
    script = tmp_path / "launch.sh"
    script.write_text('if test -n "$CPU"; then\npython main.py --cpu\nelse\npython main.py --highvram\nfi\n')
    result = inspect_script(script)
    assert not result.arguments
    assert "single" in result.message


def test_reports_dynamic_values_without_expanding_them(tmp_path):
    script = tmp_path / "launch.sh"
    script.write_text('python main.py --reserve-vram "$VRAM" --cpu "$@"\n')
    result = inspect_script(script)
    assert result.arguments == ("--reserve-vram", "$VRAM", "--cpu")
    assert "not executed" in result.message


def test_missing_script_is_reported(tmp_path):
    assert "Could not read" in inspect_script(tmp_path / "missing").message
