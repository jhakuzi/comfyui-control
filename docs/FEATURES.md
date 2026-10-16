# Monitoring, comparison and recovery

Available in **ComfyUI Control 0.10.0**. See the [README](../README.md) for
installation and updates. These features add no Python dependencies.

## System & generation

Click the arrow to expand the desktop panel. It remembers that choice. The
collapsed row shows the busiest GPU's utilization/VRAM and current sampling
speed. Expanded details include every detected GPU, temperature/power where
available, CPU/RAM, and owned ComfyUI process-group RSS.

- Linux `/proc` supplies CPU/RAM/RSS. AMD uses readable DRM/hwmon sysfs files,
  falling back to `rocm-smi` when necessary. NVIDIA uses `nvidia-smi` from the
  installed driver. No root access, btop, or extra monitoring package is needed.
- Hardware is sampled roughly once a second in a worker, at most one sample
  at a time. Slow driver commands have timeouts. Hidden, minimized or disabled
  panels stop polling; a collapsed panel samples while ComfyUI runs.
- Missing/unsupported metrics show `--`. Shared pages can appear more than once
  in process-group RSS. The app never claims this is GPU memory or unique PSS.
- Disable the panel in **Edit launch configuration…** if unwanted.

Sampling statistics use actual monotonic progress-event intervals. New sampling
stages reset the interval baseline, so model loading is excluded. The generation
average weights measured iterations across stages; the ETA covers the current
sampling stage only. It appears after at least two intervals. Total generation
elapsed time is separate and includes loading when its start is known.

The existing ComfyUI WebSocket is reused. With Mobile WebUI disabled, monitoring
can make an **outbound-only** ComfyUI connection; it never enables the HTTP
listener or changes authentication, interface, port or VPN settings. ComfyUI often
sends progress only to the submitting client. For other clients the owned server's
iteration output is a fallback. Missing/custom progress formats, parallel samplers,
late attachment, or connection gaps can leave metrics as `--`; timestamps are not
invented. Terminal buffering can reduce precision. A completed terminal duration
can supply total elapsed time, even when its start event was unavailable.

Cancelled/failed jobs do not replace the last completed sampling average. Closing
or opening this panel never starts or restarts ComfyUI.

## Compare images on your phone

In **Gallery → Select two images**, choose A and B, then **Compare**. Drag the
divider, swap images, or center it. The slider also supports keyboard arrows,
Home and End. Different aspect ratios are contained without stretching. Closing
keeps the gallery position and selection.

Differences in available models, LoRAs, sampler, steps, CFG, seed and resolution
are highlighted. Only generation-setting metadata is returned, excluding prompts
and arbitrary node inputs. Existing local PNGs can supply recognized embedded
ComfyUI prompt settings. Some custom inputs and non-PNG images have no metadata.
Another browser's private job metadata stays private. Deleted images show an
error. Full-resolution files load only in comparison and originals stay untouched.

## Crash diagnostics and optional recovery

Unexpected nonzero/signal exits show **Crashed**, the exit code and **View crash
log…**. Normal exit code zero, Stop, Restart, Update and app shutdown do not
schedule crash recovery. Only app-owned processes are supervised.

In **Edit launch configuration… → Crash recovery**, enable automatic restart if
wanted. It is **off by default**. Choose 1–20 attempts (default 3) and an initial
1–60 second delay (default 2). Delays double, capped at 60 seconds; 5 minutes of
stable runtime resets the counter. A failed retry also consumes an attempt.

**Restarting** shows the attempt/countdown and **Cancel recovery**. Once the limit
is reached, Start/Restart remains available. Stop, closing the app, settings or
installation changes, and updates cancel pending recovery. Retries check that the
selected installation and launch command still match; there is no parallel spawn.

Diagnostics keep a 32 KiB recent-output tail and the latest five crashes in
`~/.config/comfyui-control/crashes.json` (or your XDG config directory), with private
file permissions. The viewer can copy or export the selected crash. Timestamps,
exit codes, launch command and folder are included. Common token/password/URL
credential patterns are redacted before saving/exporting. Review before sharing:
unrecognized secrets, local paths and prompts can still be present. Delete that
file to discard stored history while the app is closed.

## Verification and remaining checks

Automated tests exercise unavailable hardware/readable fixture metrics, unit
conversion, process ownership, timing/stages/cancellation, monitoring lifecycle,
real short-lived QProcess crashes, retry limits/backoff, intentional exits,
configuration/update/shutdown cancellation, diagnostics, and existing desktop/mobile
behaviour. Browser checks use Chromium touch emulation and a ComfyUI protocol
test double with local PNG fixtures, not GPU generation.

Manual checks still needed on your system:

- NVIDIA/AMD driver metrics and units during a real GPU workload.
- Your custom workflows' sampling events/terminal output, especially multiple stages.
- iPhone Safari touch comparison, memory use with large images, and LAN/VPN access.
- KDE Wayland appearance and a real crash/recovery with your launch script.

Developer commands (Playwright/Chromium are optional development tools):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/mobile_browser.py
.venv/bin/python tests/manual/mobile_workflows_browser.py
.venv/bin/python tests/manual/mobile_workflows_browser.py --gguf
.venv/bin/python tests/manual/mobile_comparison_browser.py
.venv/bin/python tests/manual/mobile_preparation_browser.py
```
