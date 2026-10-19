# Start from SSH (testing 1.0.0rc2.dev1)

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

## Try the testing build

RC1's installed RPM does not contain these flags yet. Leave it installed and use
this isolated testing environment, with your existing saved configuration:

```bash
git clone --single-branch --branch testing/ssh-startup https://github.com/jhakuzi/comfyui-control.git comfyui-control-testing-ssh
cd comfyui-control-testing-ssh
python3 -m venv .venv-test
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control --start-server --start-webui
```

For later updates, close the command, run `git pull --ff-only` in that checkout
and reinstall with `.venv-test/bin/python -m pip install .`.

When starting directly from another machine, request a terminal for Ctrl+C and
use an absolute executable path:

```bash
ssh -t your-user@your-pc '/full/path/to/comfyui-control-testing-ssh/.venv-test/bin/comfyui-control --start-server --start-webui'
```

A ZIP installation's executable is `~/.local/bin/comfyui-control`; an RPM's is
`/usr/bin/comfyui-control`. Select the testing executable explicitly until the
feature is released. Your SSH shell may have a different PATH from KDE.
