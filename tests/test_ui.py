from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QMessageBox

from comfyui_control.app import LogView, MainWindow, SettingsDialog
from comfyui_control.config import Config


def test_streamed_escape_sequences_and_progress(app):
    log = LogView()
    log.append_output("hello \x1b[3")
    log.append_output("1mred\x1b[0m\r")
    log.append_output("\nnext\n")
    assert log.toPlainText() == "hello red\nnext\n"
    log.append_output("\x1b]0;title\x07clean")
    assert log.toPlainText().endswith("clean")
    log.append_output("\x1b]0;title\x1b\\")
    log.append_output("still visible")
    assert log.toPlainText().endswith("cleanstill visible")


def test_control_states_and_native_folder_open(app, tmp_path):
    (tmp_path / "output").mkdir()
    window = MainWindow(Config(comfy_dir=str(tmp_path)))
    assert window.start_stop.text() == "Start"
    assert window.change_folder.isEnabled()
    assert window.create_script_button.isEnabled()
    window._state_changed("running")
    assert window.start_stop.text() == "Stop"
    assert not window.change_folder.isEnabled()
    assert not window.create_script_button.isEnabled()
    assert not window.config_button.isEnabled()
    window._state_changed("updating")
    assert not window.start_stop.isEnabled()
    with patch("comfyui_control.app.QDesktopServices.openUrl", return_value=True) as opened:
        window._open_folder("output")
        opened.assert_called_once_with(QUrl.fromLocalFile(str(tmp_path / "output")))
    window.close()


def test_change_folder_resets_and_persists_settings(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    new = tmp_path / "new install"
    new.mkdir()
    (new / "main.py").touch()
    window = MainWindow(Config(script="/old/script.sh", mode="script", arguments="--old-flag"))
    with patch("comfyui_control.app.QFileDialog.getExistingDirectory", return_value=str(new)):
        assert window._choose_folder()
    assert window.controller.config.comfy_dir == str(new)
    assert window.controller.config.script == ""
    assert window.controller.config.arguments == ""
    assert Config.load().comfy_dir == str(new)
    window.close()


def test_settings_validate_and_save(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    dialog = SettingsDialog(Config(comfy_dir=str(tmp_path)))
    dialog.arguments.setPlainText('--port 9999 --name "quoted value"')
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert Config.load().arguments == '--port 9999 --name "quoted value"'


def test_close_waits_for_owned_process(app):
    window = MainWindow(Config())
    window.controller.state = "running"
    with patch("comfyui_control.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), patch.object(window.controller, "shutdown") as shutdown:
        assert not window.close()
        shutdown.assert_called_once()
        assert window._closing
    window.controller.state = "stopped"
    assert window.close()


def test_create_script_selects_preset_and_persists_config(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    original = Config(comfy_dir=str(tmp_path), arguments="--reserve-vram 7", output_dir="/custom/output")
    original.save()
    window = MainWindow(original)
    destination = tmp_path / "launch file"
    with patch("comfyui_control.app.LaunchScriptDialog.exec", return_value=QDialog.DialogCode.Accepted), patch("comfyui_control.app.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
        window._create_script()
    script = destination.with_suffix(".sh")
    saved = Config.load()
    assert script.is_file()
    assert saved.mode == "script"
    assert saved.script == str(script)
    assert saved.python == str(tmp_path / "comfy-env" / "bin" / "python")
    assert saved.arguments == "--reserve-vram 7"
    assert saved.managed_script
    assert saved.output_dir == "/custom/output"
    assert window.controller.config == saved
    assert saved.command() == ["/bin/bash", str(script), "--comfyui-control-args", "--reserve-vram", "7"]
    window.close()


def test_cancel_script_creation_leaves_settings_unchanged(app, tmp_path):
    (tmp_path / "main.py").touch()
    original = Config(comfy_dir=str(tmp_path), arguments="--port 9999")
    window = MainWindow(original)
    with patch("comfyui_control.app.LaunchScriptDialog.exec", return_value=QDialog.DialogCode.Accepted), patch("comfyui_control.app.QFileDialog.getSaveFileName", return_value=("", "")):
        window._create_script()
    assert window.controller.config == original
    assert list(tmp_path.iterdir()) == [tmp_path / "main.py"]
    window.close()


def test_create_script_collision_preserves_settings(app, tmp_path):
    (tmp_path / "main.py").touch()
    destination = tmp_path / "launch.sh"
    destination.write_text("existing script")
    original = Config(comfy_dir=str(tmp_path), arguments="--port 9999")
    window = MainWindow(original)
    with patch("comfyui_control.app.LaunchScriptDialog.exec", return_value=QDialog.DialogCode.Accepted), patch("comfyui_control.app.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch("comfyui_control.app.QMessageBox.warning") as warning:
        window._create_script()
    warning.assert_called_once()
    assert destination.read_text() == "existing script"
    assert window.controller.config == original
    window.close()


def test_cancel_flag_selection_does_not_offer_script_file(app, tmp_path):
    (tmp_path / "main.py").touch()
    window = MainWindow(Config(comfy_dir=str(tmp_path)))
    with patch("comfyui_control.app.LaunchScriptDialog.exec", return_value=QDialog.DialogCode.Rejected), patch("comfyui_control.app.QFileDialog.getSaveFileName") as picker:
        window._create_script()
    picker.assert_not_called()
    window.close()


def test_settings_remove_generated_defaults_and_preserve_managed_mode(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    script = tmp_path / "launch.sh"
    script.touch()
    original = Config(comfy_dir=str(tmp_path), mode="script", script=str(script),
                      managed_script=True, arguments="--disable-smart-memory --reserve-vram 1")
    dialog = SettingsDialog(original)
    dialog.launch_options.checkboxes["--disable-smart-memory"].setChecked(False)
    dialog.launch_options.reserve.setChecked(False)
    dialog._save()
    saved = Config.load()
    assert saved.arguments == ""
    assert saved.command() == ["/bin/bash", str(script), "--comfyui-control-args"]


def test_switching_scripts_clears_managed_mode(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    other = tmp_path / "custom.sh"
    other.touch()
    dialog = SettingsDialog(Config(comfy_dir=str(tmp_path), mode="script", script="/old/managed.sh", managed_script=True))
    dialog.script.setText(str(other))
    dialog._save()
    assert not Config.load().managed_script
