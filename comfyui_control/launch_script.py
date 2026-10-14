"""Generate the user's HIP launch preset without replacing existing scripts."""
import os
from pathlib import Path
import shlex

from .flags import HIP_PRESET


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
