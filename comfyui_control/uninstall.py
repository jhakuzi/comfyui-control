"""Per-user uninstallation, also runnable as a standalone standard-library script."""
import argparse
from dataclasses import dataclass
import errno
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


class UninstallError(ValueError):
    pass


def user_paths():
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')).expanduser()
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')).expanduser()
    if not data.is_absolute() or not config.is_absolute():
        raise UninstallError('XDG data and configuration folders must use absolute paths.')
    return data / 'comfyui-control', home / '.local/bin/comfyui-control', data / 'applications/comfyui-control.desktop', config / 'comfyui-control'


@dataclass(frozen=True)
class Installation:
    kind: str
    root: Path
    python: str = ''

    @property
    def description(self):
        return str(self.root) if self.kind == 'zip' else f'comfyui-control package in {self.root} (environment retained)'


def discover_installation(*, current_only=False):
    root = user_paths()[0]
    package = Path(__file__).resolve()
    canonical_root = root.resolve()
    zip_install = (root / 'venv/pyvenv.cfg').is_file() and any((root / 'venv/lib').glob('python*/site-packages/comfyui_control/__init__.py'))
    zip_current = package.is_relative_to(canonical_root) or Path(sys.prefix).resolve() == canonical_root / 'venv'
    if zip_install and (zip_current or not current_only and package.parent == canonical_root):
        if root.is_symlink():
            raise UninstallError('The per-user app folder is a symlink. Remove its target manually after checking the location.')
        return Installation('zip', root.absolute())
    prefix = Path(sys.prefix).resolve()
    if sys.prefix != sys.base_prefix:
        try:
            dist = importlib.metadata.distribution('comfyui-control')
            location = Path(dist.locate_file('comfyui_control/__init__.py')).resolve()
            if location.is_relative_to(prefix) and location.is_file() and dist.read_text('INSTALLER').strip() == 'pip':
                if not current_only or package.is_relative_to(prefix):
                    return Installation('pip', prefix, sys.executable)
        except (importlib.metadata.PackageNotFoundError, AttributeError):
            pass
    if zip_install and not current_only:
        if root.is_symlink():
            raise UninstallError('The per-user app folder is a symlink. Remove its target manually after checking the location.')
        return Installation('zip', root.absolute())
    raise UninstallError('Automatic removal supports install.sh installations and pip virtual environments. '
                         'For an RPM installation, use sudo dnf remove comfyui-control. '
                         'For a source checkout, keep the checkout or remove it manually; activate its pip environment to uninstall the package.')


def _mounts():
    try:
        lines = Path('/proc/self/mountinfo').read_text().splitlines()
    except OSError as exc:
        raise UninstallError('Cannot check mounted folders; nothing will be deleted.') from exc
    for line in lines:
        before, after = line.split(' - ', 1)
        fields = before.split()
        path = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
        yield Path(path), after.split()[0]


def guard_tree(path):
    """Never traverse mount points, including bind mounts on the same device."""
    for mounted, kind in _mounts():
        if mounted == path or mounted.is_relative_to(path) or (
                path.is_relative_to(mounted) and kind.startswith(('nfs', 'cifs', 'smb', 'fuse.sshfs'))):
            raise UninstallError(f'Refusing to delete mounted/network data: {mounted}. '
                                 'Unmount it first or choose app-only removal. NAS files are never removed by this uninstaller.')


def _identity(path):
    value = path.lstat()
    if path.is_symlink() or not path.is_dir() or value.st_uid != os.getuid():
        raise UninstallError(f'Refusing to remove a symlink or a folder not owned by this user: {path}')
    return value.st_dev, value.st_ino


def check_comfy_folder(value):
    if not value or not str(value).strip():
        raise UninstallError('No ComfyUI folder is configured. Choose app-only removal.')
    path = Path(os.path.expandvars(str(value))).expanduser().absolute()
    # Check mounts before accessing possible unavailable network storage.
    guard_tree(path)
    if path.is_symlink():
        raise UninstallError('The configured ComfyUI folder is a symlink. Its target will not be deleted automatically.')
    path = path.resolve(strict=True)
    guard_tree(path)
    root, _, _, settings = user_paths()
    protected = {Path('/'), Path.home().resolve(), *(Path(p) for p in
                 ('/home', '/usr', '/etc', '/var', '/opt', '/mnt', '/media', '/run', '/tmp', '/workspace'))}
    if path in protected or root.resolve().is_relative_to(path) or settings.resolve().is_relative_to(path):
        raise UninstallError(f'This is a shared or protected folder, not a removable ComfyUI installation: {path}')
    _identity(path)
    if not all((path / name).is_file() and not (path / name).is_symlink() for name in ('main.py', 'folder_paths.py')) or not (path / 'comfy').is_dir():
        raise UninstallError(f'Cannot verify a ComfyUI installation at {path}. Expected main.py, folder_paths.py and the comfy folder. Nothing was deleted.')
    return path


def check_running(allow_pid=None, comfy=None):
    lock = user_paths()[3] / 'control.lock'
    if lock.exists():
        try:
            pid = int(lock.read_text().splitlines()[0])
            if not 0 < pid < 2**31:
                raise ValueError()
        except (ValueError, IndexError):
            raise UninstallError('Cannot verify the existing app lock. Close ComfyUI Control and check its lock file before uninstalling.') from None
        if pid != allow_pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError:
                raise UninstallError('ComfyUI Control may be running under another user. Close it before uninstalling.') from None
            else:
                raise UninstallError('ComfyUI Control is running. Quit it completely, including its tray/SSH session, then retry.')
    if comfy is not None:
        for process in Path('/proc').iterdir():
            if not process.name.isdecimal() or int(process.name) == os.getpid():
                continue
            try:
                args = (process / 'cmdline').read_bytes().split(b'\0')
                for arg in args:
                    if arg == b'main.py' or arg.endswith(b'/main.py'):
                        candidate = Path(os.fsdecode(arg))
                        if not candidate.is_absolute():
                            candidate = (process / 'cwd').resolve() / candidate
                        if candidate.resolve() == comfy / 'main.py':
                            raise UninstallError(f'ComfyUI is still running (PID {process.name}). Stop it before removing {comfy}.')
            except (OSError, RuntimeError):
                continue


@dataclass(frozen=True)
class UninstallPlan:
    installation: Installation
    app_identity: tuple
    comfy: Path | None = None
    comfy_identity: tuple | None = None
    environment_identity: tuple | None = None


def prepare_plan(installation, comfy_dir=None, *, allow_pid=None, check_server=True):
    if os.geteuid() == 0:
        raise UninstallError('Run the uninstaller as your normal user, without sudo.')
    guard_tree(installation.root.resolve())
    identity = _identity(installation.root)
    environment_identity = None
    if installation.kind == 'zip':
        environment = installation.root / 'venv'
        environment_identity = _identity(environment)
        # App-only removal must never erase a configured ComfyUI/data folder
        # accidentally placed in the dedicated app environment.
        settings = saved_configuration()
        for key in ('comfy_dir', 'models_dir', 'output_dir'):
            value = settings.get(key)
            if isinstance(value, str) and value.strip():
                candidate = Path(os.path.expandvars(value)).expanduser().absolute()
                # Do not probe configured NAS/model mounts just to uninstall
                # a local environment. Local aliases into it need protection.
                resolved = candidate
                try:
                    guard_tree(candidate)
                    resolved = candidate.resolve()
                except UninstallError:
                    pass
                if candidate.is_relative_to(environment) or resolved.is_relative_to(environment.resolve()):
                    raise UninstallError(f'The configured {key} is inside the app environment: {candidate}. '
                                         'Move that data and update Settings before uninstalling.')
    comfy = check_comfy_folder(comfy_dir) if comfy_dir is not None else None
    if comfy and (installation.root.resolve().is_relative_to(comfy) or comfy.is_relative_to(installation.root.resolve())):
        raise UninstallError('The app environment and ComfyUI folder overlap. Remove them manually after checking their contents.')
    check_running(allow_pid, comfy if check_server else None)
    return UninstallPlan(installation, identity, comfy, _identity(comfy) if comfy else None, environment_identity)


def _owned_launcher(path, executable, desktop=False):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        return False
    if path.stat().st_size > 65536:
        return False
    text = path.read_text()
    if not desktop:
        return text in {'#!/bin/sh\nexec ' + shlex.quote(str(executable)) + ' "$@"\n',
                        '#!/bin/sh\nexec ' + shlex.quote(str(executable.with_name('python'))) + ' -I -m comfyui_control.cli "$@"\n'}
    for program, suffix in ((executable, ''), (executable.with_name('python'), ' -I -m comfyui_control.cli')):
        quoted = str(program).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%').replace('\\', '\\\\')
        if f'Exec="{quoted}"{suffix}' in text.splitlines():
            return True
    return False


def execute_plan(plan, *, allow_pid=None):
    """Called only after explicit confirmation and application shutdown."""
    if _identity(plan.installation.root) != plan.app_identity:
        raise UninstallError('The app folder changed after confirmation. Nothing was deleted; review it and retry.')
    fresh = prepare_plan(plan.installation, plan.comfy, allow_pid=allow_pid)
    if fresh != plan:
        raise UninstallError('An installation folder changed after confirmation. Nothing was deleted; review it and retry.')
    installation = plan.installation
    if installation.kind == 'zip':
        root, wrapper, desktop, _ = user_paths()
        if root.absolute() != installation.root:
            raise UninstallError('The per-user installation location changed. Nothing was deleted.')
        executable = root / 'venv/bin/comfyui-control'
        for path, is_desktop in ((wrapper, False), (desktop, True)):
            if _owned_launcher(path, executable, is_desktop):
                path.unlink()
        shutil.rmtree(installation.root / 'venv')
        for name in ('comfyui-control.png', 'uninstall.sh', 'uninstall.py'):
            path = installation.root / name
            if path.is_file() or path.is_symlink():
                path.unlink()
        try:
            installation.root.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
    elif installation.kind == 'pip':
        result = subprocess.run([installation.python, '-I', '-m', 'pip', 'uninstall', '--yes', 'comfyui-control'],
                                cwd='/', capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise UninstallError('pip could not remove the app; ComfyUI was kept.\n' + (result.stderr or result.stdout)[-3000:])
    else:
        raise UninstallError('Unsupported installation type; nothing was deleted.')
    if plan.comfy:
        # Recheck after package removal too; never recurse into a newly mounted tree.
        guard_tree(plan.comfy)
        if _identity(plan.comfy) != plan.comfy_identity:
            raise UninstallError('The app was removed, but the ComfyUI folder changed and was kept.')
        shutil.rmtree(plan.comfy)
    return ('ComfyUI Control was uninstalled.' + (' The confirmed ComfyUI folder was also removed.' if plan.comfy else ' ComfyUI was kept.') +
            '\nApp settings, mobile history, external environments, external model/output folders and NAS files were kept.')


def saved_configuration():
    path = user_paths()[3] / 'config.json'
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, AttributeError) as exc:
        raise UninstallError(f'Cannot read the saved folder settings at {path}. Review them before uninstalling.') from exc


def saved_comfy_folder():
    value = saved_configuration().get('comfy_dir', '')
    return os.path.expandvars(value) if isinstance(value, str) else ''


def main(argv=None):
    parser = argparse.ArgumentParser(description='Uninstall ComfyUI Control as your normal user. Settings are retained.')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--app-only', action='store_true', help='Remove only the app; keep ComfyUI.')
    choice.add_argument('--with-comfyui', action='store_true', help='Also remove the configured ComfyUI folder after path confirmation.')
    parser.add_argument('--dry-run', action='store_true', help='Show the removal plan without deleting files.')
    args = parser.parse_args(argv)
    executing = False
    try:
        installation = discover_installation()
        both = args.with_comfyui
        if not args.app_only and not both and not args.dry_run:
            print('1. Uninstall only ComfyUI Control (keep ComfyUI)\n2. Also remove the configured ComfyUI folder\nEnter cancels.')
            selected = input('Choice: ').strip()
            if selected not in {'1', '2'}:
                print('Cancelled. Nothing was deleted.')
                return 0
            both = selected == '2'
        plan = prepare_plan(installation, saved_comfy_folder() if both else None)
        print('App: ' + installation.description)
        if plan.comfy:
            print(f'PERMANENTLY DELETE: {plan.comfy}\nIncludes models, workflows, custom nodes and images physically stored inside this folder.')
        print('Keep: app settings/history, external environments, external model/output folders and NAS data. '
              'App-managed NFS definitions are kept; use Remove mount in the app before uninstalling to remove those too.')
        if args.dry_run:
            return 0
        if plan.comfy:
            confirmed = input('Type the full ComfyUI path above to confirm deletion: ').strip() == str(plan.comfy)
        else:
            confirmed = input('Uninstall the app? [y/N]: ').strip().lower() in {'y', 'yes'}
        if not confirmed:
            print('Cancelled. Nothing was deleted.')
            return 0
        executing = True
        print(execute_plan(plan))
        return 0
    except (UninstallError, OSError, subprocess.SubprocessError) as exc:
        print('Uninstall stopped: ' + str(exc), file=sys.stderr)
        if executing:
            print('Some confirmed files may already have been removed. App settings were kept.', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nUninstall interrupted. Some confirmed files may already have been removed. App settings were kept.'
              if executing else '\nCancelled. Nothing was deleted.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
