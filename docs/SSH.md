# Start from SSH (1.0.0)

After Wake on LAN, SSH into the PC using the same Linux account that configured
ComfyUI Control. No KDE login, desktop display or background service is needed.

```bash
comfyui-control --start-server --start-webui
```

This stays in the foreground and streams ComfyUI output to your terminal.
**Ctrl+C stops ComfyUI and its owned children, stops the Mobile WebUI, and exits.**
SIGTERM and SSH hangup use the same cleanup. A server that ignores termination is
given the existing eight-second grace period before forced shutdown.

Without flags, the application opens its normal desktop window.

| Flags | Behavior |
| --- | --- |
| `--start-server --start-webui` | Start both components without a window. |
| `--start-server` | Start ComfyUI only, using the configured script/Python and flags. |
| `--start-webui` | Start Mobile WebUI only; use the saved API URL for an existing ComfyUI server. That external server is left running on exit. |
| `--help` / `--version` | Print information without opening a window. |

## Headless system dependencies

The Python dependencies (`PySide6-Essentials`, `aiohttp`, `qrcode`) are installed
by pip. PySide6 bundles Qt, but its Linux libraries also depend on system packages
that may be missing on a minimal server. Terminal mode uses `QCoreApplication`
and shared components that import QtWidgets/QtGui; it does not open a window or
load an X11/Wayland platform plugin. Installing the runtime libraries does not
require installing KDE, GNOME, an X server or a display manager.

For **Debian 13 (Trixie)**, install the source-install prerequisites and Qt runtime:

```bash
sudo apt update
sudo apt install --no-install-recommends python3 python3-pip python3-venv git \
  libegl1 libgl1 libopengl0 libglib2.0-0t64 libdbus-1-3 libxkbcommon0 \
  libfontconfig1 libatomic1
```

APT resolves the dependent X11, font and graphics libraries automatically. These
are controller runtime dependencies, separate from ComfyUI's GPU drivers, PyTorch,
models and custom-node requirements. Older Debian/Ubuntu releases may call the
GLib package `libglib2.0-0` instead of `libglib2.0-0t64`; use your release's package.
Optional integrated NFS output also needs `nfs-common` on Debian.

Verified in a clean Debian 13 amd64 container with Python 3.13 and PySide6 6.12:
Qt imports, foreground server/WebUI startup and Ctrl+C cleanup passed using a
stub ComfyUI process. This check does not test GPU inference.

After installing the app, check the actual headless imports without starting a
server or requiring a saved configuration. Run from the source checkout:

```bash
.venv-test/bin/python -c 'import comfyui_control.headless; print("Headless Qt dependencies OK")'
.venv-test/bin/comfyui-control --start-server --start-webui
```

For a ZIP install, the Python path is
`~/.local/share/comfyui-control/venv/bin/python` (under `XDG_DATA_HOME` if customized).
`--help` and `--version` alone do not check Qt imports.

### Common startup errors

| Error | Meaning / fix |
| --- | --- |
| `libEGL.so.1`, `libGL.so.1` or `libOpenGL.so.0: cannot open shared object file` | Install `libegl1`, `libgl1` and `libopengl0`. Pip cannot install these OS libraries. |
| `libglib-2.0.so.0` / `libgthread-2.0.so.0` missing | Install `libglib2.0-0t64` on Debian 13. |
| `libdbus-1.so.3`, `libxkbcommon.so.0`, `libfontconfig.so.1` or `libatomic.so.1` missing | Install `libdbus-1-3`, `libxkbcommon0`, `libfontconfig1` or `libatomic1`, respectively. |
| `ModuleNotFoundError: PySide6` | Use the executable from the environment where the app was installed; reinstall with that environment's `python -m pip install .` if needed. |
| `qt.qpa.xcb: could not connect to display` / platform plugin initialization failure | You started the desktop path. Over SSH, include `--start-server --start-webui` and use the current app executable. Terminal mode needs no `DISPLAY`, X forwarding, Xvfb or `QT_QPA_PLATFORM=offscreen`. |
| Installation must be configured first | System libraries loaded successfully, but this Linux account needs its own valid saved ComfyUI configuration; see Settings and output below. |

If you intentionally want the **desktop window** in an X11 session on Debian 13,
its xcb plugin also needs these libraries:

```bash
sudo apt install --no-install-recommends libxcb-cursor0 libxkbcommon-x11-0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-xinerama0 libxcb-xkb1 libxcb-randr0 libxcb-shape0 libxcb-sync1 \
  libxcb-xfixes0 libx11-xcb1
```

This extra command fixes missing desktop-plugin libraries; it does not provide a
display for an SSH-only server. For desktop plugin diagnostics, run
`QT_DEBUG_PLUGINS=1 comfyui-control` from a graphical session and look for the
specific missing library rather than the generic xcb message.

## Settings and output

- Configure the installation, Python or launch script, workflow and mobile
  network settings in the desktop app first. The CLI reads the same files under
  `~/.config/comfyui-control` (or your `XDG_CONFIG_HOME`). Run without sudo.
- `--start-webui` enables the listener for this run even if its desktop checkbox
  is off. It preserves the saved bind address, port, advertised URL, authentication,
  default workflow, jobs and client sessions. The enable preference is not saved.
- `--start-server` alone leaves Mobile WebUI off, regardless of its saved checkbox.
- An enabled automatic NFS connection is checked before launching ComfyUI. The
  server then uses the ready mount or the existing local fallback, with the same
  warning and gallery destination as the desktop. No interactive mount/package
  setup is attempted over SSH; complete the one-time setup in the desktop first.
- Close the desktop app before running this command. The same instance lock
  prevents two copies from owning the configured server or mobile storage.
- The Mobile WebUI URL is printed after listening starts. Failed configuration,
  a port conflict or exhausted crash recovery is reported in the terminal and
  exits with failure after cleanup. Saved automatic recovery still applies.

This is deliberately a foreground command: the SSH session controls its lifetime.
No boot-start service, user lingering or new persistent configuration is installed.
Closing the command does not unmount an NFS share another program might use.

## Run from source

The 1.0 RPM and ZIP installations include these flags. For an isolated source
installation using your existing saved configuration:

```bash
git clone --single-branch --branch main https://github.com/jhakuzi/comfyui-control.git comfyui-control-source
cd comfyui-control-source
python3 -m venv .venv-test
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control --start-server --start-webui
```

For later updates, close the command, run `git pull --ff-only` in that checkout
and reinstall with `.venv-test/bin/python -m pip install .`.

When starting directly from another machine, request a terminal for Ctrl+C and
use an absolute executable path:

```bash
ssh -t your-user@your-pc '/usr/bin/comfyui-control --start-server --start-webui'
```

A ZIP installation's executable is `~/.local/bin/comfyui-control`; an RPM's is
`/usr/bin/comfyui-control`. For a source install, use the absolute path to its
`.venv-test/bin/comfyui-control`. Your SSH shell may have a different PATH from KDE.
