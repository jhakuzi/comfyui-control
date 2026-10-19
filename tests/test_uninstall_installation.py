"""Real installer/pip removal in disposable environments with a tiny fixture wheel."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]


def fixture_source(root):
    root.mkdir()
    package = root/'comfyui_control'
    (package/'assets').mkdir(parents=True)
    (package/'__init__.py').write_text('')
    (package/'cli.py').write_text('def main():\n    print("uninstall test fixture")\nif __name__ == "__main__":\n    main()\n')
    for name in ('install.sh', 'uninstall.sh'):
        shutil.copyfile(SOURCE/name, root/name)
    shutil.copyfile(SOURCE/'comfyui_control/uninstall.py', package/'uninstall.py')
    shutil.copyfile(SOURCE/'comfyui_control/assets/comfyui-control.png', package/'assets/comfyui-control.png')
    (root/'pyproject.toml').write_text('[build-system]\nrequires=[]\nbuild-backend="fixture_backend"\nbackend-path=["."]\n')
    (root/'fixture_backend.py').write_text('''
import base64,csv,hashlib,io
from pathlib import Path
import zipfile
def build_wheel(wheel_directory,config_settings=None,metadata_directory=None):
    name='comfyui_control-0.0.0-py3-none-any.whl'
    files={p.relative_to(Path(__file__).parent).as_posix():p.read_bytes()
           for p in (Path(__file__).parent/'comfyui_control').rglob('*') if p.is_file()}
    dist='comfyui_control-0.0.0.dist-info/'
    files[dist+'METADATA']=b'Metadata-Version: 2.1\\nName: comfyui-control\\nVersion: 0.0.0\\n'
    files[dist+'WHEEL']=b'Wheel-Version: 1.0\\nGenerator: uninstall-test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n'
    files[dist+'entry_points.txt']=b'[console_scripts]\\ncomfyui-control = comfyui_control.cli:main\\n'
    record=io.StringIO(); writer=csv.writer(record)
    for key,value in files.items():
        digest=base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b'=').decode()
        writer.writerow([key,'sha256='+digest,str(len(value))])
    writer.writerow([dist+'RECORD','',''])
    files[dist+'RECORD']=record.getvalue().encode()
    with zipfile.ZipFile(Path(wheel_directory)/name,'w') as archive:
        for key,value in files.items(): archive.writestr(key,value)
    return name
''')
    return root


def environment(tmp_path):
    # Deliberately include shell/desktop quoting characters in all install paths.
    home = tmp_path/'home $ with "quotes"'
    home.mkdir()
    return {**os.environ, 'HOME': str(home), 'XDG_DATA_HOME': str(home/'data'),
            'XDG_CONFIG_HOME': str(home/'config'), 'PIP_NO_INDEX': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_CONFIG_FILE': os.devnull}


def run(command, env, **kwargs):
    __tracebackhide__ = True
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.skipif(os.getuid() == 0, reason='Installer/uninstaller intentionally refuse root; verified separately.')
def test_real_install_script_persists_independent_uninstaller_and_removes_owned_shortcuts(tmp_path):
    source = fixture_source(tmp_path/'app source')
    env = environment(tmp_path)
    run(['/bin/bash', str(source/'install.sh')], env, cwd='/tmp')
    root = Path(env['XDG_DATA_HOME'])/'comfyui-control'
    wrapper = Path(env['HOME'])/'.local/bin/comfyui-control'
    desktop = Path(env['XDG_DATA_HOME'])/'applications/comfyui-control.desktop'
    assert (root/'uninstall.sh').exists() and (root/'uninstall.py').exists()
    assert wrapper.exists() and desktop.exists()
    run([str(wrapper)], env)
    # The installed helper must work after the original download is gone.
    shutil.rmtree(source)
    run(['/bin/bash', str(root/'uninstall.sh'), '--app-only'], env, input='y\n')
    assert not root.exists() and not wrapper.exists() and not desktop.exists()


@pytest.mark.skipif(os.getuid() == 0, reason='Standalone per-user removal intentionally refuses root.')
def test_pip_uninstall_keeps_virtual_environment_and_unrelated_files(tmp_path):
    source = fixture_source(tmp_path/'source')
    env = environment(tmp_path)
    venv = tmp_path/'shared venv'
    run([sys.executable, '-m', 'venv', str(venv)], env)
    python = str(venv/'bin/python')
    run([python, '-m', 'pip', 'install', str(source)], env)
    unrelated = venv/'unrelated-user-file'
    unrelated.write_text('keep')
    result = run([python, '-I', str(source/'comfyui_control/uninstall.py'), '--app-only'], env, input='y\n')
    assert 'environment retained' in result.stdout
    assert (venv/'bin/python').exists() and unrelated.read_text() == 'keep'
    assert not (venv/'bin/comfyui-control').exists()
    run([python, '-I', '-c', 'import importlib.metadata; assert not any(d.metadata["Name"] == "comfyui-control" for d in importlib.metadata.distributions())'], env)
