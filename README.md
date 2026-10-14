# ComfyUI Control

A small native Qt 6 window for Fedora Linux and KDE Plasma, matching the supplied sketch. Live server output sits above Start/Stop, Restart, Update, Open output folder, Open models folder, and Edit launch configuration buttons. A visible **Change folder…** button lets you switch installations later.

![Window preview](preview.png)

The preview uses sample server output. Qt's appearance follows the available desktop theme and platform integration.

## Install on Fedora

This application controls an **existing, working ComfyUI installation**. It does not install ComfyUI, GPU drivers, or models.

Extract the archive, open a terminal in the `comfyui-control` folder, then run:

```bash
sudo dnf install python3 python3-pip git
bash install.sh
```

The installer downloads Qt's Python bindings and installs the application for your user, without sudo. Open **ComfyUI Control** from the KDE application menu, or run `~/.local/bin/comfyui-control`. GUI dependencies live in their own virtual environment; ComfyUI keeps its existing environment.

For development or running directly from the source:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m comfyui_control
```

## First launch and configuration

On first launch, a folder picker suggests `/mnt/Ironforge/ComfyUI`. Select the folder containing `main.py`, then choose a launch method in the configuration dialog:

- **Python:** starts `main.py` using the specified Python executable. Leave Python blank to detect `.venv/bin/python`, then `venv/bin/python`, then `python3`. For Conda or an environment elsewhere, browse to its actual `bin/python` executable. Put flags such as `--listen 127.0.0.1 --port 8188` in Launch arguments.
- **Existing Bash launch script:** select your `.sh` file. It runs with `/bin/bash` and the ComfyUI folder as its working directory. **Edit launch script…** opens it in KWrite or Kate so you can change flags already hardcoded there. Additional Launch arguments are appended to the script; your script must forward them with `"$@"` to use them. This output viewer supports scripts that run without interactive prompts.

For a script you can adapt, the last lines should look like:

```bash
cd /mnt/Ironforge/ComfyUI || exit 1
exec .venv/bin/python -u main.py --listen 127.0.0.1 --port 8188 "$@"
```

Keep your existing environment activation and flags if you already have them. `exec` helps the controller track the server; avoid backgrounding or daemonizing it. Stopping also signals child processes in the controller's process group.

### Select launch flags

**Edit launch configuration…** includes searchable checkboxes for the boolean flags supported by your installed ComfyUI version. It reads `comfy/cli_args.py` as text without running or importing ComfyUI. Each flag's tooltip shows its help text. If that file is unavailable or cannot be read, a labeled list of common flags is used instead.

Choose options such as `--disable-smart-memory`, `--use-pytorch-cross-attention`, `--lowvram`, and `--cpu-vae` with checkboxes. Mutually exclusive options automatically uncheck one another. **Reserve VRAM** enables a numeric GB field. **Other arguments** accepts options requiring other values, such as `--port 8188`, plus flags not listed as checkboxes. Selections are saved between sessions.

![Launch flag checkboxes](flags-preview.png)

### Create a launch script

The small **Create launch script…** button beside the installation path first opens the checkbox selector, then saves an executable `.sh` file and selects it as the launch method. Existing configured flags are preselected; when none are configured, your HIP preset is suggested. The generated script activates `comfy-env` inside your selected ComfyUI folder, changes into that folder, sets `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`, then launches with the selected flags. The initial preset is equivalent to:

```bash
exec ./comfy-env/bin/python main.py \
  --use-pytorch-cross-attention \
  --disable-smart-memory \
  --reserve-vram 1 \
  "$@"
```

The `comfy-env` environment must already exist; the button creates the script, not the environment. Folder paths containing spaces or shell characters are quoted safely. `exec` keeps Start/Stop and Restart in control of the Python server. Additional arguments can be added in the configuration dialog.

By default the script is saved next to the application's settings, outside the ComfyUI checkout, so it does not introduce an untracked file that blocks Update. You can choose another location and filename. Existing scripts are not overwritten. Creating a script preserves your chosen additional arguments and selects `comfy-env/bin/python` for optional dependency updates.

Scripts created by this version store your chosen defaults for standalone use. When started from the app, they receive the current checkbox selections instead, so unchecking a flag removes it even when it appeared in the original defaults. This also works when every flag is unchecked. The app uses a private argument marker that the generated script removes before launching ComfyUI. To change the environment activation or HIP setting, use **Edit launch configuration… → Edit launch script…**.

Existing custom scripts and scripts generated by versions before 0.3 continue to receive appended arguments; flags hardcoded inside them must be edited in the script or replaced by creating a new script with this version.

The settings are stored in `~/.config/comfyui-control/config.json` (or `$XDG_CONFIG_HOME/comfyui-control/config.json`). Settings can be edited while stopped. Changing installation folders resets the interpreter, script, arguments, and custom folder paths, so configure the new installation before starting it.

Output and models buttons use the installation's `output` and `models` subfolders. If your flags or scripts relocate these folders, set the corresponding custom paths in the configuration dialog too. These custom paths control the folder buttons; they do not change ComfyUI's flags.

## Server output and lifecycle

The output pane is a read-only log, not an interactive shell. It merges stdout and stderr, handles streamed UTF-8 and common ANSI escapes, and retains the last 5,000 lines. Scroll up to pause following new output. “Process running” indicates the process is alive; check ComfyUI's output for the URL and whether startup has completed.

Stop sends SIGTERM to the process group, then SIGKILL after eight seconds if necessary. Restart waits for shutdown before launching again. Closing an active window asks to stop its process before exiting. Only one controller window per user is allowed. The app manages processes it launched; stop any separately running ComfyUI before using it.

## Updates

Update requires the selected folder to be the root of a Git checkout. It checks for tracked modifications and untracked files, then runs `git pull --ff-only` against the branch's configured upstream. It never resets, cleans, or stashes your changes. Git divergence, local changes, authentication failures, or command errors stop the update and remain visible in the output. If Git reports untracked models/output files, check the installation's `.gitignore` or move them before updating.

If ComfyUI is running, Update stops it and restarts it only after a successful update. On failure it stays stopped. Optional **Install requirements.txt after updating** runs `python -m pip install -r requirements.txt` with the selected ComfyUI interpreter. It is off by default because it can change GPU and other dependencies. In script mode, explicitly select the Python executable used by your script before enabling this option. Updates cover the core checkout and optionally its requirements; custom nodes have their own update procedures. There is no automatic rollback if Git succeeds but dependency installation fails.

## Troubleshooting

- **ComfyUI exits immediately:** check the log and the interpreter/launch script; confirm your normal launch command works in a terminal.
- **Qt reports an xcb plugin error:** on Fedora install `libxcb`, `xcb-util-cursor`, and `libxkbcommon-x11`. KDE Wayland can also be selected with `QT_QPA_PLATFORM=wayland ~/.local/bin/comfyui-control`.
- **No script editor:** install `kwrite` or `kate`, or edit the script in your preferred editor.
- **Folder unavailable:** verify `/mnt/Ironforge` is mounted and choose the correct folder.

## Tests

```bash
.venv/bin/python -m pip install pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

Tests use temporary fake servers and local Git repositories. They do not touch your ComfyUI installation or require a GPU.

## Uninstall

Remove `~/.local/share/comfyui-control`, `~/.local/share/applications/comfyui-control.desktop`, and `~/.local/bin/comfyui-control` (use your configured XDG data folder if different). Settings under `~/.config/comfyui-control` can be kept for reinstalling or removed separately. Your ComfyUI installation is unchanged.
