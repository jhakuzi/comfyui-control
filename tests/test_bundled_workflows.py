import json
import time
from unittest.mock import patch

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from comfyui_control import bundled_workflows as workflows
from comfyui_control.workflow_widgets import WorkflowInstallDialog, SETUP_NOTICE
from comfyui_control.app import MainWindow
from comfyui_control.config import Config


@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'ComfyUI'
    root.mkdir()
    (root / 'main.py').write_text('# fixture; never executed')
    return root


def request(root, names=None, replace=None):
    return dict(names=names or [name for name, _ in workflows.WORKFLOWS], replace=replace or [], review=workflows.inspect(root))


def wait_dialog(dialog):
    deadline = time.monotonic() + 5
    while dialog.job is not None and time.monotonic() < deadline:
        QTest.qWait(30)
    assert dialog.job is None, 'Workflow worker did not complete'


def test_inspection_is_read_only_and_selected_install_uses_default_user_path(root):
    review = workflows.inspect(root)
    assert not (root / 'user').exists()
    assert review['target'] == str(root / 'user/default/workflows')
    name = workflows.WORKFLOWS[0][0]
    result = workflows.install(root, dict(names=[name], replace=[], review=review))
    assert result['results'][0]['status'] == 'installed'
    assert (root / workflows.RELATIVE_TARGET / name).read_bytes() == (workflows.ASSETS / name).read_bytes()
    assert list((root / workflows.RELATIVE_TARGET).iterdir()) == [root / workflows.RELATIVE_TARGET / name]
    assert not (root / 'user/workflows').exists()
    assert workflows.inspect(root)['files'][name]['state'] == 'same'


def test_existing_files_default_to_skip_and_replacements_require_review(root):
    target = root / workflows.RELATIVE_TARGET
    target.mkdir(parents=True)
    name = workflows.WORKFLOWS[0][0]
    (target / name).write_bytes(b'keep this user workflow')
    result = workflows.install(root, request(root))
    assert [e['status'] for e in result['results']] == ['skipped', 'installed', 'installed']
    assert (target / name).read_bytes() == b'keep this user workflow'
    reviewed = request(root, [name], [name])
    (target / name).write_bytes(b'user edited after confirmation')
    assert workflows.install(root, reviewed)['results'][0]['status'] == 'error'
    assert (target / name).read_bytes() == b'user edited after confirmation'
    result = workflows.install(root, request(root, [name], [name]))
    assert result['results'][0]['status'] == 'installed'
    assert (target / name).read_bytes() == (workflows.ASSETS / name).read_bytes()
    assert all(e['status'] == 'skipped' for e in workflows.install(root, request(root))['results'])


@pytest.mark.parametrize('part', ['user', 'default', 'workflows'])
def test_symlinked_target_directories_are_not_followed(root, tmp_path, part):
    outside = tmp_path / 'outside'
    outside.mkdir()
    parent = root
    for component in workflows.RELATIVE_TARGET.parts:
        if component == part:
            (parent / component).symlink_to(outside, target_is_directory=True)
            break
        (parent / component).mkdir()
        parent /= component
    with pytest.raises(OSError): workflows.inspect(root)
    assert not list(outside.iterdir())


def test_symlink_file_and_unselected_files_are_untouched(root, tmp_path):
    target = root / workflows.RELATIVE_TARGET
    target.mkdir(parents=True)
    outside = tmp_path / 'outside.json'
    outside.write_bytes(b'outside')
    name = workflows.WORKFLOWS[0][0]
    (target / name).symlink_to(outside)
    (target / 'unselected.json').write_bytes(b'other')
    result = workflows.install(root, request(root, [name], [name]))
    assert result['results'][0]['status'] == 'error'
    assert outside.read_bytes() == b'outside' and (target / name).is_symlink()
    assert (target / 'unselected.json').read_bytes() == b'other'


@pytest.mark.parametrize('change', ['root', 'target'])
def test_replaced_installation_or_target_is_rejected(root, change):
    (root / workflows.RELATIVE_TARGET).mkdir(parents=True)
    reviewed = request(root)
    if change == 'root':
        root.rename(root.with_name('old'))
        root.mkdir()
        (root / 'main.py').touch()
    else:
        (root / workflows.RELATIVE_TARGET).rename(root / 'old-workflows')
        (root / workflows.RELATIVE_TARGET).mkdir()
    with pytest.raises(ValueError, match='changed'): workflows.install(root, reviewed)
    assert not list(root.rglob('*.json'))


def test_file_created_after_preview_is_not_overwritten(root):
    reviewed = request(root)
    target = root / workflows.RELATIVE_TARGET
    target.mkdir(parents=True)
    name = workflows.WORKFLOWS[0][0]
    (target / name).write_bytes(b'created after preview')
    assert workflows.install(root, reviewed)['results'][0]['status'] == 'skipped'
    assert (target / name).read_bytes() == b'created after preview'


def test_partial_copy_error_retains_originals_and_cleans_temp_files(root, monkeypatch):
    original_link = workflows.os.link
    failed = workflows.WORKFLOWS[1][0]
    def link(source, destination, **kwargs):
        if destination == failed: raise PermissionError('fixture read-only target')
        return original_link(source, destination, **kwargs)
    monkeypatch.setattr(workflows.os, 'link', link)
    result = workflows.install(root, request(root))
    assert [e['status'] for e in result['results']] == ['installed', 'error', 'installed']
    assert not list((root / workflows.RELATIVE_TARGET).glob('*.tmp'))
    assert not (root / workflows.RELATIVE_TARGET / failed).exists()


@pytest.mark.parametrize('names', [[], ['../escape.json'], ['unknown.json'], [None], ['VeryComfy.json', 'VeryComfy.json']])
def test_install_selection_is_allowlisted(root, names):
    with pytest.raises(ValueError): workflows.install(root, dict(names=names, review=workflows.inspect(root)))
    assert not (root / 'user').exists()


def test_dialog_cancel_and_selected_install_with_webui_notice(app, root):
    dialog = WorkflowInstallDialog(root, 'http://127.0.0.1:8290')
    wait_dialog(dialog)
    assert all(c.isChecked() for c in dialog.choices.values())
    assert not dialog.replace.isChecked()
    assert 'ComfyUI Manager' in SETUP_NOTICE and 'regular ComfyUI' in SETUP_NOTICE
    assert dialog.destination.text() == str(root / workflows.RELATIVE_TARGET)
    dialog.reject()
    assert not (root / 'user').exists()
    dialog = WorkflowInstallDialog(root, 'http://127.0.0.1:8290')
    wait_dialog(dialog)
    first = workflows.WORKFLOWS[0][0]
    for name, choice in dialog.choices.items(): choice.setChecked(name == first)
    dialog._install()
    wait_dialog(dialog)
    assert '1 installed' in dialog.status.text()
    assert not dialog.open_webui.isHidden()
    with patch('comfyui_control.workflow_widgets.QDesktopServices.openUrl', return_value=True) as opened:
        dialog._open_webui()
        opened.assert_called_once_with(QUrl('http://127.0.0.1:8290'))
    assert len(list((root / workflows.RELATIVE_TARGET).glob('*.json'))) == 1


def test_dialog_replacement_confirmation_and_skip_default(app, root):
    target = root / workflows.RELATIVE_TARGET
    target.mkdir(parents=True)
    name = workflows.WORKFLOWS[0][0]
    (target / name).write_bytes(b'old user graph')
    dialog = WorkflowInstallDialog(root, 'http://127.0.0.1:8188')
    wait_dialog(dialog)
    dialog.replace.setChecked(True)
    with patch('comfyui_control.workflow_widgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
        dialog._install()
    assert dialog.job is None and (target / name).read_bytes() == b'old user graph'
    with patch('comfyui_control.workflow_widgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        dialog._install()
    wait_dialog(dialog)
    assert '3 installed' in dialog.status.text()
    assert (target / name).read_bytes() == (workflows.ASSETS / name).read_bytes()


def test_manual_button_and_once_per_selected_installation_offer(app, root):
    window = MainWindow(Config(comfy_dir=str(root)))
    assert window.workflows_button.isEnabled() and not window._workflow_offers
    with patch('comfyui_control.app.WorkflowInstallDialog') as dialog:
        dialog.return_value.isVisible.return_value = True
        window._offer_workflows(); window._offer_workflows()
        assert dialog.call_count == 1
        window._install_workflows()
        assert dialog.call_count == 1
    window._state_changed('updating')
    assert not window.workflows_button.isEnabled()
    window.close()


@pytest.mark.parametrize('choice', ['existing', 'install'])
def test_setup_completion_offers_same_workflow_dialog(app, root, choice):
    window = MainWindow(Config(comfy_dir=str(root)))
    with patch('comfyui_control.app.WelcomeDialog') as welcome, patch('comfyui_control.app.InstallDialog') as setup, \
         patch.object(window, '_choose_folder', return_value=True), patch.object(window, '_settings'), \
         patch.object(window, '_set_config'), patch.object(window, '_offer_workflows') as offer:
        welcome.return_value.exec.return_value = QDialog.DialogCode.Accepted
        welcome.return_value.choice = choice
        setup.return_value.exec.return_value = QDialog.DialogCode.Accepted
        setup.return_value.result_config = Config(comfy_dir=str(root))
        window._first_setup()
        offer.assert_called_once()
    window.close()


def test_root_changed_between_inspection_and_creation_is_checked_before_mkdir(root, monkeypatch):
    reviewed = request(root)
    original = workflows.open_target
    changed = False
    def open_target(path, create=False, expected_root=None):
        nonlocal changed
        if create and not changed:
            root.rename(root.with_name('old-root'))
            root.mkdir()
            (root / 'main.py').touch()
            changed = True
        return original(path, create=create, expected_root=expected_root)
    monkeypatch.setattr(workflows, 'open_target', open_target)
    with pytest.raises(ValueError, match='changed'):
        workflows.install(root, reviewed)
    assert not (root / 'user').exists()


def test_dialog_worker_error_does_not_retry_or_leave_controls_locked(app, root):
    dialog = WorkflowInstallDialog(root, 'http://127.0.0.1:8188')
    wait_dialog(dialog)
    with patch('comfyui_control.workflow_widgets.BackgroundProcess') as worker:
        worker.return_value.poll.side_effect = TimeoutError('Fixture storage timed out')
        dialog._install()
        dialog._poll()
        assert worker.call_count == 1
        assert dialog.review is None and dialog.cancel.isEnabled() and dialog.refresh.isEnabled()
        assert not dialog.copy.isEnabled()
        assert 'refresh before retrying' in dialog.status.text()


def test_inspection_cancel_does_not_create_workflow_directory(app, root):
    with patch('comfyui_control.workflow_widgets.BackgroundProcess') as worker:
        worker.return_value.poll.return_value = None
        dialog = WorkflowInstallDialog(root, 'http://127.0.0.1:8188')
        assert dialog.cancel.isEnabled()
        dialog.reject()
        worker.return_value.cancel.assert_called_once()
        assert dialog.job is None
    assert not (root / 'user').exists()
