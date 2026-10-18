# Network output (testing 0.11.2.dev3)

[Back to features](FEATURES.md)

Save ComfyUI images to an NFS export, with the selected installation's
`ComfyUI/output` folder as the local fallback.

## Set up

1. Install the NFS client: **Fedora:** `sudo dnf install nfs-utils`;
   **Debian/Ubuntu:** `sudo apt install nfs-common`;
   **Arch:** `sudo pacman -S nfs-utils`.
2. Stop ComfyUI, open **Settings**, and enable **Network output (NFS)**. Enter
   the NAS IP/hostname and its exported path, for example `192.168.1.50` and
   `/export/comfy-output`. This is an NFS export, not an SMB share name.
3. Leave **Connect when ComfyUI Control starts** checked for automatic connection.
   The generated local mount location is shown below.
4. Save Settings. In the main window, click **Set up mount**, review the proposed
   setup (exact units are under Show Details), and authorize it as administrator.
5. Setup checks the connection. When ready, start ComfyUI. Use **Retry network**
   after changing NAS availability or permissions.

Setup creates a root-owned mountpoint under `/mnt` and two systemd units under
`/etc/systemd/system`. It enables an on-demand automount. Subsequent app launches
run unprivileged checks without an administrator prompt. The desktop app remains
unprivileged. The setup button needs systemd and a polkit authentication agent.

The export must allow writes by your Linux UID/GID. The check creates, flushes
and removes a small temporary file as your user; it does not change NAS permissions.
Export paths currently support letters, numbers, slash, dot, underscore and
hyphen. Use a hostname or IPv4/global IPv6 address; scoped IPv6 and export names
containing spaces are unsupported.

## Fallback and switching

- Startup checks run in the background with a 12-second app deadline. The desktop
  opens immediately. Starting ComfyUI before the check finishes selects local
  output for that run.
- Missing setup, an unreachable NAS, a timeout or denied write access produces a
  visible error and selects **`ComfyUI/output`**. Saved custom output settings and
  launch flags are retained.
- A successful retry during an active run does not change its destination.
  Manually restart ComfyUI to use the share. Existing images are not moved.
- **Open output folder** and the mobile gallery follow the selected folder.
  Bounded disposable workers isolate NFS scans/reads from the Qt and HTTP loops.

The app supplies ComfyUI's `--output-directory` option at launch, replacing a
conflicting output option for this run only. Generated launch scripts support
this automatically. Existing scripts need a simple `main.py` command forwarding
`"$@"`, without a hardcoded output-directory option; incompatible scripts show
an error. A custom save node with its own absolute destination can still override
ComfyUI's default. This setting applies to servers launched by this application.

Fallback is selected before starting a server. A NAS disappearing during a save
can make that save fail or wait for recovery. Linux's default NFS hard-mount
semantics are retained; a process blocked in kernel NFS I/O can remain until the
NAS recovers. The app cannot transparently redirect that in-progress write.

## Gallery

Workflow mappings, LoRAs, GGUF controls, prompt history and metadata permissions
are unchanged. Local and NFS output keep separate job/output scopes. Network-image
reads have a 100 MiB limit; symlinked paths and traversal are rejected. Offline
scans retain the current gallery rather than treating it as an empty folder.
Worker output uses private, unnamed local temporary files closed after reading;
no second image archive is maintained.

## Terminal setup and removal

If `pkexec` is unavailable, find the helper with the app's Python:

```bash
.venv-test/bin/python -c 'import comfyui_control.network_output as n; print(n.__file__)'
```

Use the printed path, your actual server and export:

```bash
sudo /usr/bin/python3 -I -S /printed/path/network_output.py setup 192.168.1.50 /export/comfy-output
```

Disabling NFS restores normal output settings on the next ComfyUI start; the OS
mount setup remains available. To remove it, first stop ComfyUI and other users
of the share. Replace `UNIT` below with the exact unit base name from
**Set up mount → Show Details**:

```bash
sudo systemctl disable --now 'UNIT.automount'
sudo systemctl stop 'UNIT.mount'
sudo rm -- '/etc/systemd/system/UNIT.automount' '/etc/systemd/system/UNIT.mount'
sudo systemctl daemon-reload
```

Remove the empty mountpoint with `rmdir` afterward if desired. Do not remove files
inside a mounted export during cleanup.

## Verification

Tests use disposable directories/processes and validate generated systemd units
where the validator is available. They cover fallback, output writes, timeouts,
script forwarding, worker limits, image reads, privacy and deletion. Real NAS
mounting, polkit authorization and NAS UID/GID permissions need testing on your PC.
