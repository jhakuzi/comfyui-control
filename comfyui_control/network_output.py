"""NFS mount definition and isolated filesystem worker (standard library only).

Only the explicit desktop setup action runs `setup` as administrator. Normal
probes, gallery scans and image reads always run as the desktop user.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import pwd
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

MAX_IMAGE = 100 * 1024 * 1024
MARKER = '# Managed by comfyui-control NFS output\n'
UNIT_DIRECTORY = Path('/etc/systemd/system')
POLICY_DIRECTORY = Path('/etc/polkit-1/rules.d')
OTHER_UNIT_DIRECTORIES = tuple(Path(path) for path in (
    '/run/systemd/system', '/run/systemd/generator', '/run/systemd/generator.early',
    '/run/systemd/generator.late', '/usr/local/lib/systemd/system',
    '/usr/lib/systemd/system', '/lib/systemd/system'))


def nfs_client_available():
    # sbin is often absent from an ordinary desktop user's PATH.
    return bool(shutil.which('mount.nfs') or any(
        Path(path).is_file() for path in ('/usr/sbin/mount.nfs', '/sbin/mount.nfs')))


def specification(server, export):
    server = server.strip()
    export = export.strip()
    if '%' in server:
        raise ValueError('Use a hostname or an IPv4/global IPv6 address without a zone identifier.')
    try:
        address = ipaddress.ip_address(server.strip('[]'))
        server = f'[{address}]' if address.version == 6 else str(address)
    except ValueError:
        if len(server) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', server):
            raise ValueError('Enter a server IP address or hostname, without a URL or port.')
        if any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in server.split('.')):
            raise ValueError('Enter a valid server hostname.')
        server = server.lower()
    if not re.fullmatch(r'/[A-Za-z0-9_./-]*', export) or '..' in PurePosixPath(export).parts:
        raise ValueError('Enter an absolute NFS export path using letters, numbers, /, dots, hyphens or underscores.')
    export = '/' + str(PurePosixPath(export)).lstrip('/')
    digest = hashlib.sha256(f'{server}:{export}'.encode()).hexdigest()[:16]
    # Fixed root-owned location: a missing mount can never receive local output.
    where = f'/mnt/comfyui-nfs-{digest}'
    # systemd-escape --path: literal hyphens in a path component are escaped.
    unit = 'mnt-comfyui\\x2dnfs\\x2d' + digest
    return {'server': server, 'export': export, 'source': f'{server}:{export}', 'where': where, 'unit': unit}


def units(spec, legacy=False):
    definitions = {
        spec['unit'] + '.mount': MARKER + (
            '[Unit]\nDescription=ComfyUI network output\n'
            'Wants=network-online.target\nAfter=network-online.target\nJobTimeoutSec=15s\n\n'
            f'[Mount]\nWhat={spec["source"]}\nWhere={spec["where"]}\nType=nfs\n'
            'Options=rw,_netdev,nosuid,nodev,noexec\nTimeoutSec=10s\n'),
    }
    if legacy:
        definitions[spec['unit'] + '.automount'] = MARKER + (
            '[Unit]\nDescription=ComfyUI output automount\n\n'
            f'[Automount]\nWhere={spec["where"]}\n\n[Install]\nWantedBy=multi-user.target\n')
    return definitions


def _system_command(command, action, timeout):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or '').strip()[-1600:]
        raise ValueError(f'{action} failed (exit {exc.returncode}). ' +
                         (details or 'No explanation was returned by the system command.')) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'{action} timed out after {timeout} seconds. Check the system mount status before retrying.') from exc


def mount_permission(spec):
    uid = os.getuid()
    if os.geteuid() == 0:
        value = os.environ.get('PKEXEC_UID', os.environ.get('SUDO_UID', str(uid)))
        if not value.isdecimal():
            raise ValueError('Run mount setup/removal through the app or sudo from your normal desktop account.')
        uid = int(value)
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        raise ValueError('The desktop user account could not be identified.') from None
    name = '49-comfyui-control-' + spec['where'].rsplit('-', 1)[1] + '.rules'
    text = ('// Managed by comfyui-control NFS output\n'
            'polkit.addRule(function(action, subject) {\n'
            '    if (action.id === "org.freedesktop.systemd1.manage-units" &&\n'
            f'        subject.user === {json.dumps(username)} &&\n'
            f'        action.lookup("unit") === {json.dumps(spec["unit"] + ".mount")} &&\n'
            '        action.lookup("verb") === "start") {\n'
            '        return polkit.Result.YES;\n'
            '    }\n});\n')
    return POLICY_DIRECTORY / name, text


def check_permission_file(path, contents):
    if path.is_symlink():
        raise ValueError('Refusing to change a symlinked mount permission file.')
    if path.exists():
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or
                path.read_text() != contents):
            raise ValueError('The mount permission file is edited, foreign or belongs to another user. Nothing was changed.')


def managed_unit_files(spec, required=False):
    """Refuse collisions, edits and overrides before any systemd mutation."""
    paths = []
    for name, contents in units(spec, legacy=True).items():
        path = UNIT_DIRECTORY / name
        for directory in (UNIT_DIRECTORY, *OTHER_UNIT_DIRECTORIES):
            candidate = directory / name
            if (directory != UNIT_DIRECTORY and (candidate.exists() or candidate.is_symlink()) or
                    (directory / (name + '.d')).exists()):
                raise ValueError(f'Refusing to change a mount with another system definition or override: {candidate}')
        if path.is_symlink():
            raise ValueError(f'Refusing to change a symlinked system mount definition: {name}')
        if path.exists():
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or
                    path.read_text() != contents):
                raise ValueError(f'Refusing to change a foreign or edited system mount definition: {name}')
            paths.append(path)
        elif required and name.endswith('.mount'):
            raise ValueError(f'The managed mount definition is missing: {name}. Refusing to remove an incomplete setup.')
    return paths


def check_mount_location(spec, owned):
    record = mount_record(spec['where'])
    if record and (not owned or record not in {
            ('nfs', spec['source']), ('nfs4', spec['source']), ('autofs', 'systemd-1')}):
        raise ValueError('The mount location is used by another filesystem or a mount not managed by this app. Nothing was changed.')
    return record


def install_mount(spec):
    if os.geteuid() != 0:
        raise ValueError('Mount setup requires administrator authorization.')
    if not nfs_client_available():
        raise ValueError('Install the NFS client first: Fedora/Arch nfs-utils; Debian/Ubuntu nfs-common.')
    parent = Path('/mnt')
    if parent.is_symlink() or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
        raise ValueError('/mnt must be a root-owned directory without write access for other users.')
    target = Path(spec['where'])
    # Never chmod/chown an already mounted export or unmount someone else's work.
    existing = managed_unit_files(spec)
    record = check_mount_location(spec, bool(existing))
    permission, permission_text = mount_permission(spec)
    check_permission_file(permission, permission_text)
    if POLICY_DIRECTORY.exists():
        info = POLICY_DIRECTORY.stat()
        if POLICY_DIRECTORY.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('The mount permission directory must be root-owned and not writable by other users.')
    if any(path.suffix == '.automount' for path in existing):
        remove_mount(spec)
        record = None
    if not record:
        if target.is_symlink():
            raise ValueError('The mount location must not be a symlink.')
        target.mkdir(mode=0o755, exist_ok=True)
        info = target.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or any(target.iterdir()):
            raise ValueError('The unmounted mount location must be empty, root-owned and not writable by other users.')
    directory = UNIT_DIRECTORY
    definitions = units(spec)
    for name, contents in definitions.items():
        fd, temporary = tempfile.mkstemp(prefix='.comfyui-nfs-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o644)
                stream.write(contents)
            os.replace(temporary, directory / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    restorecon = next((program for program in ('/usr/sbin/restorecon', '/sbin/restorecon') if Path(program).is_file()), None)
    if restorecon:
        _system_command([restorecon, *[str(directory / name) for name in definitions]], 'Restoring SELinux labels for the mount definitions', 10)
    POLICY_DIRECTORY.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.comfyui-permission-', dir=POLICY_DIRECTORY)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(permission_text)
        os.replace(temporary, permission)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if restorecon:
        _system_command([restorecon, str(permission)], 'Restoring SELinux labels for the mount permission', 10)
    _system_command(['/usr/bin/systemctl', 'daemon-reload'], 'Reloading systemd mount definitions', 25)


def remove_mount(spec):
    if os.geteuid() != 0:
        raise ValueError('Mount removal requires administrator authorization.')
    paths = managed_unit_files(spec, required=True)
    check_mount_location(spec, True)
    permission, permission_text = mount_permission(spec)
    check_permission_file(permission, permission_text)
    # systemd stop can propagate to nested mount units. Refuse those rather than
    # allowing removal of our mount to stop somebody else's child mount.
    prefix = spec['where'].rstrip('/') + '/'
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.partition(' - ')[0].split()
        if len(fields) > 4 and unescape_mount(fields[4]).startswith(prefix):
            raise ValueError('Another filesystem is mounted inside this output folder. Remove that nested mount yourself first; nothing was changed.')
    names = {path.name for path in paths}
    dependencies = _system_command(
        ['/usr/bin/systemctl', 'show', '--property=RequiredBy,RequisiteOf,BoundBy,ConsistsOf,PropagatesStopTo', *sorted(names)],
        'Checking whether other system units would be stopped with this mount', 5)
    # A mount/service elsewhere can depend on this mount too. Refuse rather than
    # letting a systemd stop transaction propagate beyond our two units.
    dependents = {unit for line in (dependencies or '').splitlines() for unit in line.partition('=')[2].split()} - names
    if dependents:
        raise ValueError('Other system units depend on this mount: ' + ', '.join(sorted(dependents)) +
                         '. Nothing was changed. Remove those dependencies yourself first.')
    if spec['unit'] + '.automount' in names:
        _system_command(['/usr/bin/systemctl', 'disable', '--now', spec['unit'] + '.automount'],
                        'Disabling the old managed NFS automount', 25)
    _system_command(['/usr/bin/systemctl', 'stop', spec['unit'] + '.mount'],
                    'Unmounting the managed NFS output (close programs using this folder and retry if it is busy)', 25)
    if mount_record(spec['where']):
        raise ValueError('The output folder is still mounted. Its definitions were kept; no files were removed.')
    managed_unit_files(spec, required=True)
    for path in paths:
        path.unlink()
    if permission.exists():
        permission.unlink()
    _system_command(['/usr/bin/systemctl', 'daemon-reload'], 'Reloading systemd mount definitions', 25)
    # Leave the empty local mountpoint alone: never traverse/delete NAS files.


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def mount_record(where):
    # /proc is local even when an NFS server is offline. Never stat the mount
    # to determine whether it is mounted: that can trigger automount/block.
    records = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, _, right = line.partition(' - ')
        fields, filesystem = left.split(), right.split()
        if len(fields) > 4 and len(filesystem) > 1 and unescape_mount(fields[4]) == where:
            records.append((fields[0], fields[1], filesystem[0], unescape_mount(filesystem[1])))
    # Stacked mounts refer to the mount beneath them as their parent. mountinfo
    # line order is not guaranteed, so do not mistake the underlying autofs for
    # the NFS mounted over it (or accept NFS hidden by another filesystem).
    parents = {record[1] for record in records}
    return next(((kind, source) for mount_id, _, kind, source in records
                 if mount_id not in parents), None)


def mounted(spec):
    return mount_record(spec['where']) in {('nfs', spec['source']), ('nfs4', spec['source'])}


def probe(spec):
    mount_file = UNIT_DIRECTORY / (spec['unit'] + '.mount')
    if (UNIT_DIRECTORY / (spec['unit'] + '.automount')).is_file():
        raise ValueError('An older boot-enabled automount setup was found. Stop ComfyUI, then use Set up mount once to replace it with app-triggered mounting.')
    if not mount_file.is_file() and not mounted(spec):
        raise ValueError('Mount setup is not installed. Open Settings → Network output (NFS) and click Save and set up mount. '
                         'You can also use Set up mount beside the network status in the main window.')
    record = mount_record(spec['where'])
    if record and record not in {('nfs', spec['source']), ('nfs4', spec['source'])}:
        raise ValueError('Another filesystem is using the output mount location. No mount was started; inspect it before retrying setup.')
    # Fail quickly for an unreachable NAS before touching its filesystem.
    try:
        with socket.create_connection((spec['server'].strip('[]'), 2049), timeout=2):
            pass
    except OSError as exc:
        raise ValueError(f'Cannot reach NFS server {spec["server"]} on TCP port 2049: {exc}. '
                         'Check that the NAS is online, NFS is enabled, and the LAN/VPN route and firewall allow the connection.') from exc
    root = Path(spec['where'])
    status_command = 'systemctl status ' + shlex.quote(spec['unit'] + '.mount')
    if not mounted(spec):
        try:
            _system_command(['/usr/bin/systemctl', '--no-ask-password', 'start', spec['unit'] + '.mount'],
                            'Starting the NFS mount', 12)
        except ValueError as exc:
            raise ValueError(f'{exc} Check the export path and NAS access rules. '
                             'For an authorization error, use Set up mount once to install the permission for your user. '
                             f'For system details, run: {status_command}') from exc
    if not mounted(spec):
        raise ValueError(f'Linux did not mount {spec["source"]} at {spec["where"]}. '
                         'The start request completed, but the expected NFS filesystem is not active; '
                         'no write was attempted. Check the mount status and use Set up mount if needed. '
                         f'For system details, run: {status_command}')
    try:
        fd, path = tempfile.mkstemp(prefix='.comfyui-write-check-', dir=root)
    except OSError as exc:
        raise ValueError(f'The export {spec["source"]} is mounted, but the write check failed for your user '
                         f'(UID {os.getuid()}, GID {os.getgid()}): {exc}. '
                         'Check the NAS folder permissions, UID/GID mapping and whether the export allows writes.') from exc
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'comfyui-control\n')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.unlink(path)


TRASH_DIRECTORY = '.comfyui-control-trash'


def safe_path(root, descriptor):
    filename = descriptor.get('filename', '')
    subfolder = descriptor.get('subfolder', '')
    if not isinstance(filename, str) or not isinstance(subfolder, str) or not filename or Path(filename).name != filename or '\\' in filename + subfolder:
        return None
    relative = Path(subfolder) / filename
    if relative.is_absolute() or '..' in relative.parts or TRASH_DIRECTORY in relative.parts or relative.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        return None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def read_image(root, descriptor):
    path = safe_path(root, descriptor)
    if path is None:
        raise FileNotFoundError('Image is unavailable.')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        relative = path.relative_to(root)
        for component in relative.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Image is not a regular file.')
            expected = descriptor.get('expected_modified')
            if expected is not None and expected != str(info.st_mtime_ns):
                raise ValueError('This image changed. Refresh the gallery before acting on it.')
            contents = stream.read(MAX_IMAGE + 1)
            if expected is not None and expected != str(os.fstat(stream.fileno()).st_mtime_ns):
                raise ValueError('This image changed while it was being read. Refresh the gallery and try again.')
        if len(contents) > MAX_IMAGE:
            raise ValueError('Image exceeds the 100 MiB network-image limit.')
        return contents
    finally:
        os.close(directory)


def scan(root, references):
    found, valid = [], {}
    for item in references:
        path = safe_path(root, item) if item.get('type', 'output') == 'output' else None
        if path:
            info = path.stat()
            valid[item['id']] = [info.st_mtime, str(info.st_mtime_ns)]
    count = 0
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name != TRASH_DIRECTORY and not (Path(folder) / name).is_symlink()]
        for name in files:
            count += 1
            if count > 10000:
                return {'found': found, 'valid': valid}
            path = Path(folder) / name
            if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'} or path.is_symlink():
                continue
            try:
                if path.is_file():
                    info = path.stat()
                    found.append([info.st_mtime, str(info.st_mtime_ns), str(path.relative_to(root))])
            except OSError:
                pass
    return {'found': found, 'valid': valid}


def _open_directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _trash_directory(root, create=False):
    parent = open_output_directory(root)
    try:
        result = _open_directory(parent, TRASH_DIRECTORY, create)
        info = os.fstat(result)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(result)
            raise ValueError('The app trash must be a private directory owned by this user.')
        return result
    finally:
        os.close(parent)


def _trash_record(directory, token, owner, scope):
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Invalid trash entry.')
    entry = _open_directory(directory, token)
    try:
        fd = os.open('record.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=entry)
        with os.fdopen(fd) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Invalid trash record.')
            record = json.loads(stream.read(16385))
        if record.get('owner') != owner or record.get('scope') != scope or record.get('token') != token:
            raise ValueError('This trash entry belongs to another browser or output folder.')
        filename = record.get('filename', '')
        relative = Path(record.get('subfolder', '')) / filename
        if (not filename or Path(filename).name != filename or relative.is_absolute() or
                '..' in relative.parts or TRASH_DIRECTORY in relative.parts or '\\' in str(relative) or
                relative.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}):
            raise ValueError('Invalid original image location.')
        expected = 'image' + relative.suffix.lower()
        info = os.stat(expected, dir_fd=entry, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Trashed image is not a regular file.')
        return record, expected
    finally:
        os.close(entry)


def image_library(root, operation, data):
    """Recoverable same-filesystem moves, bounded by the existing worker runner.

    Directory descriptors prevent following symlinked parents. No paths supplied
    by an HTTP client reach this function: descriptors come from the gallery.
    Restore uses a no-overwrite hard link before unlinking the trash copy.
    """
    owner, scope = data.get('owner'), data.get('scope')
    if not isinstance(owner, str) or not re.fullmatch('[a-f0-9]{64}', owner) or not isinstance(scope, str):
        raise ValueError('A browser identity and output scope are required.')
    try:
        trash = _trash_directory(root, create=operation == 'trash')
    except FileNotFoundError:
        if operation == 'trash-list':
            return []
        raise
    try:
        if operation == 'trash-list':
            records = []
            for token in os.listdir(trash)[:2000]:
                try:
                    record, _ = _trash_record(trash, token, owner, scope)
                    if not record.get('restored'):
                        entry = _open_directory(trash, record['token'])
                        try:
                            info = os.stat('image' + Path(record['filename']).suffix.lower(), dir_fd=entry, follow_symlinks=False)
                            identity = dict(directories=[list(file_identity(os.fstat(trash))[:2]),
                                                        list(file_identity(os.fstat(entry))[:2])], file=file_identity(info))
                        finally:
                            os.close(entry)
                        records.append({**{k: record[k] for k in ('token', 'filename', 'subfolder', 'created')},
                                        'identity': identity})
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            return sorted(records, key=lambda item: item['created'], reverse=True)
        if operation in ('legacy-read', 'legacy-delete'):
            record, stored = _trash_record(trash, data.get('token'), owner, scope)
            entry = _open_directory(trash, record['token'])
            try:
                fd = os.open(stored, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=entry)
                with os.fdopen(fd, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('Image is not a regular file.')
                    identity = dict(directories=[list(file_identity(os.fstat(trash))[:2]),
                                                list(file_identity(os.fstat(entry))[:2])], file=file_identity(info))
                    if identity != data.get('identity'):
                        raise ValueError('The stored image or location changed. Nothing was deleted.')
                    if operation == 'legacy-read':
                        contents = stream.read(MAX_IMAGE + 1)
                        if len(contents) > MAX_IMAGE:
                            raise ValueError('Image exceeds the image size limit.')
                        return contents
                    if file_identity(os.stat(stored, dir_fd=entry, follow_symlinks=False)) != file_identity(info):
                        raise ValueError('Image changed. Nothing was deleted.')
                    os.unlink(stored, dir_fd=entry)
                os.unlink('record.json', dir_fd=entry)
            finally:
                os.close(entry)
            os.rmdir(record['token'], dir_fd=trash)
            return {'ok': True}
        if operation == 'restore':
            record, stored = _trash_record(trash, data.get('token'), owner, scope)
            entry = _open_directory(trash, record['token'])
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in Path(record['subfolder']).parts:
                    child = _open_directory(parent, part, create=True)
                    os.close(parent)
                    parent = child
                try:
                    os.link(stored, record['filename'], src_dir_fd=entry, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    raise ValueError('An image already exists at the original location. Nothing was overwritten.') from None
                os.unlink(stored, dir_fd=entry)
                os.unlink('record.json', dir_fd=entry)
            finally:
                os.close(parent)
                os.close(entry)
            os.rmdir(record['token'], dir_fd=trash)
            return {'filename': record['filename'], 'subfolder': record['subfolder'], 'type': 'output'}
        descriptor = data['image']
        path = safe_path(root, descriptor)
        if path is None:
            raise FileNotFoundError('This saved image is no longer available.')
        relative = path.relative_to(root)
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        entry = None
        try:
            for part in relative.parts[:-1]:
                child = _open_directory(parent, part)
                os.close(parent)
                parent = child
            info = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or str(info.st_mtime_ns) != data.get('modified'):
                raise ValueError('This image changed. Refresh the gallery before moving it to Trash.')
            import uuid
            token = uuid.uuid4().hex
            os.mkdir(token, mode=0o700, dir_fd=trash)
            entry = _open_directory(trash, token)
            record = dict(token=token, owner=owner, scope=scope, filename=relative.name,
                          subfolder=str(relative.parent) if relative.parent != Path('.') else '', created=time.time())
            fd = os.open('record.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=entry)
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(relative.name, 'image' + relative.suffix.lower(), src_dir_fd=parent, dst_dir_fd=entry)
            return {k: record[k] for k in ('token', 'filename', 'subfolder', 'created')}
        finally:
            os.close(parent)
            if entry is not None:
                os.close(entry)
    finally:
        os.close(trash)


def open_output_directory(root):
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(os.path.abspath(root)).parts[1:]:
            child = _open_directory(parent, part)
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise


def file_identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def virtual_image(root, operation, data):
    """Read/check/unlink an original, anchored to the configured output directory.

    Never follow symlinks, including above the configured root. Fingerprints bind
    markers to the root, every parent and the exact regular file. No filesystem
    writes occur during identify/read; only an explicitly requested delete unlinks.
    """
    descriptor = data['image']
    filename, subfolder = descriptor.get('filename'), descriptor.get('subfolder', '')
    if (not isinstance(filename, str) or not isinstance(subfolder, str) or not filename
            or Path(filename).name != filename or '\\' in filename + subfolder):
        raise ValueError('Invalid original image location.')
    relative = Path(subfolder) / filename
    if (descriptor.get('type', 'output') != 'output' or relative.is_absolute() or '..' in relative.parts
            or TRASH_DIRECTORY in relative.parts or relative.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}):
        raise ValueError('Invalid original image location.')
    # Start at / so even a symlink in the configured root's ancestors fails closed.
    parent = open_output_directory(root)
    try:
        directories = [list(file_identity(os.fstat(parent))[:2])]
        for part in relative.parts[:-1]:
            child = _open_directory(parent, part)
            os.close(parent)
            parent = child
            directories.append(list(file_identity(os.fstat(parent))[:2]))
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Image is not a regular file.')
            identity = dict(directories=directories, file=file_identity(info))
            if operation == 'identify':
                if str(info.st_mtime_ns) != descriptor.get('modified'):
                    raise ValueError('This image changed. Refresh the gallery before deleting it.')
                return identity
            if identity != data.get('identity'):
                raise ValueError('The original file or output location changed. Nothing was deleted. Restore this entry and refresh the gallery.')
            if operation == 'wastebin-read':
                contents = stream.read(MAX_IMAGE + 1)
                if len(contents) > MAX_IMAGE or file_identity(os.fstat(stream.fileno())) != identity['file']:
                    raise ValueError('Image changed or exceeds the image size limit.')
                return contents
            if operation != 'delete':
                raise ValueError('Unknown Wastebin operation.')
            current = open_output_directory(root)
            try:
                for part in relative.parts[:-1]:
                    child = _open_directory(current, part)
                    os.close(current)
                    current = child
                if file_identity(os.fstat(current))[:2] != file_identity(os.fstat(parent))[:2]:
                    raise ValueError('The original directory changed. Nothing was deleted.')
            finally:
                os.close(current)
            # Recheck the directory entry immediately before unlinking through its
            # held parent FD; a substituted symlink/file must never be followed.
            if file_identity(os.stat(relative.name, dir_fd=parent, follow_symlinks=False)) != identity['file']:
                raise ValueError('The original file changed. Nothing was deleted.')
            os.unlink(relative.name, dir_fd=parent)
            return {'ok': True}
    finally:
        os.close(parent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('setup', 'remove', 'probe', 'scan', 'read', 'trash', 'restore', 'trash-list', 'identify', 'delete', 'wastebin-read', 'legacy-delete', 'legacy-read'))
    parser.add_argument('first')
    parser.add_argument('second', nargs='?', default='')
    args = parser.parse_args()
    try:
        if args.operation in ('setup', 'remove', 'probe'):
            spec = specification(args.first, args.second)
            {'setup': install_mount, 'remove': remove_mount, 'probe': probe}[args.operation](spec)
            result = {'ok': True, 'where': spec['where']}
        else:
            root = Path(args.first)
            data = json.load(sys.stdin)
            if re.fullmatch(r'/mnt/comfyui-nfs-[a-f0-9]{16}', str(root)):
                record = mount_record(str(root))
                if not record or record[0] not in ('nfs', 'nfs4'):
                    raise OSError('Network output is not mounted. Retry the connection from the desktop app.')
            if args.operation == 'scan':
                result = scan(root, data)
            elif args.operation in ('identify', 'delete', 'wastebin-read'):
                result = virtual_image(root, args.operation, data)
                if args.operation == 'wastebin-read':
                    sys.stdout.buffer.write(result)
                    return 0
            elif args.operation in ('trash', 'restore', 'trash-list', 'legacy-delete', 'legacy-read'):
                result = image_library(root, args.operation, data)
                if args.operation == 'legacy-read':
                    sys.stdout.buffer.write(result)
                    return 0
            else:
                sys.stdout.buffer.write(read_image(root, data))
                return 0
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)[:2000], 'missing': isinstance(exc, FileNotFoundError)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
