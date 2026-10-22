> Presentation files are now separated without changing this layout. See
> [WEBUI_PRESENTATION.md](WEBUI_PRESENTATION.md) for mobile/desktop file ownership,
> shared component dependencies and regression checks.

# Responsive WebUI — testing workspace

Open the **same Mobile WebUI URL** on your phone, iPad or laptop. No device
setting, second server or separate installation is needed.

The workflow selector lists **Saved in ComfyUI** files first, once per filename,
then **Imported presets**. Retained folder snapshots and internal Edit/Upscale
presets do not appear as additional normal choices. Explicit image/history reuse
can show its single **Current saved settings** entry. If the ComfyUI folder list
is unavailable, saved copies remain selectable without duplicate filenames.
Refreshing the list preserves the selected workflow and unsent edits; no stored
presets, history or original workflow files are deleted by this organization.

- **Phone / narrow window:** existing compact controls and bottom Generate/progress dock.
- **Desktop / large landscape iPad:** workflow and model selectors across the
  top, broad positive/negative prompts with Generate beside them, open generation,
  resolution and LoRA settings on the left, and a large preview on the right.
  The full-width gallery sits underneath. Advanced mappings remain collapsible.
  Click a thumbnail to inspect that exact saved image. Previous/next, **Save image**
  and collapsible **Details** are integrated below the preview. Phones retain the
  separate image viewer. The toolbar wraps to additional rows as needed, including
  with multiple text encoders or long filenames. The left settings form one stack;
  the right preview keeps the image's aspect ratio without a viewport-sized height
  or nested scrollbar. Use normal page scrolling to reach details and image actions.
  Clicking a gallery image brings its preview and actions into view. Live progress
  stays with the preview; Generate and the red run/queue cancellation buttons stay
  beside the prompts. The gallery follows the taller workspace column.
  Returning to phone width restores the compact sections' open/closed preferences.
  Redundant Create/Gallery tabs are hidden in this view.
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
- **Generate button:** a blue backdrop fills behind the label during sampling,
  using the current stage's reported step percentage. Model loading, queueing
  and processing use a moving highlight without inventing a percentage. It pauses
  while reconnecting. Only confirmed workflow success finishes the fill, briefly
  showing Complete before resetting; sampler completion still waits for later
  decoding/saving stages. Failures and cancellations show brief feedback. The
  button remains disabled during an active job.
- **Generation settings:** Steps, CFG/guidance, Sampler, Scheduler, Seed and Batch
  size use the selected workflow's mapped inputs and installed node choices.
  Missing recognized controls in older presets are discovered on load. Inputs
  on separate sampler/noise/scheduler nodes work too; graph connections stay linked.
  Existing Advanced mappings appear here with their saved keys/roles retained.
  Turn off **Randomize seed for each generation** to enter a fixed seed.
  **Reuse last seed** copies just the latest matching completed generation's seed(s), turns
  randomization off and preserves the prompt and other edits. Seeds retain their
  exact 64-bit values. Whole-setting reuse remains available separately.
- **Batch count / Batch size:** count queues that many workflow runs; size is the
  workflow's images per run. For example, count 2 and size 3 requests two runs of
  three images. Count defaults to 1, is saved with the draft, and is limited to
  20 runs within the existing 20-unfinished-job limit. Random mode chooses a seed
  per run; fixed mode retains the same seed and may reuse cached output. Progress
  follows the active batch member; History lists each run. The red **×** cancels
  only the current run. When additional runs are queued, an attached counter
  peeks from behind it. Click once to expand **Stop run & clear queue**, then
  activate and confirm to remove this browser’s queued runs and stop its running
  work. Escape collapses it. Queue removal happens first; other browsers’ jobs
  and jobs from other output folders are preserved. Running interruption requires
  ComfyUI’s safe per-job cancellation endpoint; no global interrupt is sent.
  Reloads/retries do not submit the batch again. An uncertain/rejected submission
  stops the remaining runs and reports where it stopped; check History/ComfyUI
  before starting another batch. Reusing whole image/job settings resets count to 1.
- **History / Favourites:** separate buttons near the prompt open prompt history
  and liked images. Image hearts toggle Favourites in the central selected-image
  panel or phone viewer. Existing Keep marks carry across unchanged. Image hearts
  are the only Favourites category; History provides prompt search, reuse and deletion.
- **Refresh / cleanup:** compact refresh icons sit beside the workflow selector
  and first model selector. The small broom by Models requests idle VRAM cleanup.
  Icons have accessible labels, tooltips and 44px touch targets.
- **Gallery:** the full-width desktop gallery has All images, Favourites, History and Wastebin views.
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
1000 × 600 CSS pixels. The desktop workbench fits landscape windows from 1024px wide
(at least a 4:3 aspect ratio), or windows at least 1440px wide, with a minimum
height of 600px. Content uses up to 2560px on ultrawide monitors.
iPad Split View, browser zoom, small tablets and short
windows can use the compact layout. Controls retain their existing touch sizing.
Resizing or rotating preserves your prompt, workflow, settings and current job.
Generation settings appear before LoRAs. Choosing a replacement LoRA updates its
checkbox label and enables that slot; uncheck it afterward to leave it disabled.
Other slots and the original workflow retain their settings.

The **Resolution** panel also exposes calculator-node inputs, including
ControlAltAI's **FluxResolutionNode**: megapixels, the node's aspect-ratio presets
(such as **2:3 (Classic Portrait)**), rounding, custom-ratio toggle and custom ratio.
Choices come from your installed node's ComfyUI metadata; saved defaults are kept.
The calculator continues feeding width/height into the latent-image node. The
WebUI changes its inputs without replacing those connections or calculating its
own dimensions. Existing presets gain missing calculator controls on load;
calculator fields already mapped under Advanced appear in Resolution with their
keys and saved mappings retained. Update/restart the testing copy, reload the
browser and select your saved workflow to see them. The model refresh icon also
refreshes node choices.

Saved workflows, custom nodes, GGUF models, LoRAs and session recovery use the
same backend. [Foreground SSH startup](SSH.md) is included in 1.0.

## Shared visual styling

All layouts use the same charcoal surfaces, blue controls and green online
indicator. Colors, control/panel radii, spacing, typography and shadows are
defined at the top of `comfyui_control/mobile/web/style.css`. Component rules
reuse those tokens. Restrained highlights separate panels, inputs and raised
buttons; gallery filters use segmented selection styling. Compact header spacing,
44px standard controls retain comfortable targets. Desktop settings stay open;
compact sections retain their existing disclosure behavior and breakpoints.
Keyboard focus stays visible, controls retain their touch targets, and reduced
motion disables the control transitions and loading animation.

Expandable sections fade and resize over 180ms on opening and closing, including
keyboard activation and reversing an in-progress transition. Dialogs also fade
where the browser supports native discrete transitions. Reduced motion disables
these effects. Model/workflow dropdowns retain the browser's native menus and
keyboard/touch behavior; their popup animation is controlled by the browser/OS.

Browser chrome and the PWA manifest use the same background color. The shell
cache version is updated for this theme; reload an existing tab to get the styles.
The existing application icon is retained.

## Run from source

The responsive workspace is on **testing/webui-workspace**, version
**1.1.0.dev7**. It branches from main; the uninstall work remains separate.
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

The **VRAM cleanup** broom by Models unloads idle models using
ComfyUI's existing API. It is disabled while work is queued or running. The
server checks the queue again before requesting cleanup; the next generation
will reload its models.

## Saved-image actions

- **Heart / Favourites:** like/unlike the selected image for this browser's
  Favourites gallery. No file is moved. Likes survive app restarts and are scoped to
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
- **Delete:** after confirmation naming the image, mark it in the persistent local
  image-library metadata. The original file stays in place, untouched. Deleted
  images disappear from normal gallery and public job image lists; the original
  generation journal is retained.
- **Wastebin:** open it from Gallery or the bin icon beside VRAM cleanup. It shows
  this browser's deleted images with thumbnails and original filenames. Restore
  removes the marker immediately, even if the original storage is offline.
- **Delete permanently / Empty Wastebin:** explicitly confirm removal of the
  selected file or displayed Wastebin snapshot. The existing bounded worker
  unlinks only files beneath the configured local/NFS output location after
  checking the recorded directory and regular-file identities. Changed/replaced
  files, symlinks, missing/unmounted storage and permission failures fail safely;
  unsuccessful entries retain their markers and error messages. A timeout can
  leave an uncertain result: inspect storage before retrying. Missing files are
  never treated as proof that a failed request succeeded.

The Wastebin follows existing browser ownership and output-folder isolation.
Metadata sharing grants no delete permission. Ordinary ComfyUI output without
mobile ownership can still be managed. Remote-only image proxies cannot delete
files. The old `/api/trash` URLs/action key remain compatible; new Delete requests
use `action: "delete"`. Images physically moved by older versions remain visible,
restorable and eligible for confirmed permanent deletion through the same panel.

## Check on your devices

1. Try phone portrait/landscape, large iPad portrait/landscape and Split View,
   and a laptop at different window sizes or browser zoom levels.
2. Enter a draft and rotate/resize; confirm the text and workflow stay selected.
3. Generate: confirm model loading, progress and Cancel remain accessible while
   scrolling. On desktop, Generate stays beside the prompts; phones keep the
   bottom dock. Check the completed image and Save image.
4. Refresh or briefly disconnect during generation; confirm recovery and no
   duplicate request. Try Gallery, comparison selection and closing the viewer.
5. Select an older image, tap its heart, refresh and check Favourites. Delete that image,
   confirm other files remain, then restore it. Try actions while changing selection.

Chromium and Linux WebKit checks exercise layout, generation/recovery, comparison,
metadata reuse, image hearts, Wastebin deletion/restore and browser isolation with a simulated ComfyUI
backend and temporary images. Physical Apple devices, VPN routes, GPU inference
and actual NAS Wastebin deletion/restore still need manual testing for this branch.
Repeat browser checks with Playwright:

```bash
python tests/manual/mobile_responsive_browser.py --browser chromium
python tests/manual/mobile_responsive_browser.py --browser webkit
```
