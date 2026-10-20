# Responsive WebUI — testing workspace

Open the **same Mobile WebUI URL** on your phone, iPad or laptop. No device
setting, second server or separate installation is needed.

- **Phone / narrow window:** existing compact controls and bottom Generate/progress dock.
- **Desktop / large landscape iPad:** settings and prompts on the left, a large
  selected-image preview in the center, and gallery/history on the right.
  Click a thumbnail to inspect that exact saved image; **Full size** opens the
  existing viewer. Preview controls remain in view as settings scroll.
- **Medium-width windows:** settings on the left; preview and Generate on the right.
  Live progress, s/it, VRAM and GPU
  usage appear in the top header while generating, including in Gallery.
  The header stays visible while scrolling. Completed images appear on the right.
- **Gallery:** the desktop sidebar has All images, Kept, History and Trash views.
  History lists this browser's jobs; selecting one never submits a generation.
  Phones keep the Gallery tab and full-size viewer. Comparison remains available.
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
1000 × 600 CSS pixels, and three columns at 1280 × 600. iPad Split View, browser zoom, small tablets and short
windows can use the compact layout. Controls retain their existing touch sizing.
Resizing or rotating preserves your prompt, workflow, settings and current job.
Saved workflows, custom nodes, GGUF models, LoRAs and session recovery use the
same backend. [Foreground SSH startup](SSH.md) is included in 1.0.

## Run from source

The three-column workspace is on **testing/webui-workspace**, version
**1.1.0.dev1**. It branches from main; the uninstall work remains separate.
For an isolated source copy,
close the running app and install as your usual Linux user:

```bash
git clone --single-branch --branch testing/webui-workspace https://github.com/jhakuzi/comfyui-control.git comfyui-control-workspace-testing
cd comfyui-control-workspace-testing
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

## Saved-image actions

- **Keep:** mark/unmark the selected image for this browser's Kept filter in the
  recent gallery. No file is moved. Marks survive app restarts and are scoped to
  browser identity, output folder and file version.
- **Edit / Upscale:** disabled with an explanation. Workflow execution is not
  implemented in this branch; no Krea, Qwen or SeedVR graph is embedded.
- **Trash:** after confirmation naming the image, move it into the output
  folder's private `.comfyui-control-trash` directory. **Trash → Restore** returns
  it to its original location without overwriting a replacement. There is no
  permanent-delete or automatic-empty operation. This is app-managed storage,
  separate from the desktop's system Trash.

Trash supports local output and the existing NFS worker path. Another browser's
mobile output cannot be trashed, even when metadata sharing is enabled; ordinary
ComfyUI output without mobile ownership can be managed. Keep marks are private to
each browser. Trashed files are excluded from the gallery and public job image
lists, while the original generation journal is retained. Remote-only ComfyUI
files cannot be moved to Trash through the image proxy.

If storage times out, refresh both Gallery and Trash to check the final location
before retrying. A disconnected NAS is not evidence that its files were deleted.

## Check on your devices

1. Try phone portrait/landscape, large iPad portrait/landscape and Split View,
   and a laptop at different window sizes or browser zoom levels.
2. Enter a draft and rotate/resize; confirm the text and workflow stay selected.
3. Generate: confirm model loading, progress, preview, Cancel and Generate remain
   accessible while scrolling, then check the completed image and Save image.
4. Refresh or briefly disconnect during generation; confirm recovery and no
   duplicate request. Try Gallery, comparison selection and closing the viewer.
5. Select an older image, mark it Keep, refresh and check Kept. Trash that image,
   confirm other files remain, then restore it. Try actions while changing selection.

Chromium and Linux WebKit checks exercise layout, generation/recovery, comparison,
metadata reuse, Keep, Trash/restore and browser isolation with a simulated ComfyUI
backend and temporary images. Physical Apple devices, VPN routes, GPU inference
and actual NAS Trash/restore still need manual testing for this branch.
Repeat browser checks with Playwright:

```bash
python tests/manual/mobile_responsive_browser.py --browser chromium
python tests/manual/mobile_responsive_browser.py --browser webkit
```
