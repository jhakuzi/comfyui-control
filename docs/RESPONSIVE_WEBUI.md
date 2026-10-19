# Responsive WebUI testing — 1.0.0rc2.dev4

Open the **same Mobile WebUI URL** on your phone, iPad or laptop. No device
setting, second server or separate installation is needed.

- **Phone / narrow window:** existing compact controls and bottom Generate/progress dock.
- **Large iPad / laptop:** prompts and settings on the left; a pinned preview,
  results and Generate column on the right. Live progress, s/it, VRAM and GPU
  usage appear in the top header while generating, including in Gallery.
  The header stays visible while scrolling. Completed images appear on the right.
- Create opens directly at Workflow, with both columns aligned at the top.
- **Gallery:** four columns and larger image/comparison dialogs on wide screens.

Layout follows available space, not the device name: two columns start at
1000 × 600 CSS pixels. iPad Split View, browser zoom, small tablets and short
windows can use the compact layout. Controls retain their existing touch sizing.
Resizing or rotating preserves your prompt, workflow, settings and current job.
Saved workflows, custom nodes, GGUF models, LoRAs and session recovery use the
same backend. This branch also includes [foreground SSH startup](SSH.md).

## Try it

Close the running app, then install this testing copy as your usual Linux user:

```bash
git clone --single-branch --branch testing/responsive-webui https://github.com/jhakuzi/comfyui-control.git comfyui-control-testing-responsive
cd comfyui-control-testing-responsive
python3 -m venv .venv-test
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control
```

Enable Mobile WebUI as usual, and open its existing URL on each device. Reload
an already-open browser page to pick up the new layout. Your installed RPM and
desktop launcher are unchanged; the testing copy reads your saved configuration.
No COPR build has been queued for this branch.

For SSH, use the testing executable with `--start-server --start-webui`.
For updates, close it, run `git pull --ff-only` in this checkout and reinstall
with `.venv-test/bin/python -m pip install .`.

## Check on your devices

1. Try phone portrait/landscape, large iPad portrait/landscape and Split View,
   and a laptop at different window sizes or browser zoom levels.
2. Enter a draft and rotate/resize; confirm the text and workflow stay selected.
3. Generate: confirm model loading, progress, preview, Cancel and Generate remain
   accessible while scrolling, then check the completed image and Save image.
4. Refresh or briefly disconnect during generation; confirm recovery and no
   duplicate request. Try Gallery, comparison selection and closing the viewer.

Chromium and Linux WebKit checks passed with a simulated ComfyUI backend. Actual
iPad/iPhone Safari, your LAN/VPN, GPU generation and real workflows still need
testing on your installation. Browser checks can be repeated with Playwright:

```bash
python tests/manual/mobile_responsive_browser.py --browser chromium
python tests/manual/mobile_responsive_browser.py --browser webkit
```
