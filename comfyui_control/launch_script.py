"""Generate the user's HIP launch preset without replacing existing scripts."""
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import re
import shlex
import stat
import tempfile
import uuid

from .script_flags import inspect_source

from .flags import HIP_PRESET


def _shell_tokens(source):
    """Token spans for a single simple command; preserve spelling and quoting."""
    result, index = [], 0
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        if source.startswith('\\\r\n', index) or source.startswith('\\\n', index):
            index += 3 if source.startswith('\\\r\n', index) else 2
            continue
        if source[index] == '#':
            break
        start, quote = index, None
        while index < len(source):
            char = source[index]
            if char == '\\' and quote != "'":
                index += 2
                continue
            if quote:
                if char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char.isspace():
                break
            elif char in ';&|()<>`':
                raise ValueError('The Python command uses shell operators or substitutions that cannot be updated automatically.')
            index += 1
        if quote:
            raise ValueError('The Python command has an unfinished quote.')
        raw = source[start:index]
        words = shlex.split(raw.replace('\\\r\n', '').replace('\\\n', ''))
        if len(words) != 1:
            raise ValueError('The Python command cannot be updated safely.')
        result.append((words[0], start, index, raw))
    return result


def _atomic_script(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(temporary)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass
class ScriptUpdate:
    path: Path
    before: bytes
    after: bytes
    changes: tuple[str, ...]
    mode: int
    backup: Path | None = None

    def _unchanged(self, expected):
        if self.path.is_symlink() or not self.path.is_file() or self.path.read_bytes() != expected:
            raise ValueError('The launch script changed while settings were open. Reopen Settings and retry; the newer file was not overwritten.')

    def apply(self):
        self._unchanged(self.before)
        if self.path.stat().st_uid != os.geteuid() or not self.mode & stat.S_IWUSR:
            raise ValueError('The launch script is not writable by your user. Choose a writable copy or use Create launch script; no administrator edit was attempted.')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.backup = self.path.with_name(self.path.name + f'.bak-{stamp}-{uuid.uuid4().hex[:8]}')
        temporary = _atomic_script(self.path, self.after, self.mode)
        backup_created = backup_complete = False
        try:
            # A private, exclusive backup keeps the exact original, including
            # any custom environment setup, flags, comments and line endings.
            fd = os.open(self.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            backup_created = True
            with os.fdopen(fd, 'wb') as stream:
                stream.write(self.before)
                stream.flush()
                os.fsync(stream.fileno())
            backup_complete = True
            self._unchanged(self.before)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
            if backup_created and not backup_complete:
                self.backup.unlink(missing_ok=True)
        return self.backup

    def rollback(self):
        self._unchanged(self.after)
        temporary = _atomic_script(self.path, self.before, self.mode)
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def prepare_script_update(path: Path) -> ScriptUpdate | None:
    """Plan only known output-routing repairs; never execute the user's script."""
    with path.open('rb') as stream:
        before = stream.read(262_145)
    source = before.decode('utf-8')
    inspection = inspect_source(source)
    if not inspection.recognized:
        raise ValueError(inspection.message)
    if inspection.forwards_arguments and re.search(r'"\$(?:@|\{@\})"', source) and not any(
            value == '--output-directory' or value.startswith('--output-directory=') for value in inspection.arguments
            ) and not re.search(r';[ \t]*or[ \t]+exit\b', source):
        return None
    if re.search(r'<<|`|^\s*(?:function\b|[A-Za-z_]\w*\s*\(\s*\)|set\s+--(?:\s|$)|shift\b|for\b|while\b|until\b|getopts\b|case\b)', source, re.MULTILINE):
        raise ValueError('The script contains a function, loop, here-document, substitution or positional-argument handling. It was not changed automatically.')
    updated, changes = [], []
    for line in source.splitlines(keepends=True):
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|()<>')
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            # A continued quoted string is considered with its complete
            # logical command below; it is not a guard eligible for repair.
            tokens = []
        if tokens and tokens[0] in ('cd', 'source', '.') and tokens[-4:] == [';', 'or', 'exit', '1']:
            guard = re.search(r';[ \t]*or(?=[ \t]+exit[ \t]+1[ \t]*(?:#.*)?(?:\r?\n)?$)', line)
            if guard:
                line = line[:guard.start()] + ' ||' + line[guard.end():]
                if 'Fixed Bash error handling (; or exit → || exit)' not in changes:
                    changes.append('Fixed Bash error handling (; or exit → || exit)')
        updated.append(line)
    source = ''.join(updated)
    offset, logical, candidates = 0, '', []
    for line in source.splitlines(keepends=True):
        logical += line
        if line.endswith(('\\\n', '\\\r\n')):
            continue
        if inspect_source(logical).recognized:
            candidates.append((offset, logical))
        offset += len(logical)
        logical = ''
    if logical or len(candidates) != 1:
        raise ValueError('Cannot locate a single complete Python launch command to update. The script was left unchanged.')
    offset, command = candidates[0]
    tokens = _shell_tokens(command)
    main = next(index for index, token in enumerate(tokens) if Path(token[0]).name == 'main.py')
    edits, forwarded = [], False
    index = main + 1
    while index < len(tokens):
        value, start, end, raw = tokens[index]
        if value == '--output-directory':
            if index + 1 >= len(tokens) or tokens[index + 1][0].startswith('--') or tokens[index + 1][0] in ('$@', '${@}'):
                raise ValueError('The script’s --output-directory option has no folder value. Correct that command before saving.')
            edits.append((start, tokens[index + 1][2], ''))
            index += 1
            changes.append('Removed the script’s output-folder override; the app supplies the selected folder at launch')
        elif value.startswith('--output-directory='):
            edits.append((start, end, ''))
            changes.append('Removed the script’s output-folder override; the app supplies the selected folder at launch')
        elif value in ('$@', '${@}'):
            forwarded = True
            if raw not in ('"$@"', '"${@}"'):
                edits.append((start, end, '"$@"'))
                changes.append('Quoted forwarded arguments so folder names with spaces work')
        index += 1
    if not forwarded:
        # Insert before an inline comment without rewriting any existing flags.
        edits.append((tokens[-1][2], tokens[-1][2], ' "$@"'))
        changes.append('Added "$@" so ComfyUI receives the app’s output-folder argument')
    for start, end, replacement in sorted(edits, reverse=True):
        command = command[:start] + replacement + command[end:]
    after = (source[:offset] + command + source[offset + len(candidates[0][1]):]).encode('utf-8')
    if after == before:
        return None
    if path.is_symlink():
        raise ValueError('Automatic editing does not replace symlinked launch scripts. Select the real file or a writable copy.')
    check = inspect_source(after.decode('utf-8'))
    if not check.recognized or not check.forwards_arguments or any(arg == '--output-directory' or arg.startswith('--output-directory=') for arg in check.arguments):
        raise ValueError('Could not verify the prepared output-folder update. The launch script was left unchanged.')
    return ScriptUpdate(path, before, after, tuple(dict.fromkeys(changes)), stat.S_IMODE(path.stat().st_mode))


def create_launch_script(directory: Path, destination: Path, arguments: list[str] | None = None, python: str | None = None) -> None:
    directory = directory.absolute()
    if not (directory / "main.py").is_file():
        raise ValueError("Choose the ComfyUI folder containing main.py first.")
    defaults = shlex.join(HIP_PRESET if arguments is None else arguments)
    executable = Path(python).absolute() if python else directory / "comfy-env" / "bin" / "python"
    activation = executable.parent / "activate"
    content = (
        "#!/usr/bin/env bash\n"
        "set -e\n\n"
        f"COMFYUI_DIR={shlex.quote(str(directory))}\n"
        f"COMFY_PYTHON={shlex.quote(str(executable))}\n"
        f"COMFY_ACTIVATE={shlex.quote(str(activation))}\n"
        'if [[ -f "$COMFY_ACTIVATE" ]]; then source "$COMFY_ACTIVATE"; fi\n'
        'cd -- "$COMFYUI_DIR"\n\n'
        '# The app supplies the current checkbox selections; standalone runs use defaults.\n'
        'if [[ "${1-}" == "--comfyui-control-args" ]]; then\n'
        '  shift\n'
        'else\n'
        f'  set -- {defaults} "$@"\n'
        'fi\n\n'
        "PYTORCH_HIP_ALLOC_CONF=expandable_segments:True \\\n"
        'exec "$COMFY_PYTHON" main.py "$@"\n'
    )
    # Exclusive creation also protects existing scripts and symlink targets.
    with destination.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o700)
        stream.write(content)
