# Network output (testing 0.11.2.dev10)

[Back to features](FEATURES.md)

Save ComfyUI images to an NFS export, with the selected installation's
`ComfyUI/output` folder as the local fallback.

## Set up

1. Stop ComfyUI, open **Settings**, and enable **Network output (NFS)**. Enter
   the NAS IP/hostname and its exported path, for example `192.168.1.50` and
   `/export/comfy-output`. This is an NFS export, not an SMB share name.
2. Leave **Connect when ComfyUI Control starts** checked for automatic connection.
   The generated local mount location is shown below.
3. In the NFS section, click **Save and set up mount**. This saves Settings,
   closes the window and opens mount setup directly. You can also use
   **Set up mount** beside the network status in the main window. If NFS tools are
   missing, accept **Install nfs-utils** (Fedora/Arch) or **Install nfs-common**
   (Debian/Ubuntu). Installation opens in your terminal; authorize it and review
   the package manager's prompts. When finished, click **Set up mount** again in
   the main window.
4. Review the proposed
   setup (exact units are under Show Details), and authorize it as administrator.
5. Setup checks the connection. When ready, start ComfyUI. Use **Retry network**
   after changing NAS availability or permissions.

Setup creates a root-owned mountpoint under `/mnt` and one static `.mount`
unit under `/etc/systemd/system`. Nothing is enabled at boot, `/etc/fstab` is
untouched, and accessing the folder does not automatically mount it. The app
requests mounting in a background worker when it launches (if Connect at startup
is checked) or when you choose Retry network.

One-time administrator setup installs a narrowly scoped rule under
`/etc/polkit-1/rules.d`: only your account may **start this exact mount unit**
without another prompt. It does not grant permission to stop/restart units,
change unit files or manage other mounts. Setup/removal still requires
administrator authorization. The desktop app stays unprivileged.

**Upgrading from dev9 or earlier:** stop ComfyUI and close programs using the
share, then click **Set up mount** once. Migration validates and disables the
old app-managed boot automount, removes its definition and installs the new
setup. Busy/foreign/nested mounts and stop dependencies retain the existing
safeguards. Startup detects the old setup and asks for migration rather than
silently continuing to use it.

Connection errors identify the NFS server/port, mount activation or write access.
A start authorization error asks you to rerun setup for your current account.
The mount's actual source/type is verified before writing any probe file.
Failed system commands include their error output rather than only an exit code.
Closing the app leaves a successfully mounted share available; use Remove mount
for explicit cleanup rather than interrupting another program using it.

The package check detects `mount.nfs`, including in system sbin folders outside
your user PATH. Declining installation leaves local fallback available.
Installation uses the existing Konsole/GNOME Terminal/xterm support, needs sudo,
and runs independently of the app. No packages are installed automatically at
startup. Unsupported or image-based distributions show manual setup guidance.
Manual alternatives: Fedora `sudo dnf install nfs-utils`, Debian/Ubuntu
`sudo apt install nfs-common`, Arch `sudo pacman -S --needed nfs-utils`.

The export must allow writes by your Linux UID/GID. The check creates, flushes
and removes a small temporary file as your user; it does not change NAS permissions.
Export paths currently support letters, numbers, slash, dot, underscore and
hyphen. Use a hostname or IPv4/global IPv6 address; scoped IPv6 and export names
containing spaces are unsupported.

## Fallback and switching

- Startup checks run in the background with a 18-second app deadline. The desktop
  opens immediately. Starting ComfyUI before the check finishes selects local
  output for that run.
- Missing setup, an unreachable NAS, a timeout or denied write access produces a
  visible error and selects **`ComfyUI/output`**. Saved custom output settings and
  launch flags are retained.
- Desktop and mobile show a persistent warning naming the local fallback folder
  and reminding you to **upload those images manually**. A failed mount also
  shows its error. The mobile warning survives refreshes/reconnections and is
  visible on both Create and Gallery; it clears when network output is selected
  or the feature is disabled. Images are never automatically uploaded or moved.
- A successful retry during an active run does not change its destination.
  Manually restart ComfyUI to use the share. Existing images are not moved.
- **Open output folder** and the mobile gallery follow the selected folder.
  While local fallback is selected, the gallery reads **`ComfyUI/output`**.
  Bounded disposable workers isolate NFS scans/reads from the Qt and HTTP loops.

The app supplies ComfyUI's `--output-directory` option at launch, replacing a
conflicting app-supplied output option for this run only. Generated launch scripts
support this automatically. When saving settings, the app updates a recognizable
existing `main.py` script as needed: it adds quoted `"$@"` forwarding, removes a
script-level output-directory override, and corrects simple Bash `; or exit 1`
guards to `|| exit 1`. Your Python/environment setup, other flags and comments
are preserved. The exact original is saved beside it as `script.sh.bak-TIME-ID`;
the desktop log lists the changes and backup path. Repeated saves do not rewrite
an already compatible script. Changes apply on the next start/restart.

Complex, ambiguous, symlinked or unwritable scripts are not rewritten. The dialog
explains the specific blocker and offers to save settings for mount setup or
open the script editor. This script check happens before a NAS connection test;
you can configure the mount independently, while starting ComfyUI stays blocked
until its output argument can be applied. You can also use **Python — launch
main.py** with your environment or **Create launch script**.

A custom save node with its own absolute destination can still override
ComfyUI's default. This setting applies to servers launched by this application.

If the export is already mounted by your system, leave **Network output (NFS)**
disabled and select that local mount path in **Output folder** instead. This now
sets ComfyUI's actual save destination as well as the app/gallery folder. The
integrated mount checks and automatic local fallback apply only to mounts managed
through the Network output feature; system-managed mounts follow your OS setup.

Fallback is selected before starting a server. A NAS disappearing during a save
can make that save fail or wait for recovery. Linux's default NFS hard-mount
semantics are retained; a process blocked in kernel NFS I/O can remain until the
NAS recovers. The app cannot transparently redirect that in-progress write.
If a subsequent connection check fails while a server still targets NFS, the
warning asks you to restart ComfyUI for local fallback rather than claiming the
active server has already changed its output folder.

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

## Remove the managed mount

Disabling NFS restores normal output settings on the next ComfyUI start; it does
not remove the OS mount setup. To remove that setup:

1. Stop ComfyUI and close file managers/other programs using the share.
2. Click **Remove mount** beside the network status in the main window. If NFS
   was disabled, enable the existing server/export in Settings to show that row.
3. Review the exact units and authorize removal as administrator.

Removal stops this mount and removes its definition and scoped start permission
after confirming unmount. It also cleans up an existing legacy automount.
NAS files, other mount definitions and
`/etc/fstab` are untouched. The empty local mountpoint is kept. Busy mounts fail
without forced/lazy unmount, and keep their definitions for retry. Edited/foreign
unit files, overrides, foreign filesystems and nested mounts are refused.
Removal also refuses other systemd units that would be stopped through a mount
dependency, including mounts/services elsewhere on the system.
Setup applies the same ownership/collision checks before changing anything.
The app does not adopt or remove a mount configured outside its generated units.

Local fallback and its mobile gallery remain available after removal. No new
mount is created unless you explicitly choose **Set up mount** again. Settings
retain the server/export for that purpose. For a terminal alternative using the
worker path found above:

```bash
sudo /usr/bin/python3 -I -S /printed/path/network_output.py remove 192.168.1.50 /export/comfy-output
```

If you have customized the generated units, inspect them manually rather than
deleting unrelated system definitions to bypass the safeguard.

## Verification

Tests use disposable directories/processes and validate generated systemd units
where the validator is available. They cover fallback, output writes, timeouts,
script forwarding, worker limits, image reads, privacy and deletion. Mount
activation tests require an explicit non-interactive systemd start before
writing, and stacked mount tests vary mountinfo order. Tests also cover legacy
migration and the permission rule’s exact user/unit/start restrictions. Removal
tests cover foreign/edited/symlinked units,
unit overrides, nested mounts, busy failures, preservation of unrelated files,
authorization/cancellation and desktop/mobile fallback after completion. Automatic
script edits cover the reported multiline Bash script, exact backups, idempotent
saves, existing output overrides, refusal of complex/changed/unwritable scripts,
rollback on settings-save failure and actual child-process output writes. Embedded
HTTP/SSE checks cover mount error delivery, fallback gallery reads, live warning
updates and listener restarts. Browser checks cover persistent warnings on
Create/Gallery without interrupting generation progress or prompt recovery. Real NAS
mounting, polkit authorization and NAS UID/GID permissions need testing on your PC.
