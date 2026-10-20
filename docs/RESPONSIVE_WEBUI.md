# Responsive WebUI — testing workspace

Open the **same Mobile WebUI URL** on your phone, iPad or laptop. No device
setting, second server or separate installation is needed.

- **Phone / narrow window:** existing compact controls and bottom Generate/progress dock.
- **Desktop / large landscape iPad:** settings and prompts on the left, a large
  selected-image preview in the center, and gallery/history on the right.
  Click a thumbnail to inspect that exact saved image. Previous/next, **Save image**
  and collapsible **Details** are integrated below the preview. Phones retain the
  separate image viewer. Preview controls remain in view as settings scroll. The
  preview fills the available height; side columns stay a readable width even
  on ultrawide monitors. Redundant Create/Gallery tabs are hidden in this view.
- **Medium-width windows:** settings on the left; preview and Generate on the right.
  Live progress, s/it, VRAM and GPU
  usage appear in the top header while generating, including in Gallery.
  The header stays visible while scrolling. Active progress has its own compact
  panel with a short fade (disabled with reduced motion); it disappears when
  inactive. The empty preview also shows a loading circle and the same live
  statistics while submitting, loading models or sampling. With a live preview,
  they become a small overlay; completion clears them. Reduced motion disables
  the spinner animation. No extra monitoring requests are made.
  Completed images appear on the right.
- **Gallery:** the desktop sidebar has All images, Kept, History and Trash views.
  History lists this browser's jobs; selecting one never submits a generation.
  Phones keep the Gallery tab and full-size viewer. Comparison remains available.
  Previews use 768px thumbnails, or 1280px on high-density screens; phones keep
  the smaller previews. Full-size viewing and comparison keep their original images.
- **Image Details:** prompts, generation parameters, models/LoRAs and additional
  metadata use matching bordered panels. **Copy prompt** is inside the prompt
  panel and also works over ordinary LAN HTTP.
- **Reuse settings / New variation:** also work for images saved directly by
  ComfyUI when the local PNG includes its API workflow metadata. Settings fill
  the form; tap Generate when ready. Missing metadata is explained in the viewer.
- **Reuse across devices:** in desktop **Mobile WebUI**, enable **Share image
  prompts and settings between browsers**, click **Apply**, then refresh your
  phone. Any browser allowed into this WebUI can inspect/reuse image settings.
  Live jobs, cancellation, previews and prompt history stay separate. The option
  is off by default and is also loaded when starting through SSH.

Layout follows available space, not the device name: two columns start at
1000 × 600 CSS pixels. Three columns fit landscape windows from 1024px wide
(at least a 4:3 aspect ratio), or windows at least 1440px wide, with a minimum
height of 600px. Content uses up to 2560px on ultrawide monitors.
iPad Split View, browser zoom, small tablets and short
windows can use the compact layout. Controls retain their existing touch sizing.
Resizing or rotating preserves your prompt, workflow, settings and current job.
Generation settings appear before LoRAs. Choosing a replacement LoRA updates its
checkbox label and enables that slot; uncheck it afterward to leave it disabled.
Other slots and the original workflow retain their settings.
Saved workflows, custom nodes, GGUF models, LoRAs and session recovery use the
same backend. [Foreground SSH startup](SSH.md) is included in 1.0.

## Shared visual styling

All layouts use the same charcoal surfaces, blue controls and green online
indicator. Colors, control/panel radii, spacing, typography and shadows are
defined at the top of `comfyui_control/mobile/web/style.css`. Component rules
reuse those tokens. Restrained highlights separate panels, inputs and raised
buttons; gallery filters use segmented selection styling. Compact header spacing,
44px standard controls and collapsed sections leave more room for the preview.
The three-column structure and responsive breakpoints are unchanged.
Keyboard focus stays visible, controls retain their touch targets, and reduced
motion disables the control transitions and loading animation.

Browser chrome and the PWA manifest use the same background color. The shell
cache version is updated for this theme; reload an existing tab to get the styles.
The existing application icon is retained.

## Run from source

The three-column workspace is on **testing/webui-workspace**, version
**1.1.0.dev5**. It branches from main; the uninstall work remains separate.
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

**VRAM cleanup** below the workflow refresh controls unloads idle models using
ComfyUI's existing API. It is disabled while work is queued or running. The
server checks the queue again before requesting cleanup; the next generation
will reload its models.

## Saved-image actions

- **Keep:** mark/unmark the selected image for this browser's Kept filter in the
  recent gallery. No file is moved. Marks survive app restarts and are scoped to
  browser identity, output folder and file version.
- **Edit:** enter an instruction for the selected saved image. Uses the saved
  `VeryComfy_Qwen21_Turbo_EDIT_ONLY.json` workflow in ComfyUI.
- **Upscale:** asks for an optional multiplier, then sends the selected saved
  image to `OfficialComfy-SeedVR_Upscaler.json` in ComfyUI. Leave the multiplier
  blank to keep its saved value; overrides map to `scale_multiplier`.
  Both actions retain the original image and use normal generation progress,
  cancellation and reconnect recovery. Your main workflow and prompt draft stay
  selected. Missing workflows disable the corresponding action with instructions.
  See [workflow setup and exact bindings](IMAGE_WORKFLOW_INTEGRATION.md).
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
