# Guide for Codex sessions

Read `HANDOFF.md`, `docs/WEBUI_PRESENTATION.md` and
`docs/FEATURE_PORT_INTEGRATION.md` before changing code. `AGENTS.md` is the canonical agent guide (not `agent.md`). Inspect the current
branch, recent commits and working tree. Treat the implementation as the baseline;
do not assume earlier requests or deferred integrations are unfinished assignments.

For the next session, start with the current-session snapshot at the top of
`HANDOFF.md`. Its newest section supersedes older, chronological notes. The
latest published baseline is 1.2.1; check the actual branch, remote and working
tree rather than assuming a previous checkout is current. `AGENTS.md` is the only
agent guide; do not create a second `AGENT.md` with conflicting instructions.

## Project and architecture

ComfyUI Control is a Linux Python/Qt controller with one buildless responsive
WebUI. ComfyUI owns model inference and workflow execution. Python 3.10+ is
required; runtime dependencies are in `pyproject.toml`. No frontend build is needed.

Paths below are under `comfyui_control/` unless stated otherwise:

| Location | Responsibility |
| --- | --- |
| `cli.py`, `app.py`, `*_widgets.py` | Entry point and native Qt application/settings. |
| `controller.py`, `headless.py`, `mobile/runtime.py` | Process ownership, SSH runtime and Qt/asyncio bridge. |
| `mobile/service.py`, `mobile/client.py` | Shared persisted jobs, queue, UUID idempotency, ComfyUI HTTP/WebSocket and reconnect. |
| `mobile/server.py`, `mobile/settings.py` | HTTP/SSE, sessions, permissions and WebUI preferences. |
| `mobile/workflows.py`, `mobile/workflow_sources.py`, `mobile/editor_subgraphs.py`, `mobile/input_metadata.py` | Graph import, explicit mappings, saved workflows and metadata validation. |
| `mobile/image_actions.py`, `mobile/image_pixels.py`, `mobile/image_metadata.py` | Image-library sidecar, action bindings, pixel copies and image metadata. |
| `network_output.py`, `background_process.py` | Authorized output filesystem operations and bounded workers, including read-only output-version resolution. |
| `bundled_workflows.py`, `workflow_webui.py` | Optional workflow installation and asynchronous ComfyUI readiness checks. |
| `mobile/web/app.js` | One shared application controller, selection, drafts, requests, generation and pending journal. |
| `mobile/web/feature_*.js` | Shared Generate/image-action components and transport. |
| `mobile/web/feature_gallery_library.js/css` | Shared Gallery toolbar, Favourites/Wastebin collection previews and heart indicators. |
| `tests/`, `tests/manual/` at repository root | pytest and automated browser/protocol fixtures. |

## Desktop and Phone boundaries

- Desktop and Phone presentations are developed independently, sharing application
  logic, state, backend APIs and persistence. Do not create a second application,
  queue, selection store or image-action implementation for either presentation.
- Preserve main's yellow accent (`#e7f67b`), native controls and existing layouts.
  Functionality and direct access to common actions take priority over polish.
- Desktop-only arrangement belongs in `mobile/web/presentation_desktop.css` and
  `presentation_desktop.js`. Scope CSS with
  `:where(html[data-presentation="desktop"])`. The adapter owns placement and
  labels, never API requests or business logic.
- The existing desktop breakpoint is 1000px wide and 600px tall. Retain it unless
  explicitly asked to change it. There is no Forge presentation coordinator or
  separate Phone JavaScript adapter on this branch; do not import Forge layout/theme files.
- Reuse existing DOM nodes, IDs and handlers; restore their original placement and
  labels on leaving desktop. New desktop containers use `data-desktop-slot`.
  Phone changes require an explicit request. Desktop work must preserve Phone
  layout, styling, navigation, interactions, drafts and live jobs.
- Shared `style.css`, `index.html`, `app.js` and feature components affect both
  presentations. Make necessary changes narrowly and verify both. Do not add
  polling, duplicate listeners or redundant capability requests.
- Phone refinements live in `presentation_phone.css`, scoped to
  `:where(html[data-presentation="mobile"])`. The existing placement helper also
  places shared image controls and refresh/cleanup buttons on Phone. Preserve its
  tabs, fixed dock, inline/native details, prompt history, negative-prompt state,
  slider bounds, exact reuse, New variation and viewer navigation.
  Phone Compare is an additional button, using the existing picker and comparison.
  Phone Create places the result section before the workflow form, labels completed
  results `Preview & results`, and hides their workflow filename. Active jobs stay
  in the dock; failure/unknown-job diagnostics remain visible.
  See `docs/PHONE_UI.md` for current behavior and verification.
- Keep new public assets in `mobile/server.py`'s allowlist and `web/sw.js`'s shell;
  bump the shell cache when shipping changed assets. Never cache private APIs or
  images. Preserve reduced-motion support.

## Current implementation contracts (1.2.1)

- Workflow/model refresh reconciles option catalogues in place when graph/control
  structure is unchanged. Preserve select/button DOM identity, handlers, drafts,
  exact seeds, mappings, focus, text selection and scroll. Structural changes use
  the already-loaded description; never clear controls before a network await.
  Failed/stale refreshes must not clear or replace the selected form/workflow list.
- The shared workflow picker lists only ComfyUI's saved workflows (`/userdata`
  workflows directory), plus at most one top `Reused image` entry after settings
  reuse. Stored/internal preset snapshots remain available to jobs but stay out
  of the menu. A saved filename is a UI alias; backend preset IDs remain canonical.
- Saved-editor imports can retain safely recognized active/bypassed MODEL/CLIP
  LoRA loaders. Checked means active; unchecked means genuine connection bypass.
  Preserve model/strength values. Recover old omitted nodes by reselecting the
  saved workflow. Never guess unknown node/widget serialization or API-only nodes.
- Desktop header contains live speed, VRAM, GPU and steps; reconnect feedback is
  `Reconnecting...`. The original connection badge remains. Native submission
  progress and duplicate offline/configuration prose stay out of Desktop Create.
  Active generation keeps the last completed image and its preview dimensions;
  Cancel is beside the preview heading. Preserve failure/unknown-job diagnostics.
- Desktop prompts use fixed flow rows and expanded editors overlay downward with
  shadows, ending at the main workflow card's bottom border. Negative prompt is
  open by default with its own icon toggle, no native collapse arrow. Restore
  Phone's original negative-prompt DOM/open state and inline sizing on resize.
- LoRAs, Generation settings, Resolution and Advanced open upward as bounded,
  internally scrolling overlays. Their summaries and columns do not move; arrows
  rotate in fixed-width slots. Keep dependent ResizeObserver writes frame-batched.
- Desktop LoRA rows hide redundant visual field labels (retain accessible names),
  pair strength sliders with numeric inputs, and use slider range -2..2. Restore
  original Phone slider bounds; numeric metadata limits/values stay authoritative.
- Desktop Gallery uses an icon refresh. Prompt controls use chevrons and an
  idle-only broom action calling the existing VRAM API. Desktop hides prompt
  history and the fixed-seed explanatory hint; Phone retains both.
- Phone also has refresh/cleanup icons, prompt chevrons and live step metrics in
  its existing dock. Shared Heart/Edit/Upscale/Delete controls appear on completed
  results and in the saved-image viewer; a running Phone job retains its live
  preview without those controls. One component, capability signature and pending
  journal serve both presentations. Action forms close on breakpoint transitions.
- Both presentations have Gallery Wastebin/Favourites icons next to Refresh and
  heart indicators on marked thumbnails. Collection dialogs reuse `renderImages`,
  thumbnail decoding/reduced motion and the existing viewer. Wastebin previews use
  only private `/api/trash` thumbnails. Favourites includes older marked versions
  outside the recent 200; scanning and marks remain bounded and controller/output
  scoped. All clients admitted by this WebUI's access rules share the image library.
  Keep thumbnails/DOM identity on mark updates, ignore stale reads after
  close/authentication/mutations, and add no collection polling. See
  `docs/GALLERY_COLLECTIONS.md` for details and checks.
- Desktop collection dialogs are viewport-clamped up to 1200×900 with four columns;
  Phone keeps two. Keep loading geometry stable and avoid visible transient prose
  during heart saves. Confirmed heart updates reuse current capabilities without
  a redundant read. Invalidate the Gallery revision after local metadata edits.
- Wastebin's Clear Bin confirms an explicit displayed token snapshot and calls the
  existing permanent-delete API. New entries stay out of that snapshot; failures
  stay in the bin with errors. Disable duplicate actions while clearing. An uncertain
  response requires Refresh, never automatic resubmission.
- Desktop Gallery splits Select two images beside a multi-image Select mode.
  Bulk actions live in a right-click/Shift+F10 menu on selected thumbnails;
  selection count/help remain hidden and feedback overlays preserve grid position. Preserve keyboard
  navigation, viewport bounds and dismissal on lifecycle/selection changes.
  Reuse the existing per-image action route and controller reconciliation; retain
  exact-version snapshots, permissions, partial failures and uncertain-result
  handling. No bulk selection persists. Compare and bulk selection are mutually
  exclusive; leaving Gallery or changing presentation clears bulk selection and
  stops further batch requests. Phone keeps its two-button comparison row and has
  a pictographic Select icon next to Refresh. Use the same selection/runner/menu;
  a 550ms hold on a selected Phone thumbnail opens it. Preserve movement, scroll,
  pointer cancellation/multitouch/lifecycle guards and suppress the release click.
  Keep 48px Phone targets and existing 8px gaps while compacting vertical spacing.
- The normal Desktop Gallery image viewer uses Left/Right for navigation,
  Backspace for the existing confirmed single Delete and Space for the current
  image/version in the shared bulk selection. Retain selections while browsing;
  right-click uses the same bulk menu within the modal top layer. Exclude typing,
  nested dialogs/menus, repeats and pending actions from shortcuts. Phone remains
  unaffected. Restore menu/feedback nodes when the viewer closes.
- `feature_image_confirm.js` supplies the shared in-app confirmation dialog for
  single/bulk Delete and Clear Bin. Keep Cancel/Escape, initial Cancel focus,
  snapshot/stale guards and separate virtual/permanent deletion wording.
- Confirmed Clear Bin may complete a missing original when the saved root/parent
  identities match. For an NFS remount that only renumbered st_dev, metadata-only
  cleanup may accept matching inode IDs for the full parent chain on a currently
  mounted NFS root, without nested device changes; recheck directories and mount.
  This exception must never unlink an existing file or relax its full fingerprint
  check. Missing/replaced storage, parents, symlinks, ownership and permission
  failures remain guarded. No listing silently removes missing-file markers.
  Preview failures show filenames and storage guidance.
- Both Desktop Preview and enlarged viewer use Compare instead of New variation.
  One second-image picker reuses the shared gallery renderer/loader and existing
  comparison dialog. Keep drafts/selection on cancel, ignore late responses, exclude
  the source image, preserve square scrolling rows, wait for thumbnail decoding,
  and honor reduced motion. Enlarged-view picker centers over Compare, bottom at
  the Upscale/Delete row, clamped to the viewport; regular picker matches Preview.
  Both presentations hide the viewer filename/iPhone instructions. Phone places
  Details after the image action and reuse/Compare rows; Desktop keeps its placement.
  Phone Close overlays the image top right; the image flexes to fit the controls
  within the viewport. Expanded metadata/diagnostics use bounded internal scrolling.
- Do not modify any ComfyUI installation. User explicitly declined an external
  immediate-VRAM-cleanup patch. The existing idle-only `/free` request remains;
  server-side processing timing is outside this app's guarantee.

- Ordinary background-tab visibility retains the existing SSE stream for sampling
  title progress and completed results; pagehide/offline/logout still cancel and
  resume safely. Never add a second poller or resubmit work on return. Older full
  state responses may hydrate missing details only for matching instance/job/
  prompt/status/image count, preserving newer summaries and recovery epochs.
  Browser titles use validated shared sampling feedback and reset outside sampling.

- Batch Count is an app-level repeat count (1..20 under the existing total queue
  limit). Explicit `batch_count` requests render mapped batch inputs as 1 for each
  separate prompt; legacy/internal requests without it keep saved batch semantics.
  Preserve every child's durable UUID/seed, owner/scope, uncertain POST journal,
  safe group cancellation and no-resubmission behavior. UI follows the current
  run within its batch, preserving drafts and earlier results/failure diagnostics.

- Desktop has a compact hidden-folder switch beside the brand, off by default
  and persisted in browser storage. `include_hidden=0` filters dot-prefixed
  relative folder components before the Gallery limit, including Favourites and
  Compare. Phone/API defaults remain unfiltered; Wastebin lists all entries.
  Preserve bounded visible-page references, per-client filtering/revisions, stale
  response/selection guards and open collections on presentation changes.

- Completed output refs must resolve their actual file version before old deletion
  markers can filter a replacement at a reused filename. Use the bounded read-only
  versions worker, keep original deleted jobs hidden, and fail closed on uncertain
  storage. Never inherit another job's timestamp; unversioned URL/thumbnail caches
  use job identity. Journal completion refs before awaiting version resolution.

## Data and safety contracts

- Act on the explicitly selected image and version. Ignore stale async responses
  after navigation; opening/cancelling an action must preserve generation drafts.
  Full settings reuse preserves exact 64-bit seeds and never auto-generates.
- Use the existing pending-submission journal and UUID for uncertain retries,
  including image workflows. Reconnect must not resubmit accepted work.
- Preserve unknown workflow nodes, links, model choices, GGUF/LoRA wiring and
  saved editor settings. Change only validated mapped literals; never invent a
  replacement Qwen/SeedVR pipeline. Named action bindings live in `IMAGE_WORKFLOWS`.
- Favourites use the existing Keep sidecar (`keep`/`kept`), now shared between
  devices of this controller/output. Valid legacy browser marks merge atomically;
  unmarking must remove old copies so a heart cannot reappear. Virtual Delete
  changes metadata only. Restore removes that marker; only explicitly confirmed
  permanent deletion may remove originals. Retain configured-root, file/directory
  identity, symlink, ownership and output-scope guards and bounded NFS workers.
  Failed deletion stays in Wastebin with its error.
- Preserve Host/Origin checks, authentication and CSP. Library sharing includes
  initial virtual Delete, bin listing/thumbnails, restore and confirmed permanent
  deletion for every admitted browser, independent of image-settings sharing.
  Preserve each bin record's recorded owner for legacy-worker validation.
  Live jobs, cancellation, prompt history and optional settings reuse remain
  browser-specific. Delete does not require the generating browser; keep metadata/job privacy separate.
  Never commit credentials or private prompts.
- Keep blocking filesystem/NFS/GPU work off Qt and HTTP event loops. Preserve
  atomic metadata writes and corruption safeguards. Do not disturb user settings
  or unrelated mounts; do not start competing app instances against one config.

## Bundled workflow installer

- `bundled_workflows.py` is the standard-library-only inspect/copy worker;
  `workflow_widgets.py` is the optional native dialog. The main app offers it after
  existing-folder selection and successful fresh setup, and has a permanent button
  beside Settings. Do not prompt repeatedly on startup or start ComfyUI during copying.
- `workflow_webui.py` checks API readiness asynchronously. Its explicit button may
  offer one controller-managed start after confirmation, then wait for readiness
  before opening the browser. Never duplicate a starting/running process; stop
  pending opening on cancellation, failure, changed installations or timeout.
- Target exactly `<selected ComfyUI>/user/default/workflows`. Preserve bundled JSON
  bytes. Default to skipping existing files; replacement requires a reviewed exact
  file identity and confirmation of those names. Keep symlink/root/directory checks,
  atomic writes, per-file errors, bounded workers and uncertain-result handling.
- Show the one-time regular ComfyUI/Manager setup notice and an explicit Open ComfyUI
  WebUI button using the configured backend address. Never install nodes/models,
  execute workflows or modify other installations as part of copying files.
- Use disposable installations in `tests/test_bundled_workflows.py` for verification;
  do not test installation/replacement on the user's real ComfyUI folder.

## Local setup and verification

Run from the checkout root; use this checkout's environment, not paths from a
previous Codex workspace. Linux Qt/browser system libraries may be needed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest
.venv/bin/comfyui-control
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

For WebUI changes, install optional Playwright and its browsers:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium webkit firefox
.venv/bin/python tests/manual/desktop_image_actions_browser.py --browser chromium --output /tmp/control-desktop-actions-check
.venv/bin/python tests/manual/mobile_responsive_browser.py --browser chromium --output /tmp/control-responsive-check
.venv/bin/python tests/manual/mobile_generate_button_browser.py --browser chromium --output /tmp/control-generate-check
.venv/bin/python tests/manual/phone_image_actions_browser.py --browser chromium --output /tmp/control-phone-actions-check
.venv/bin/python tests/manual/gallery_collections_browser.py --browser chromium --output /tmp/control-gallery-library-check
.venv/bin/python tests/manual/gallery_library_updates_browser.py --browser chromium --output /tmp/control-shared-library-check
.venv/bin/python tests/manual/phone_gallery_bulk_browser.py --browser chromium --output /tmp/control-phone-gallery-check
.venv/bin/python tests/manual/hidden_gallery_browser.py --browser chromium --output /tmp/control-hidden-gallery-check
.venv/bin/python tests/manual/preview_reused_filename_browser.py --browser firefox --output /tmp/control-preview-version-check
.venv/bin/python tests/manual/background_results_browser.py --browser firefox --output /tmp/control-background-check
.venv/bin/python tests/manual/batch_count_browser.py --browser firefox --output /tmp/control-batch-check
git diff --check
```

Also run the focused protocol/browser checks relevant to a change:

```bash
.venv/bin/python tests/manual/refresh_stability_browser.py --browser chromium --output /tmp/control-refresh-check
.venv/bin/python tests/manual/bypassed_loras_browser.py --browser chromium --output /tmp/control-bypassed-loras-check
.venv/bin/python tests/manual/saved_workflow_picker_browser.py --browser chromium --output /tmp/control-workflow-picker-check
.venv/bin/python tests/manual/generate_transition_browser.py --browser chromium --output /tmp/control-submit-transition-check
```

Repeat relevant browser checks with WebKit, Chromium or Firefox and fresh output directories. See
`docs/WEBUI_PRESENTATION.md` for Phone pixel comparisons against an exported
baseline. Node runs optional shared-JS tests; it is not a runtime/build dependency.
Browser/protocol fixtures do not prove real GPU inference, NAS or physical Phone
behavior. Historical test counts are evidence, not a substitute for current checks.

Keep changes focused, follow adjacent conventions and run relevant checks. Do not
change versions, rebuild release artifacts, merge, tag or publish unless requested.
Commit/push when authorized; never force-push by default. After a push, provide the
branch/commit and full fresh-clone, venv, install and launch testing commands.
