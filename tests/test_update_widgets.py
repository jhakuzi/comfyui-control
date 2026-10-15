from unittest.mock import patch
import sys

from PySide6.QtWidgets import QDialog

from comfyui_control.config import Config
from comfyui_control.update_widgets import UpdateDialog


def test_update_offers_both_methods_and_accepts_git_without_cli(app, tmp_path):
    (tmp_path / "main.py").touch()
    dialog = UpdateDialog(Config(comfy_dir=str(tmp_path), python=sys.executable))
    assert [dialog.method.itemData(i) for i in range(dialog.method.count())] == ["git", "cli"]
    assert "comfy update" in dialog.method.itemText(1)
    assert not dialog.python.parentWidget().isEnabled()
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.result_config.update_method == "git"


def test_cli_choice_selects_environment_and_disables_git_only_pip(app, tmp_path):
    (tmp_path / "main.py").touch()
    config = Config(comfy_dir=str(tmp_path), python=sys.executable, install_requirements=True)
    dialog = UpdateDialog(config)
    dialog.method.setCurrentIndex(dialog.method.findData("cli"))
    assert dialog.python.parentWidget().isEnabled()
    assert not dialog.requirements.isEnabled()
    dialog.python.setText("/selected/venv/bin/python")
    with patch.object(Config, "cli_update", return_value=(["comfy", "update"], {})), patch.object(Config, "validate"):
        dialog._accept()
    assert dialog.result_config.python == "/selected/venv/bin/python"
    assert dialog.result_config.update_method == "cli"
    assert config.update_method == "git"  # Original is untouched until accepted by the main window.


def test_invalid_cli_environment_keeps_dialog_open(app, tmp_path):
    (tmp_path / "main.py").touch()
    dialog = UpdateDialog(Config(comfy_dir=str(tmp_path), python="/usr/bin/python3", update_method="cli"))
    with patch("comfyui_control.update_widgets.QMessageBox.warning") as warning:
        dialog._accept()
    assert dialog.result_config is None
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "Choose environment" in warning.call_args.args[2]


def test_git_requirements_enable_python_but_do_not_require_comfy_cli(app, tmp_path):
    (tmp_path / "main.py").touch()
    dialog = UpdateDialog(Config(comfy_dir=str(tmp_path), python=sys.executable))
    dialog.requirements.setChecked(True)
    assert dialog.python.parentWidget().isEnabled()
    with patch.object(Config, "cli_update") as cli:
        dialog._accept()
    cli.assert_not_called()
    assert dialog.result_config.install_requirements


def test_picker_chooses_environment_directory_without_resolving_python_symlink(app, tmp_path):
    (tmp_path / "main.py").touch()
    prefix = tmp_path / "comfy-env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin/python").symlink_to(sys.executable)
    (prefix / "pyvenv.cfg").touch()
    cli = prefix / "bin/comfy"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o700)
    dialog = UpdateDialog(Config(comfy_dir=str(tmp_path), update_method="cli"))
    with patch("comfyui_control.update_widgets.QFileDialog.getExistingDirectory", return_value=str(prefix)):
        dialog._browse_python()
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.result_config.interpreter() == str(prefix / "bin/python")
