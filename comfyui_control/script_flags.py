"""Inspect simple Python launch commands as text; never execute shell code."""
from dataclasses import dataclass
from pathlib import Path
import re
import shlex


@dataclass(frozen=True)
class ScriptFlags:
    arguments: tuple[str, ...] = ()
    message: str = ""
    forwards_arguments: bool = False


def inspect_script(path: Path) -> ScriptFlags:
    try:
        with path.open(encoding="utf-8") as stream:
            source = stream.read(262_145)
    except (OSError, UnicodeError) as exc:
        return ScriptFlags(message=f"Could not read script: {exc}")
    if len(source) > 262_144:
        return ScriptFlags(message="Script is too large to inspect. Use Edit script file to review its flags.")
    source = source.replace("\\\r\n", "").replace("\\\n", "")
    launches, defaults = [], []
    generated = "# The app supplies the current checkbox selections; standalone runs use defaults." in source and "--comfyui-control-args" in source
    try:
        for line in source.splitlines():
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
            lexer.whitespace_split = True
            commands, command = [], []
            for token in lexer:
                if token and all(char in ";&|()<>" for char in token):
                    commands.append(command)
                    command = []
                else:
                    command.append(token)
            commands.append(command)
            for command in commands:
                if generated and command[:2] == ["set", "--"]:
                    defaults = command[2:]
                index = 0
                while index < len(command) and (command[index] in ("exec", "env") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", command[index])):
                    index += 1
                if index >= len(command):
                    continue
                executable = command[index]
                if not (re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(executable).name) or executable in ("$COMFY_PYTHON", "${COMFY_PYTHON}", "$PYTHON", "${PYTHON}")):
                    continue
                for position in range(index + 1, len(command)):
                    if command[position] in ("-c", "-m"):
                        break
                    if Path(command[position]).name == "main.py":
                        launches.append(command[position + 1:])
                        break
    except ValueError:
        return ScriptFlags(message="Script uses shell syntax that cannot be inspected reliably. Use Edit script file to review its flags.")
    if len(launches) != 1:
        return ScriptFlags(message="Could not identify a single Python main.py command. Script flags were not inferred.")
    arguments = [token for token in [*defaults, *launches[0]] if token not in ("$@", "${@}")]
    dynamic = any("$" in token or "`" in token for token in arguments)
    return ScriptFlags(tuple(arguments), "Variable-based arguments are shown literally; the script was not executed." if dynamic else "",
                       any(token in ('$@', '${@}') for token in launches[0]))
