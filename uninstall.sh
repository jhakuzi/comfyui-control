#!/usr/bin/env bash
set -euo pipefail
uninstall_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
uninstall_helper="$uninstall_source/comfyui_control/uninstall.py"
if [[ ! -f "$uninstall_helper" ]]; then
    uninstall_helper="$uninstall_source/uninstall.py"
fi
command -v python3 >/dev/null || { echo 'Python 3 is required to run the uninstaller.' >&2; exit 1; }
exec python3 -I "$uninstall_helper" "$@"
