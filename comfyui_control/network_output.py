"""NFS automount definition and isolated filesystem worker (standard library only).

Only the explicit desktop setup action runs `setup` as administrator. Normal
probes, gallery scans and image reads always run as the desktop user.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

MAX_IMAGE = 100 * 1024 * 1024
MARKER = '# Managed by comfyui-control NFS output\n'


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


def units(spec):
    return {
        spec['unit'] + '.mount': MARKER + (
            '[Unit]\nDescription=ComfyUI network output\n'
            'Wants=network-online.target\nAfter=network-online.target\nJobTimeoutSec=15s\n\n'
            f'[Mount]\nWhat={spec["source"]}\nWhere={spec["where"]}\nType=nfs\n'
            'Options=rw,_netdev,nosuid,nodev,noexec\nTimeoutSec=10s\n'),
        spec['unit'] + '.automount': MARKER + (
            '[Unit]\nDescription=ComfyUI output automount\n\n'
            f'[Automount]\nWhere={spec["where"]}\n\n[Install]\nWantedBy=multi-user.target\n'),
    }


def _system_command(command, action, timeout):
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or '').strip()[-1600:]
        raise ValueError(f'{action} failed (exit {exc.returncode}). ' +
                         (details or 'No explanation was returned by the system command.')) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'{action} timed out after {timeout} seconds. Check the system mount status before retrying.') from exc


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
    record = mount_record(spec['where'])
    if record and record != ('nfs', spec['source']) and record != ('nfs4', spec['source']) and record[0] != 'autofs':
        raise ValueError('The mount location is already used by another filesystem.')
    if not record:
        if target.is_symlink():
            raise ValueError('The mount location must not be a symlink.')
        target.mkdir(mode=0o755, exist_ok=True)
        info = target.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or any(target.iterdir()):
            raise ValueError('The unmounted mount location must be empty, root-owned and not writable by other users.')
    directory = Path('/etc/systemd/system')
    definitions = units(spec)
    for name, contents in definitions.items():
        path = directory / name
        if path.is_symlink() or path.exists() and (path.stat().st_uid != 0 or not path.read_text().startswith(MARKER)):
            raise ValueError(f'Refusing to replace an existing system mount definition: {name}')
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
    for args, action in ((['daemon-reload'], 'Reloading systemd mount definitions'),
                         (['enable', '--now', spec['unit'] + '.automount'], 'Enabling the NFS automount')):
        _system_command(['/usr/bin/systemctl', *args], action, 25)


def mount_record(where):
    # /proc is local even when an NFS server is offline. Never stat the mount
    # to determine whether it is mounted: that can trigger automount/block.
    def unescape(value):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    result = None
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, _, right = line.partition(' - ')
        fields, filesystem = left.split(), right.split()
        if len(fields) > 4 and len(filesystem) > 1 and unescape(fields[4]) == where:
            # NFS sits over the automount; retain the topmost matching entry.
            result = (filesystem[0], unescape(filesystem[1]))
    return result


def mounted(spec):
    return mount_record(spec['where']) in {('nfs', spec['source']), ('nfs4', spec['source'])}


def probe(spec):
    auto = Path('/etc/systemd/system') / (spec['unit'] + '.automount')
    if not auto.is_file() and not mounted(spec):
        raise ValueError('Mount setup is not installed. Open Settings → Network output (NFS) and click Save and set up mount. '
                         'You can also use Set up mount beside the network status in the main window.')
    # Fail quickly for an unreachable NAS before touching its filesystem.
    try:
        with socket.create_connection((spec['server'].strip('[]'), 2049), timeout=2):
            pass
    except OSError as exc:
        raise ValueError(f'Cannot reach NFS server {spec["server"]} on TCP port 2049: {exc}. '
                         'Check that the NAS is online, NFS is enabled, and the LAN/VPN route and firewall allow the connection.') from exc
    root = Path(spec['where'])
    status_command = 'systemctl status ' + shlex.quote(spec['unit'] + '.mount')
    try:
        root.stat()  # Trigger the OS-managed automount, in this disposable worker.
    except OSError as exc:
        raise ValueError(f'Linux could not activate the NFS mount for {spec["source"]}: {exc}. '
                         f'Check the export path and the NAS client-access rules. For system details, run: {status_command}') from exc
    if not mounted(spec):
        raise ValueError(f'Linux did not mount {spec["source"]} at {spec["where"]}. '
                         f'For the mount error, run: {status_command}')
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


def safe_path(root, descriptor):
    filename = descriptor.get('filename', '')
    subfolder = descriptor.get('subfolder', '')
    if not isinstance(filename, str) or not isinstance(subfolder, str) or not filename or Path(filename).name != filename or '\\' in filename + subfolder:
        return None
    relative = Path(subfolder) / filename
    if relative.is_absolute() or '..' in relative.parts or relative.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
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
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Image is not a regular file.')
            contents = stream.read(MAX_IMAGE + 1)
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
        directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('setup', 'probe', 'scan', 'read'))
    parser.add_argument('first')
    parser.add_argument('second', nargs='?', default='')
    args = parser.parse_args()
    try:
        if args.operation in ('setup', 'probe'):
            spec = specification(args.first, args.second)
            (install_mount if args.operation == 'setup' else probe)(spec)
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
