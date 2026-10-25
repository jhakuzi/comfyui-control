"""Copy only bundled workflow JSONs; never execute ComfyUI or install dependencies."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys
import uuid

WORKFLOWS = (
    ('VeryComfy.json', 'VeryComfy'),
    ('OfficialComfy-SeedVR_Upscaler.json', 'SeedVR Upscaler'),
    ('VeryComfy_Qwen21_Turbo_EDIT_ONLY.json', 'Qwen Edit'),
)
ASSETS = Path(__file__).with_name('assets') / 'workflows'
RELATIVE_TARGET = Path('user/default/workflows')


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def payloads():
    result = {}
    for name, _ in WORKFLOWS:
        raw = (ASSETS / name).read_bytes()
        document = json.loads(raw)
        if len(raw) > 2 * 1024**2 or not isinstance(document.get('nodes'), list) or not isinstance(document.get('links'), list):
            raise ValueError(f'The bundled workflow is invalid: {name}')
        result[name] = raw
    return result


def open_target(root, create=False, expected_root=None):
    root = Path(root).resolve(strict=True)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.stat('main.py', dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Choose a ComfyUI installation containing main.py.')
        root_id = identity(os.fstat(descriptor))[:2]
        if expected_root is not None and root_id != expected_root:
            raise ValueError('The selected installation changed. Refresh before installing.')
        for part in RELATIVE_TARGET.parts:
            if create:
                try: os.mkdir(part, mode=0o755, dir_fd=descriptor)
                except FileExistsError: pass
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    os.close(descriptor)
                    return root, root_id, None
                raise
            os.close(descriptor)
            descriptor = child
        return root, root_id, descriptor
    except BaseException:
        os.close(descriptor)
        raise


def existing(directory, name, raw):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return dict(state='missing', identity=None)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Destination is not a regular file.')
        same = info.st_size == len(raw) and stream.read(len(raw) + 1) == raw
        if identity(os.fstat(stream.fileno())) != identity(info):
            raise ValueError('Destination changed while being checked. Refresh before installing.')
        return dict(state='same' if same else 'present', identity=identity(info))


def inspect(root):
    raw = payloads()
    root, root_id, directory = open_target(root)
    try:
        files = {}
        for name, _ in WORKFLOWS:
            try: files[name] = existing(directory, name, raw[name]) if directory is not None else dict(state='missing', identity=None)
            except (OSError, ValueError) as exc: files[name] = dict(state='error', error=str(exc), identity=None)
        return dict(root=str(root), target=str(root / RELATIVE_TARGET), root_identity=root_id,
                    directory_identity=identity(os.fstat(directory))[:2] if directory is not None else None, files=files)
    finally:
        if directory is not None: os.close(directory)


def install(root, request):
    raw = payloads()
    if not isinstance(request, dict):
        raise ValueError('Invalid workflow installation request.')
    names, replace, review = request.get('names'), request.get('replace', []), request.get('review', {})
    if (not isinstance(names, list) or not names or any(not isinstance(name, str) or name not in raw for name in names)
            or len(set(names)) != len(names) or not isinstance(replace, list)
            or any(not isinstance(name, str) or name not in names for name in replace) or not isinstance(review, dict)):
        raise ValueError('Choose only bundled workflows to install.')
    # Check the reviewed location before creating directories or writing files.
    current = inspect(root)
    if current['root'] != review.get('root') or current['root_identity'] != review.get('root_identity'):
        raise ValueError('The selected installation changed. Refresh before installing.')
    if review.get('directory_identity') is not None and current['directory_identity'] != review['directory_identity']:
        raise ValueError('The workflow directory changed. Refresh before installing.')
    root, root_id, directory = open_target(root, create=True, expected_root=review['root_identity'])
    try:
        if root_id != review['root_identity']:
            raise ValueError('The selected installation changed. Refresh before installing.')
        directory_id = identity(os.fstat(directory))[:2]
        if current['directory_identity'] is not None and directory_id != current['directory_identity']:
            raise ValueError('The workflow directory changed. Refresh before installing.')
        results = []
        for name in names:
            temporary = None
            try:
                state = existing(directory, name, raw[name])
                if state['state'] == 'same':
                    results.append(dict(name=name, status='skipped', message='Already up to date.'))
                    continue
                replacing = state['state'] != 'missing'
                if replacing and name not in replace:
                    results.append(dict(name=name, status='skipped', message='Existing file kept.'))
                    continue
                expected = review.get('files', {}).get(name, {})
                if replacing and (expected.get('state') != 'present' or expected.get('identity') != state['identity']):
                    raise ValueError('File changed since review. Refresh and confirm replacement again.')
                temporary = '.comfyui-control-' + uuid.uuid4().hex + '.tmp'
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw[name]); stream.flush(); os.fsync(stream.fileno())
                _, checked_root, checked = open_target(root)
                try:
                    if checked_root != root_id or checked is None or identity(os.fstat(checked))[:2] != directory_id:
                        raise ValueError('The installation or workflow directory changed. Nothing was copied.')
                finally:
                    if checked is not None: os.close(checked)
                if replacing:
                    if identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) != state['identity']:
                        raise ValueError('File changed before replacement. Refresh and review again.')
                    os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                    temporary = None
                else:
                    try: os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    except FileExistsError:
                        results.append(dict(name=name, status='skipped', message='A file appeared during installation; it was kept.'))
                        continue
                results.append(dict(name=name, status='installed', message='Replaced with confirmation.' if replacing else 'Installed.'))
            except (OSError, ValueError) as exc:
                results.append(dict(name=name, status='error', message=str(exc)))
            finally:
                if temporary is not None:
                    try: os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError: pass
        return dict(results=results)
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['inspect', 'install'])
    parser.add_argument('root')
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        result = inspect(args.root) if args.operation == 'inspect' else install(args.root, request)
        print(json.dumps(result))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps(dict(error=str(exc))))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
