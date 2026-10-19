# Uninstall

For a ZIP installation, open **Settings → Uninstall app** or run:

```bash
bash "${XDG_DATA_HOME:-$HOME/.local/share}/comfyui-control/uninstall.sh"
```

The download also includes `uninstall.sh`. It can remove older `install.sh`
installations which do not yet have their own uninstall button/script. Run as
your normal user, **without sudo**. Close the app first for terminal removal.

Choose one of:

1. **Only uninstall ComfyUI Control** — remove its dedicated app environment,
   icon and owned launch shortcuts; keep ComfyUI.
2. **Remove ComfyUI as well** — also permanently delete the configured ComfyUI
   folder. Type its full path to confirm. This includes models, workflows,
   custom nodes and output images physically stored inside it.

The Settings flow stops the app-owned server and Mobile WebUI before removal.
Wait for any update or mount operation to finish first. Independently launched
ComfyUI processes must be stopped separately.

## What is kept

- App settings, mobile sessions, prompt history and workflow mappings in
  `$XDG_CONFIG_HOME/comfyui-control` (normally `~/.config/comfyui-control`).
- External Python environments, launch scripts and model/output folders outside
  the confirmed ComfyUI folder, including NAS image files.
- Targets of symlinks inside the ComfyUI folder. The symlinks themselves go with
  the folder; the files they point to stay.
- Source/download folders and shared Python dependencies.
- Additional user files inside the app's data folder, outside its dedicated
  `venv`. Only the app environment, icon, uninstall helpers and owned shortcuts
  are removed. Configured ComfyUI/model/output folders inside that environment
  must be moved before uninstalling.
- NFS system definitions and permissions. To remove this app's managed mount
  definition too, use **Remove mount** in the main window before uninstalling.
  Other mounts and `/etc/fstab` are untouched.

Mounted or network-backed ComfyUI folders, mounted subfolders (including bind
mounts), shared/protected roots and symlink installation roots are refused.
Unmount or disconnect those first, or choose app-only removal. No remote/NAS
content is recursively deleted.

For a virtual environment installed with pip, run the installed app's Settings
button or activate that environment and run the download's `bash uninstall.sh`.
It runs pip uninstall for **comfyui-control only**, keeping the environment and
other packages. A source checkout itself is never recursively removed.

To inspect the plan without deleting anything:

```bash
bash uninstall.sh --app-only --dry-run
bash uninstall.sh --with-comfyui --dry-run
```

Without `--dry-run`, terminal removal always asks for confirmation. The second
command uses the ComfyUI location from the saved app settings.

## RPM installation

Use Fedora's package manager:

```bash
sudo dnf remove comfyui-control
```

The Settings button explains this instead of deleting package-managed files.
ComfyUI and user data are not removed by the RPM uninstall.
