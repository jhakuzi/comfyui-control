"""Generate the user's HIP launch preset without replacing existing scripts."""
import os
from pathlib import Path
import shlex


def create_launch_script(directory: Path, destination: Path) -> None:
    directory = directory.absolute()
    if not (directory / "main.py").is_file():
        raise ValueError("Choose the ComfyUI folder containing main.py first.")
    content = (
        "#!/usr/bin/env bash\n"
        "set -e\n\n"
        f"COMFYUI_DIR={shlex.quote(str(directory))}\n"
        'source "$COMFYUI_DIR/comfy-env/bin/activate"\n'
        'cd -- "$COMFYUI_DIR"\n\n'
        "PYTORCH_HIP_ALLOC_CONF=expandable_segments:True \\\n"
        "exec ./comfy-env/bin/python main.py \\\n"
        "  --use-pytorch-cross-attention \\\n"
        "  --disable-smart-memory \\\n"
        "  --reserve-vram 1 \\\n"
        '  "$@"\n'
    )
    # Exclusive creation also protects existing scripts and symlink targets.
    with destination.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o700)
        stream.write(content)
