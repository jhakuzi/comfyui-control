# Responsive WebUI — 1.0.0

Open the **same Mobile WebUI URL** on your phone, iPad or laptop. No device
setting, second server or separate installation is needed.

- **Phone / narrow window:** existing compact controls and bottom Generate/progress dock.
- **Large iPad / laptop:** prompts and settings on the left; a pinned preview,
  results and Generate column on the right. Live progress, s/it, VRAM and GPU
  usage appear in the top header while generating, including in Gallery.
  The header stays visible while scrolling. Completed images appear on the right.
- Create opens directly at Workflow, with both columns aligned at the top.
- **Gallery:** four columns and larger image/comparison dialogs on wide screens.
  Previews use 768px thumbnails, or 1280px on high-density screens; phones keep
  the smaller previews. Full-size viewing and comparison keep their original images.
- **Reuse settings / New variation:** also work for images saved directly by
  ComfyUI when the local PNG includes its API workflow metadata. Settings fill
  the form; tap Generate when ready. Missing metadata is explained in the viewer.
- **Reuse across devices:** in desktop **Mobile WebUI**, enable **Share image
  prompts and settings between browsers**, click **Apply**, then refresh your
  phone. Any browser allowed into this WebUI can inspect/reuse image settings.
  Live jobs, cancellation, previews and prompt history stay separate. The option
  is off by default and is also loaded when starting through SSH.

Layout follows available space, not the device name: two columns start at
1000 × 600 CSS pixels. iPad Split View, browser zoom, small tablets and short
windows can use the compact layout. Controls retain their existing touch sizing.
Resizing or rotating preserves your prompt, workflow, settings and current job.
Saved workflows, custom nodes, GGUF models, LoRAs and session recovery use the
same backend. [Foreground SSH startup](SSH.md) is included in 1.0.

## Run from source

The 1.0 RPM and app ZIP include this interface. For an isolated source copy,
close the running app and install as your usual Linux user:

```bash
git clone --single-branch --branch main https://github.com/jhakuzi/comfyui-control.git comfyui-control-responsive
cd comfyui-control-responsive
python3 -m venv .venv-test
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control
```

Enable Mobile WebUI as usual, and open its existing URL on each device. Reload
an already-open browser page to pick up the new layout. Your installed RPM and
desktop launcher are unchanged; the source copy reads your saved configuration.

For SSH, use the source environment's executable with `--start-server --start-webui`.
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

Chromium and Linux WebKit checks passed with a simulated ComfyUI backend. The user
also confirmed phone/laptop/iPad use, generation settings, SSH, NFS/fallback,
iPhone reconnection and cross-device reuse on their own installation. Other
devices/workflows may need their own checks. Repeat browser checks with Playwright:

```bash
python tests/manual/mobile_responsive_browser.py --browser chromium
python tests/manual/mobile_responsive_browser.py --browser webkit
```
