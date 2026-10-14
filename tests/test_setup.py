import json
import subprocess
import sys
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QDialog

from comfyui_control.app import MainWindow
from comfyui_control.config import Config
from comfyui_control.setup import InstallDialog, InstallPlan, PYTHON_COMMANDS, WelcomeDialog


@pytest.fixture
def fake_python(tmp_path):
    executable = tmp_path / "python3.13"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, shlex, shutil, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['-m', 'venv']:\n"
        "    env = pathlib.Path(args[2])\n"
        "    (env / 'bin').mkdir(parents=True)\n"
        "    for name in ('python', 'comfy'):\n"
        "        target = env / 'bin' / name\n"
        "        shutil.copyfile(sys.argv[0], target)\n"
        "        target.chmod(0o700)\n"
        "    (env / 'bin' / 'activate').write_text('export VIRTUAL_ENV=' + shlex.quote(str(env)) + '\\n')\n"
        "elif args[:3] == ['-m', 'pip', 'install']:\n"
        "    assert args == ['-m', 'pip', 'install', 'comfy-cli']\n"
        "    pathlib.Path(sys.argv[0]).parent.parent.joinpath('pip-called').touch()\n"
        "elif args[:1] == ['--workspace']:\n"
        "    if os.environ.get('SIMULATE_INSTALL_FAILURE'): sys.exit(9)\n"
        "    assert args[2] == 'install'\n"
        "    env = pathlib.Path(sys.argv[0]).parent.parent\n"
        "    assert os.environ['VIRTUAL_ENV'] == str(env)\n"
        "    assert (env / 'pip-called').is_file()\n"
        "    target = pathlib.Path(args[1])\n"
        "    target.mkdir()\n"
        "    (target / 'main.py').write_text('# fake ComfyUI')\n"
        "    (env / 'cli-args.json').write_text(json.dumps(args))\n"
        "else:\n"
        f"    os.execv({sys.executable!r}, [{sys.executable!r}, *args])\n"
    )
    executable.chmod(0o700)
    return executable


def test_setup_runs_venv_pip_and_comfy_at_chosen_location(tmp_path, fake_python):
    target = tmp_path / "Folder with 'quotes' $dollars `backticks`"
    plan = InstallPlan(target, str(fake_python), "--amd")
    plan.validate()
    result_path = tmp_path / "result.json"
    script = tmp_path / "setup.sh"
    script.write_text(plan.script(result_path))
    subprocess.run(["bash", "-n", str(script)], check=True)
    subprocess.run(["bash", str(script)], check=True, capture_output=True, text=True)
    assert (target / "main.py").is_file()
    assert plan.environment.parent == target.parent
    assert not plan.environment.is_relative_to(target)
    assert json.loads(result_path.read_text()) == {"directory": str(target), "python": str(plan.environment / "bin" / "python")}
    assert json.loads((plan.environment / "cli-args.json").read_text()) == ["--workspace", str(target), "install", "--amd"]


def test_setup_refuses_existing_installation_without_touching_it(tmp_path, fake_python):
    target = tmp_path / "ComfyUI"
    target.mkdir()
    original = target / "main.py"
    original.write_text("my installation")
    plan = InstallPlan(target, str(fake_python))
    with pytest.raises(ValueError, match="already exists"):
        plan.validate()
    script = tmp_path / "setup.sh"
    result = tmp_path / "result.json"
    script.write_text(plan.script(result))
    completed = subprocess.run(["bash", str(script)], capture_output=True)
    assert completed.returncode != 0
    assert original.read_text() == "my installation"
    assert not plan.environment.exists()
    assert not result.exists()


def test_unsupported_python_stops_before_creating_folders(tmp_path):
    executable = tmp_path / "python3"
    executable.write_text("#!/bin/sh\necho 'Select Python 3.12 or 3.13' >&2\nexit 1\n")
    executable.chmod(0o700)
    plan = InstallPlan(tmp_path / "ComfyUI", str(executable))
    result = tmp_path / "result.json"
    script = tmp_path / "setup.sh"
    script.write_text(plan.script(result))
    completed = subprocess.run(["bash", str(script)], capture_output=True)
    assert completed.returncode != 0
    assert not plan.directory.exists()
    assert not plan.environment.exists()
    assert not result.exists()


def test_cli_failure_does_not_create_success_marker(tmp_path, fake_python, monkeypatch):
    monkeypatch.setenv("SIMULATE_INSTALL_FAILURE", "1")
    plan = InstallPlan(tmp_path / "ComfyUI", str(fake_python))
    result = tmp_path / "result.json"
    script = tmp_path / "setup.sh"
    script.write_text(plan.script(result))
    completed = subprocess.run(["bash", str(script)], capture_output=True)
    assert completed.returncode == 9
    assert not result.exists()
    assert not (plan.directory / "main.py").exists()


@pytest.mark.parametrize("gpu", ["", "--cpu"])
def test_installer_selects_only_successful_result(app, tmp_path, fake_python, monkeypatch, gpu):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    dialog = InstallDialog()
    target = tmp_path / "ComfyUI"
    dialog.location.setText(str(target))
    dialog.python.setText(str(fake_python))
    dialog.gpu.setCurrentIndex(dialog.gpu.findData(gpu))
    with patch("comfyui_control.setup.terminal_command", return_value=["konsole", "-e", "bash"]), patch("comfyui_control.setup.QProcess.startDetached", return_value=(True, 123)):
        dialog._open_terminal()
    assert not dialog.use_installation.isEnabled()
    assert dialog.result_config is None
    dialog._check_result()
    assert dialog.result_config is None
    subprocess.run(["bash", str(dialog.script_path)], check=True, capture_output=True)
    dialog._check_result()
    assert dialog.use_installation.isEnabled()
    dialog._use_installation()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert Config.load().comfy_dir == str(target)
    assert Config.load().python == str(dialog.plan.environment / "bin" / "python")
    assert Config.load().arguments == ("--cpu" if gpu == "--cpu" else "")


def test_welcome_choices_and_unconfigured_controls(app):
    assert Config().comfy_dir == ""
    welcome = WelcomeDialog()
    welcome._choose("existing")
    assert welcome.choice == "existing"
    assert welcome.result() == QDialog.DialogCode.Accepted
    window = MainWindow(Config())
    assert window.path_label.text() == "No installation selected"
    assert not window.start_stop.isEnabled()
    assert not window.create_script_button.isEnabled()
    assert window.change_folder.isEnabled()
    assert window.setup_button.isEnabled()
    with patch("comfyui_control.app.WelcomeDialog.exec", return_value=QDialog.DialogCode.Rejected), patch.object(window, "_choose_folder") as picker:
        window._first_setup()
    picker.assert_not_called()
    window.close()


def test_distro_instructions_include_fedora_dnf(app):
    assert "sudo dnf install" in PYTHON_COMMANDS["Fedora"]
    assert "sudo apt install" in PYTHON_COMMANDS["Ubuntu / Debian"]
    assert "sudo pacman -S" in PYTHON_COMMANDS["Arch Linux"]
    dialog = InstallDialog()
    assert "sudo dnf install" in dialog.package_commands.toPlainText()
    dialog.distro.setCurrentText("Arch Linux")
    assert "sudo pacman" in dialog.package_commands.toPlainText()
