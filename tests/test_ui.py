from unittest.mock import patch
from dataclasses import replace

from PySide6.QtCore import QUrl, Qt
from PySide6.QtTest import QTest
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
    (tmp_path / "main.py").touch()
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


def test_update_method_selection_persists_and_is_locked_during_update(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    window = MainWindow(Config(comfy_dir=str(tmp_path)))
    window.update_method.setCurrentIndex(window.update_method.findData("cli"))
    assert Config.load().update_method == "cli"
    window._state_changed("updating")
    assert not window.update_method.isEnabled()
    window._state_changed("stopped")
    assert window.update_method.isEnabled()
    with patch("comfyui_control.app.UpdateDialog") as dialog_class, patch.object(window.controller, "update") as update:
        dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
        dialog_class.return_value.result_config = window.controller.config
        window._update()
    assert dialog_class.call_args.args[0].update_method == "cli"
    update.assert_called_once()
    dialog = SettingsDialog(window.controller.config)
    assert not dialog.requirements.isEnabled()
    dialog.comfy_cli.setText("/path with spaces/comfy")
    dialog._save()
    assert Config.load().comfy_cli == "/path with spaces/comfy"
    assert Config.load().update_method == "cli"
    window.close()


def test_update_dialog_choice_is_saved_before_starting(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    window = MainWindow(Config(comfy_dir=str(tmp_path)))
    chosen = replace(window.controller.config, update_method="cli", python="/chosen/env/bin/python")
    with patch("comfyui_control.app.UpdateDialog") as dialog_class, patch.object(window.controller, "update") as update:
        dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
        dialog_class.return_value.result_config = chosen
        window._update()
        update.assert_called_once()
    assert Config.load() == chosen
    assert window.controller.config == chosen
    assert window.update_method.currentData() == "cli"


def test_cancel_update_does_not_change_settings_or_stop_server(app, tmp_path):
    (tmp_path / "main.py").touch()
    original = Config(comfy_dir=str(tmp_path))
    window = MainWindow(original)
    with patch("comfyui_control.app.UpdateDialog") as dialog_class, patch.object(window.controller, "update") as update:
        dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected
        window._update()
        update.assert_not_called()
    assert window.controller.config == original


def test_header_columns_align_and_stay_put_when_status_changes(app, tmp_path):
    (tmp_path / "main.py").touch()
    window = MainWindow(Config(comfy_dir=str(tmp_path)))
    window.show()
    for width in (680, 800):
        window.resize(width, 570)
        app.processEvents()
        original_left = window.setup_button.x()
        for state in ("stopped", "running", "updating", "stopping"):
            window._state_changed(state)
            app.processEvents()
            assert window.setup_button.x() == window.create_script_button.x() == original_left
            assert window.setup_button.width() == window.create_script_button.width()
            assert window.status.x() == window.change_folder.x()
            assert window.status.width() == window.change_folder.width()
            assert window.setup_button.height() == window.create_script_button.height() == window.change_folder.height()
    window.close()


def test_flags_are_collapsed_until_explicit_edit_and_keep_selections(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    (tmp_path / "main.py").touch()
    script = tmp_path / "script.sh"
    script.touch()
    original = Config(comfy_dir=str(tmp_path), mode="script", script=str(script), managed_script=True, arguments="--disable-smart-memory --reserve-vram 3")
    dialog = SettingsDialog(original)
    dialog.show()
    app.processEvents()
    assert not dialog.flags_contents.isVisible()
    assert dialog.flags_toggle.text() == "Edit script flags"
    QTest.mouseClick(dialog.flags_toggle, Qt.MouseButton.LeftButton)
    assert dialog.flags_contents.isVisible()
    dialog.launch_options.reserve_value.setValue(5)
    QTest.mouseClick(dialog.flags_toggle, Qt.MouseButton.LeftButton)
    assert not dialog.flags_contents.isVisible()
    dialog._save()
    assert "--reserve-vram 5" in Config.load().arguments
    assert "--disable-smart-memory" in Config.load().arguments


def test_custom_script_flags_are_labeled_as_extra_arguments(app, tmp_path):
    dialog = SettingsDialog(Config(comfy_dir=str(tmp_path), mode="script"))
    assert dialog.flags_toggle.text() == "Additional script arguments"
    assert "Edit script file" in dialog.note.text()
    assert not dialog.flags_toggle.isChecked()
