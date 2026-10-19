# ComfyUI Control

A small Qt desktop app for starting, stopping, and updating ComfyUI on Linux.

**Testing 1.0.0rc2.dev6** adds a responsive Mobile WebUI for phones, tablets and
laptops: the same URL automatically switches between compact and two-column
layouts. Wide screens show live progress and statistics in the top header.
Includes reuse from ComfyUI PNG metadata and sharper wide-screen gallery previews.
Enable **Share image prompts and settings between browsers** in desktop
**Mobile WebUI** to reuse laptop generations from your phone. It is off by default.
[Testing guide](https://github.com/jhakuzi/comfyui-control/blob/testing/responsive-webui/docs/RESPONSIVE_WEBUI.md).

Includes foreground SSH startup:
`comfyui-control --start-server --start-webui`. Use your existing configuration;
Ctrl+C stops both components. [SSH guide](https://github.com/jhakuzi/comfyui-control/blob/testing/ssh-startup/docs/SSH.md).
No flags opens the normal desktop window.

It also includes tray controls, an expandable mobile prompt editor and optional
NFS output with local fallback. Mounts are requested at app startup, never enabled
at boot. Desktop and mobile warn when fallback images need uploading manually.
Older testing mount setups need **Set up mount** once to migrate.
See the [NFS guide](https://github.com/jhakuzi/comfyui-control/blob/main/docs/NFS_OUTPUT.md).

See the [feature guide](https://github.com/jhakuzi/comfyui-control/blob/main/docs/FEATURES.md).
Use **Mobile WebUI** to enable the embedded listener, configure your LAN/VPN
address and password, and scan the QR. It is disabled by default.
See the [mobile setup and workflow-mapping guide](https://github.com/jhakuzi/comfyui-control/blob/main/docs/MOBILE.md).

## Install

Extract this ZIP and open a terminal in the `comfyui-control` folder.
Install prerequisites for your distribution:

**Fedora**

```bash
sudo dnf install python3 python3-pip git
```

**Debian / Ubuntu**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git
```

**Arch Linux**

```bash
sudo pacman -S --needed python python-pip git
```

Then install as your normal user, without sudo:

```bash
bash install.sh
```

Open **ComfyUI Control** from the application menu, or run:

```bash
~/.local/bin/comfyui-control
```

The installer downloads Qt's Python bindings into a separate environment.
Your ComfyUI environment and models are kept separate.

## Set up ComfyUI

On first launch, choose your existing ComfyUI folder containing `main.py`,
or install a new copy through Comfy CLI. New setup needs Konsole, GNOME Terminal,
or xterm. GPU drivers and models are configured separately.

Use **Settings** to select Python or a launch script and
inspect launch flags. For CLI updates, use **Choose environment** to select
your ComfyUI environment folder, such as `comfy-env`.

## Update this app

Close the app, download and extract the latest app ZIP, and rerun `bash install.sh`.
Your settings and ComfyUI installation are kept. The app's **Update** button
updates ComfyUI itself.

[Full guide and screenshots](https://github.com/jhakuzi/comfyui-control/blob/main/docs/USAGE.md)

## Uninstall

Remove `~/.local/share/comfyui-control`,
`~/.local/share/applications/comfyui-control.desktop`, and
`~/.local/bin/comfyui-control` (use your XDG data folder if customized).
Settings under `~/.config/comfyui-control` can be kept. ComfyUI and models are
unaffected.
