import shlex

import pytest

from comfyui_control.flag_widgets import LaunchFlags, LaunchScriptDialog
from comfyui_control.flags import available_flags, validate_groups
from comfyui_control.config import Config


def test_reads_local_boolean_flags_and_groups_without_running_code(tmp_path):
    path = tmp_path / "comfy" / "cli_args.py"
    path.parent.mkdir()
    sentinel = tmp_path / "must-not-be-created"
    path.write_text(
        f'open({str(sentinel)!r}, "w").write("executed")\n'
        'import argparse\nparser = argparse.ArgumentParser()\n'
        'memory = parser.add_mutually_exclusive_group()\n'
        'memory.add_argument("--future-lowvram", action="store_true", help="New low memory mode")\n'
        'memory.add_argument("--future-cpu", action="store_true")\n'
        'parser.add_argument("--disable-smart-memory", action="store_true")\n'
        'parser.add_argument("--reserve-vram", type=float)\n'
        'parser.add_argument("--port", type=int)\n'
    )
    flags, local, reserve = available_flags(tmp_path)
    assert local and reserve
    assert [flag.name for flag in flags] == ["--future-lowvram", "--future-cpu", "--disable-smart-memory"]
    assert flags[0].group == flags[1].group == "memory"
    assert flags[0].help == "New low memory mode"
    assert not sentinel.exists()
    with pytest.raises(ValueError, match="Choose only one"):
        validate_groups(["--future-lowvram", "--future-cpu"], flags)


def test_checkbox_roundtrip_reserve_vram_and_quoted_extra_arguments(app, tmp_path):
    widget = LaunchFlags(tmp_path, '--disable-smart-memory --reserve-vram=2.5 --output-directory "/a path"')
    assert widget.checkboxes["--disable-smart-memory"].isChecked()
    assert widget.reserve.isChecked()
    assert widget.reserve_value.value() == 2.5
    assert shlex.split(widget.argument_string()) == ["--disable-smart-memory", "--reserve-vram", "2.5", "--output-directory", "/a path"]
    widget.checkboxes["--disable-smart-memory"].setChecked(False)
    widget.reserve.setChecked(False)
    assert shlex.split(widget.argument_string()) == ["--output-directory", "/a path"]


def test_conflicting_flags_are_exclusive_but_can_all_be_unchecked(app, tmp_path):
    widget = LaunchFlags(tmp_path)
    widget.checkboxes["--lowvram"].setChecked(True)
    widget.checkboxes["--cpu"].setChecked(True)
    assert not widget.checkboxes["--lowvram"].isChecked()
    assert widget.checkboxes["--cpu"].isChecked()
    widget.checkboxes["--cpu"].setChecked(False)
    assert widget.argument_string() == ""
    widget.checkboxes["--lowvram"].setChecked(True)
    widget.extra_arguments.setPlainText("--cpu")
    with pytest.raises(ValueError, match="Choose only one"):
        widget.argument_string()


def test_search_does_not_clear_selected_flags(app, tmp_path):
    widget = LaunchFlags(tmp_path, "--disable-smart-memory")
    widget.search.setText("cpu")
    assert widget.checkboxes["--disable-smart-memory"].isHidden()
    assert "--disable-smart-memory" in widget.argument_string()


def test_create_script_dialog_suggests_original_preset(app, tmp_path):
    dialog = LaunchScriptDialog(Config(comfy_dir=str(tmp_path)))
    assert shlex.split(dialog.options.argument_string()) == ["--disable-smart-memory", "--use-pytorch-cross-attention", "--reserve-vram", "1"]
