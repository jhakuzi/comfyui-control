# ComfyUI Control

A small Qt desktop app for starting, stopping, and updating ComfyUI on Linux.

This ZIP is the preliminary **Mobile WebUI testing build, 0.9.0.dev6**.
Use **Mobile WebUI…** to enable the embedded listener, configure your LAN/VPN
address and password, and scan the QR. It is disabled by default.
See the [mobile setup and workflow-mapping guide](https://github.com/jhakuzi/comfyui-control/blob/testing/mobile-webui/docs/MOBILE.md).

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

Use **Edit launch configuration…** to select Python or a launch script and
inspect launch flags. For CLI updates, use **Choose environment…** to select
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
