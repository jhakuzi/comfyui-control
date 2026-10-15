#!/usr/bin/env bash
set -euo pipefail

# Per-user install: keep GUI dependencies separate from ComfyUI's environment.
app_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app_target="${XDG_DATA_HOME:-$HOME/.local/share}/comfyui-control"
app_desktops="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
app_bin="$HOME/.local/bin"
if [[ "$EUID" -eq 0 ]]; then
    echo 'Run this installer as your normal desktop user, without sudo.' >&2
    exit 1
fi
command -v python3 >/dev/null || { echo 'Install Python first: sudo dnf install python3 python3-pip' >&2; exit 1; }
mkdir -p "$app_target" "$app_desktops" "$app_bin"
python3 -m venv "$app_target/venv"
"$app_target/venv/bin/python" -m pip install "$app_source"

# Generate quoted paths for both a shell wrapper and the desktop file.
"$app_target/venv/bin/python" - "$app_target" "$app_bin" "$app_desktops" <<'PY'
from pathlib import Path
import comfyui_control
import shlex
import shutil
import sys

target, bin_dir, desktop_dir = map(Path, sys.argv[1:])
executable = str(target / 'venv' / 'bin' / 'comfyui-control')
icon = target / 'comfyui-control.png'
shutil.copyfile(Path(comfyui_control.__file__).with_name('assets') / 'comfyui-control.png', icon)
icon_value = str(icon).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')
wrapper = bin_dir / 'comfyui-control'
wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(executable) + ' "$@"\n', encoding='utf-8')
wrapper.chmod(0o755)
# Desktop Entry Exec has its own quoting rules, not shell quoting rules.
quoted = executable.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
quoted = quoted.replace('\\', '\\\\')  # Escape at the desktop string layer too.
(desktop_dir / 'comfyui-control.desktop').write_text(
    '[Desktop Entry]\nType=Application\nName=ComfyUI Control\n'
    'Comment=Start, stop, and update a local ComfyUI server\n'
    f'Exec="{quoted}"\nIcon={icon_value}\nTerminal=false\n'
    'Categories=Graphics;\nStartupNotify=true\n', encoding='utf-8'
)
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$app_desktops" || true
fi
echo 'Installed. Open ComfyUI Control from the KDE application menu.'
echo "Or run: $app_bin/comfyui-control"
