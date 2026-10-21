# Session handoff — 2026-10-21

## Latest work: enlarged desktop preview and equal row gaps

The user requested equal spacing between Save/actions/reuse rows and double-click
on the desktop preview to enlarge it in a centered floating box, with a shadow,
dimmed page, heart and Close button. They explicitly authorized pushing the result
to testing after completion. This follows `e263485` on `testing/webui-desktop-forge`.

- Hide the empty desktop workflow-status paragraph, whose 8px margin created the
  extra gap. The two action-row gaps are now 6px when no status message is present.
- Desktop CSS/JS create a native dialog with viewport-bounded image dimensions,
  the existing dialog shadow/backdrop tokens, heart and Close controls. The original
  image and heart move with reversible `place()`; there is no duplicate image,
  action handler, API call or application state. Enter/Space provide keyboard
  opening, Close/Escape restore focus, and the same Favourites action works inside.
- Popup resize uses the image aspect ratio and viewport CSS. Close explicitly
  refreshes inline heart positioning. Selection changes close the popup before
  updating the image. Returning to sign-in also closes it. A desktop-to-mobile
  transition closes it and restores the
  original mobile controls and image attributes; no mobile/shared styles or logic
  changed. Public shell cache version is 9.
- Added checks for exact row gaps, centered/bounded portrait/landscape popup,
  backdrop/shadow, original-node identity, Escape/focus/keyboard, resizing while
  open, and an open-popup mobile round trip. The responsive check toggles the
  existing heart inside the popup, closes it, and verifies inline/reloaded state.
- Chromium and WebKit passed the desktop matrix at five widths and all five
  compact pixel comparisons against `e263485`. Final desktop reruns also passed
  resizing an open popup and restoring the heart position afterward. Both engines
  passed responsive/reconnect/privacy/image actions, including the popup heart,
  inline state, reload, Trash/restore, and mobile restoration. Chromium additionally
  verified an open popup closes through sign-in/recovery without resetting state.
  Chromium isolation passed unique controls/listeners, exact seeds, live jobs and
  cancellation. Screenshots were inspected; syntax, protected-file and whitespace
  checks passed. No shared/backend code changed; the Python suite was not rerun
  for this presentation-only change.

Artifacts: `/tmp/control-zoom-*`; baseline export is `e263485` at
`/tmp/control-zoom-baseline/comfyui_control/mobile/web`.

## Previously pushed: preview heart, action rows and small-preview fix

The user requested the desktop Favourites heart on the image corner, even action
rows (Edit/Upscale/Details/Trash and Reuse settings/New variation), with Save image
and arrows unchanged. They also asked to check the intermittently small preview.
This follows pushed `a989c2f`; the user authorized committing and pushing this
verified batch to `testing/webui-desktop-forge`.

- The original selected-image heart moves through `place()` into the existing
  desktop image stage. A desktop ResizeObserver tracks the image's rendered bounds
  so the heart stays inset 8px from its upper-right corner, including letterboxing.
  The original action Map/listener owns favourites, pending state and requests;
  switching to mobile restores the original row automatically. Desktop-only heart
  styling retains the existing Favourites tokens, with a shadow over light images.
- Desktop action rows use four and two equal columns with the same gap and edges;
  the Save/arrow selectors are unchanged. Mobile/shared component styles untouched.
- Root cause of the small preview: `#job-output` kept `flex:1` even empty or showing
  a previous non-complete job, reserving space above the saved image. It is now
  hidden while saved images are shown without an active run, or explicitly inspected
  during one. Generation itself and the ordinary live preview remain unchanged.
- Product files are only desktop CSS/JS and public cache version 8 in `sw.js`.
  Added desktop geometry checks for heart insets, four equal actions, aligned reuse
  edges/midpoint, and sufficient preview space, including no-job/cancelled/failed/
  running-inspection cases. Responsive action assertions now locate the same
  controls through the selected-image panel so the moved heart is exercised too.
  Desktop geometry writes are queued outside ResizeObserver delivery to avoid
  WebKit notification loops; the final responsive rerun has no page errors.
- Chromium and WebKit passed the five-width desktop matrix and five compact pixel
  comparisons against `a989c2f`, including the new heart/row/preview-state checks.
  Both passed responsive/reconnect/privacy, Favourites/reload/unlike, delayed-action
  targeting, Trash/restore, and mobile viewer/restoration checks. Final Chromium
  isolation passed with live jobs, exact seeds, unique controls and cancellation.
  Screenshots were inspected. Syntax, protected-file and whitespace checks passed.
  The Python suite was not rerun for this desktop-only follow-up; earlier suite
  results and the known fixture failure remain documented separately below.

Artifacts: `/tmp/control-heart-*`; baseline exported from `a989c2f` under
`/tmp/control-heart-baseline/comfyui_control/mobile/web`.

## Previously pushed: expanded prompt aligned with Batch count

After pushed `3b8bfcb`, the user requested that the expanded prompt's initial lower
border align with the bottom of Batch count and explicitly authorized an immediate
push after the change. The existing desktop geometry ResizeObserver now measures
that edge and sets a desktop-only CSS height variable on each prompt editor.
It observes settings and prompt geometry, so toolbar wrapping, viewport changes
and workflow fields update the alignment. Manual resizing still overrides the
initial CSS size until the existing Expand/Collapse handler clears it. No new
controls, handlers, requests or application state; mobile/shared logic is unchanged.
The public shell cache is version 7. The desktop browser check now asserts the
edge alignment within 1px at every desktop size, alongside no layout shift and
expanded-editor mobile round trips. Chromium and WebKit passed the desktop matrix at all five widths, including the
new 1px alignment assertion, unchanged workspace bounds, edited draft retention,
and expanded mobile round trips. Chromium also passed all five compact pixel
comparisons against `3b8bfcb`. Screenshots, JS/Python syntax, protected-file diffs
and whitespace checks passed. Artifacts are under `/tmp/control-batch-prompt-*`.
The Python suite was not rerun for this geometry-only follow-up; the preceding
run remains documented separately below.

## Previously pushed: floating desktop prompt editor

The user requested Expand to float the positive prompt above surrounding controls
without shifting the UI, with a shadow, plus more width for positive and less for
negative. This work follows pushed `d3d34f2`; the user authorized committing and pushing
these verified changes to `testing/webui-desktop-forge`.

- Desktop CSS keeps a 112px collapsed footprint, absolutely positions the expanded
  existing scroll frame above settings, and uses the existing dialog shadow token.
  The positive/negative columns now use 2.2:1 instead of 1.4:1 from 1280px upward.
  The desktop 14px prompt font remains unchanged.
- No new JS, controls, handlers or state; the shared Expand/Collapse class and live
  textarea are retained. Mobile/tablet adapters, theme, shared styling/app/backend
  are untouched. The public asset cache is bumped to version 6 in `sw.js`.
- Extended the desktop browser check to assert unchanged workspace rectangles on
  expansion/collapse, actual painting above settings, a visible shadow, wider
  positive inputs, preserved editing, and expanded mobile-to-desktop restoration.
  Baseline desktop Advanced/gallery ordering accepts either historic order while
  retaining non-overlap; current ordering and all mobile pixel checks remain strict.
- Full Python run: 430 passed, 1 failed (the existing old-job equality fixture).
  Chromium and WebKit passed desktop/skin/mobile baseline checks at five desktop
  and five compact sizes. Chromium presentation isolation and broad responsive,
  reconnect, progress/cancellation, image actions and comparison checks passed.
  WebKit also verified an expanded-editor mobile-to-desktop round trip without
  losing the original textarea, draft or layout. Screenshots were inspected in
  both engines at laptop sizes. Syntax and whitespace checks passed.

Artifacts: `/tmp/control-prompt-overlay-*`; baseline exported from `d3d34f2` under
`/tmp/control-prompt-overlay-baseline/comfyui_control/mobile/web`. Browser checks
use protocol fixtures, not real inference or physical devices.

## Previously pushed: desktop gallery, History and control polish

The user requested inset scrollbars, centered text in all buttons, larger gallery
thumbnails filling the width, a unified gallery/comparison bar without the desktop
History shortcut, eight gallery rows before internal scrolling, Advanced below the
gallery, and a wider prompt History popup with six cards and inset Delete buttons.
The user authorized committing and pushing these verified refinements to
`testing/webui-desktop-forge`, following the previous push at `4342d8e`.

- Product changes are confined to `presentation_desktop.css/js` and the public
  shell-cache version bump from 3 to 4 in `sw.js`. Mobile adapters, shared skins,
  theme, HTML, application/feature code and backend remain untouched.
- Textareas keep their IDs/listeners inside padded desktop frames through reversible
  `place()`. Dialog scroll areas are inset; desktop action labels are centered,
  including Expand and Clear Queue. Prompt excerpts remain left-aligned content.
- Gallery columns use a 200px minimum and flexible widths. A desktop-only geometry
  observer limits the grid to eight complete rows; `max-content` implicit rows
  prevent WebKit from shrinking unloaded-image rows inside that limit. Existing
  comparison buttons move reversibly into the filter bar. Only the desktop gallery
  job-History shortcut is hidden; prompt History and mobile history remain intact.
- Advanced stays in its original form and occupies the full-width row below the
  gallery. Prompt History is up to 1080px wide with six cards before list scrolling,
  responsive excerpt lengths, and inset top-right Delete buttons.
- Added `tests/manual/desktop_gallery_browser.py` (110 images, 15 private prompts);
  adapted desktop geometry/outer-input skin expectations and moved the responsive
  job-history shortcut check to mobile, retaining its original functional coverage.
  No mobile pixel/isolation assertions were removed. Updated presentation docs.

Verification of this work:

- Full Python suite: **430 passed, 1 failed**, the documented old-job equality
  failure involving `seconds_per_iteration: None`; no assertion/backend workaround.
- Chromium and WebKit passed desktop layout/component skins at five sizes, idle,
  offline, running and portrait/landscape results, plus unchanged mobile/tablet
  pixels at five compact sizes against exported `4342d8e` after desktop round trips.
- Both engines passed presentation isolation, unique controls/listeners, drafts,
  exact seeds and live-job continuity, responsive/reconnection/privacy/image-action
  regressions, and Generate fill/recovery/cancellation/reduced-motion checks.
- Both engines passed the new gallery/History check at 1280×800, 1440×900,
  1920×1080, 2560×1440: full-width larger tiles, eight complete rows, unified bar
  and actual comparison, six cards, Delete bounds/search/reuse/deletion, centered
  button labels, and restored mobile placements. Screenshots were inspected and
  WebKit row sizing/excerpt clipping corrected before the final focused runs.
- Chromium generation/seed/batch checks passed. WebKit's additional generation
  script reached its final no-page-errors assertion after all functional checks,
  then reported two `/api/state due to access control checks` errors during reload.
  The identical failure was reproduced with unchanged `4342d8e` assets served
  directly through the existing asset handler (no route interception), proving it
  predates these changes. An earlier concurrent run also hit a submission timeout.
  Neither app code nor browser error assertions were changed to hide these results.
  JS/Python syntax, whitespace and protected-file diffs passed.

Artifacts: `/tmp/control-gallery-polish-{chromium,webkit}` contains the final
focused screenshots; `/tmp/control-gallery-desktop-final-{chromium,webkit}` has
layout/mobile baseline comparisons. `/tmp/control-gallery-final-*` contains broad
browser logs/screenshots; `/tmp/control-gallery-pytest.log` records the suite.
The baseline export is `/tmp/control-gallery-baseline/comfyui_control/mobile/web`.
`/tmp/control-gallery-generation-baseline-direct-webkit.log` records the matching
baseline reload errors; its temporary runner overrides only server `ASSETS`.
Protocol checks do not establish GPU, NAS, VPN or physical-device compatibility.

## Previously pushed work: screenshot-directed desktop refinements

The initial desktop redesign was pushed as `942f19c` on
`testing/webui-desktop-forge`. The user subsequently requested compact prompts,
a shared cutoff for settings/preview, a Details popup, on-demand Trash ownership
warnings, and cancellation in the toolbar. The user confirmed the desktop-only
scope and explicitly authorized committing and pushing these verified refinements
to `testing/webui-desktop-forge`.

- `presentation_desktop.css/js`: visually hide prompt labels while retaining
  accessible names; omit the positive placeholder ellipsis only on desktop;
  inset Expand in the prompt corner; align Generate/History/Favourites with the
  prompt boxes. Reuse last generation moves to toolbar utilities. Reserve space
  for Cancel Run/Clear Queue at the upper right, avoiding generation-driven
  toolbar/prompt movement. All shared controls move with reversible `place()`.
- A ResizeObserver sizes completed/live image previews to the main settings
  column's bottom edge, preserving image proportions and compact action rows.
  Advanced remains in the original form but occupies the next full-width row.
  Idle and loading states remain compact; loading/error cards contain their
  content within a 360px panel instead of overflowing an auto-height flex box.
- Details sits beside Edit/Upscale/Trash and opens a native desktop dialog with
  the original metadata controls and loader. Copy details includes collapsed
  sections and exact seeds; existing Copy prompt remains available. Escape/Close
  return focus, and a mobile transition closes the popup/restores controls.
- Unavoidable shared UI changes: two optional presentation hooks in
  `presentation.js`, delegated by `image_actions.js`, let desktop display an
  unavailable Trash reason only after attempted use. Mobile retains the original
  disabled button/status behavior. No unavailable action sends a mutation request;
  backend ownership guards are unchanged. The public shell cache is now version 3.
- Mobile adapters, shared styles/theme, `app.js`, HTML and backend are untouched.
  Presentation docs and two manual browser scripts reflect the new desktop flow;
  mobile pixel/isolation assertions remain intact.

Verification for these refinements:

- Final full Python suite: **430 passed, 1 failed**, the same documented old-job
  fixture equality failure (`seconds_per_iteration: None`). An initial run also
  hit a statistics disconnect timeout; that test passed alone and in the final
  full rerun. No backend/test assertion was changed to accommodate it.
- Chromium and WebKit: responsive/reconnection/privacy/reuse/gallery/history,
  previews, Favourites/Trash/restore, generation cancellation, Generate fill,
  unique controls/listeners/live jobs and presentation isolation passed. Chromium
  generation/seed/batch checks also passed.
- Both engines passed the desktop matrix at 1280×800, 1440×900, 1512×982,
  1920×1080, 2560×1440, including empty/offline/running/portrait/landscape results.
  New checks verify the cutoff, unchanged Generate/toolbar geometry on start,
  popup keyboard/focus behavior, full metadata copying including collapsed models,
  exact seeds, no unauthorized image-action POSTs, and popup-open mobile round trips.
- Both engines passed unchanged mobile/tablet pixel comparisons at 390×844,
  430×932, 768×1024, 834×1194, 1024×1366 against exported `942f19c`, after desktop
  round trips. Screenshots were inspected and refined. JS/Python syntax,
  whitespace and protected-file diffs passed.

Latest artifacts are under `/tmp/control-refinements-*`: `desktop-final-*` contains
baseline/mobile comparisons and popup screenshots; `layout-complete-*` contains
final desktop geometry and loading-frame checks; `responsive-final-*` covers
integrated behavior. `/tmp/control-refinement-baseline/comfyui_control/mobile/web`
is the pre-refinement export. These are protocol/fixture checks, not real GPU,
NAS, VPN or physical iOS proof. See the runtime instructions below for browsers.

## Current work: desktop redesign

The Forge-inspired desktop redesign is on `testing/webui-desktop-forge`, based
on `testing/webui-presentation-layers` at `5240e59`. The user authorized committing
and pushing the redesign to a dedicated testing branch. This section supersedes
the earlier “Next task” below.

- `presentation_desktop.css` consolidates the old overlapping layout rules into
  a wrapping, bounded workflow/model toolbar, side-by-side prompts at 1280px+
  (a lone prompt takes the full prompt area), Generate/cancel actions alongside,
  compact slider/value rows and settings left, image workspace right, gallery
  below. Empty/loading previews are compact; saved images preserve their aspect
  ratio within 65dvh. Desktop content is capped at 2240px with settings up to 680px.
- `presentation_desktop.js` uses reversible `place()` for resolution/LoRA reading
  order and toolbar connection hints. Active/completed job cards stay in the
  image workspace. No controls, event handlers, requests or state are duplicated.
- Shared change: only the public `sw.js` cache version was incremented so installed
  shells receive changed desktop assets. Mobile CSS/JS, shared skins/tokens,
  markup, coordinator, application logic and backend remain untouched.
- `docs/WEBUI_PRESENTATION.md` documents the layout and `--desktop-redesign`
  comparison flag. Four manual browser scripts have updated desktop geometry
  expectations or explicit waits for WebKit presentation selection after resizing.
  Mobile isolation and pixel assertions are unchanged.

Verification for this work:

- Full Python suite: **430 passed, 1 failed**, the previously documented
  `test_old_action_preset_and_jobs_are_retained_when_multiplier_mapping_is_added`
  equality failure (`seconds_per_iteration: None`). The focused public shell/cache
  test passed again after the cache change. No timing normalization was changed.
- Chromium: final desktop layout/skin and mobile baseline comparison, isolation,
  responsive/reconnection/gallery/privacy/reuse, generation/seed/batch and Generate
  fill/cancellation checks passed. Supplied editor workflow check also passed.
- WebKit: desktop layout/skin and mobile baseline comparison, isolation, responsive,
  generation/seed/batch and Generate fill/cancellation checks passed. Mobile pixels
  match after waiting for each presentation selection and control restoration.
- Actual screenshots were inspected and used to refine the offline toolbar and
  compact settings. JS/Python syntax, whitespace and protected-file diffs pass.
- Desktop matrix: 1280×800, 1440×900, 1512×982, 1920×1080, 2560×1440.
  Mobile pixel baseline: 390×844, 430×932, 768×1024, 834×1194, 1024×1366,
  including desktop round trips. Protocol fixtures do not establish real GPU,
  NAS, VPN or physical iOS behavior.

Artifacts are under `/tmp/control-*`. The exported pre-change web assets are in
`/tmp/control-desktop-baseline/comfyui_control/mobile/web`. Final screenshot/check
outputs include `/tmp/control-desktop-v5-chromium`,
`/tmp/control-desktop-v6-webkit`, `/tmp/control-responsive-v3-chromium`, and
`/tmp/control-responsive-final-webkit`. They may not survive environment replacement.
For WebKit here, downloaded system libraries are extracted under
`/tmp/control-browser-libs/root` and linked into the browser's local `sys/lib`.
Use `PLAYWRIGHT_BROWSERS_PATH=/workspace/.playwright-browsers`,
`QT_QPA_PLATFORM=offscreen`, `XDG_CACHE_HOME=/tmp/control-cache`, plus
`PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1` and
`LD_LIBRARY_PATH=/tmp/control-browser-libs/root/usr/lib/x86_64-linux-gnu` for WebKit.
The latter bypasses only Playwright's system-library discovery; the libraries
are present in the local browser bundle.

## Completed: independent presentation layers

- Active work branch: `testing/webui-presentation-layers`, created from pushed
  `testing/webui-workspace` commit `cddb86b`. Separation committed and pushed as
  `3a7ae41`. Older branch/application descriptions below are historical context.
- User explicitly requested an architecture-only separation of mobile/desktop
  presentation. Appearance and existing breakpoints are preserved. No additional
  Forge-inspired redesign, workflow/API change or generation change is included.
- New `mobile/web/theme.css` contains shared tokens. `style.css` retains shared
  component skins/animations; `presentation_{mobile,desktop}.{css,js}` isolate
  page layouts/interactions. `presentation.js` selects the mode before first
  paint and coordinates temporary preferences/reversible DOM placements.
- There is one shared HTML/control tree, application state and backend. Desktop
  adapters use `place()` to record return anchors; leaving desktop restores even
  new desktop-only moves without changing the mobile adapter. New desktop slots
  use `data-desktop-slot`. No controls or business logic are cloned.
- `app.js` delegates layout/navigation while retaining all application services,
  workflow fields, requests, progress, recovery and shared feature rendering.
  The only server change is the additional public shell asset allowlist. Shell
  caching and package inclusion cover all six new CSS/JS assets.
- Read `docs/WEBUI_PRESENTATION.md` for file ownership, shared dependencies,
  breakpoints and baseline-comparison commands. `AGENTS.md` now explicitly
  protects mobile and directs desktop-only work to the desktop CSS/JS adapter.

## Next task: Forge-inspired desktop layout

Refine desktop/laptop arrangement using AUTOMATIC1111 / Forge as a layout
reference; preserve our colors, typography, component styling, animated Generate
and cancel controls. Use the desktop CSS/JS adapters described in
`docs/WEBUI_PRESENTATION.md`; retain the shared application and generation logic.
**Mobile/tablet layout, styling and behavior must remain unchanged.** Compare
against the completed separation baseline and rerun mobile isolation/regressions
alongside desktop responsive checks. The redesign has not been implemented by
the separation commit. Installation-specific checks below remain outstanding.

After every push, include the full fresh-clone testing command for the pushed
branch: clone, cd, create `.venv-test`, install with its Python, then launch
`.venv-test/bin/comfyui-control`.

Verification recorded for the completed refactor (not rerun for this doc update):

- Full Python suite: **430 passed, 1 failed**. The failure is still
  `tests/test_image_workflows.py::test_old_action_preset_and_jobs_are_retained_when_multiplier_mapping_is_added`.
  The exact `seconds_per_iteration: None` equality failure was independently
  reproduced on an exported, untouched `cddb86b` baseline; it remains unfixed.
- Chromium and Linux WebKit isolation/live-state checks passed at 390×844,
  430×932, 768×1024, 1280×800, 1440×900, 1920×1080 and 2560×1440, plus rotation.
  Checks disable the inactive stylesheet, verify unique/control-node identity,
  preserve prompts/exact seeds/live jobs and exercise automatic restoration of
  a desktop-only placement unknown to mobile. Generation/queue cancellation
  handlers still work after resizing.
- Both engines passed baseline desktop geometry/component-skin comparisons at
  1280×800, 1440×900, 1512×982, 1920×1080 and 2560×1440 for empty, offline,
  running and portrait/landscape results, including long filenames/prompts.
  Mobile screenshot comparisons passed at 390×844, 430×932, 768×1024, 834×1194
  and 1024×1366 after a desktop round trip (one-channel antialiasing tolerance).
- Chromium responsive/reconnect/gallery/privacy/reuse, generation/seed/batch and
  Generate-fill/cancellation regressions passed. Public asset authentication/cache
  coverage and ZIP asset inclusion passed; JS/Python syntax and whitespace passed.
  Chromium supplied-editor Edit/Upscale, GGUF/dynamic-input/multiplier, draft and
  reload regression checks also passed.
- These remain protocol/fixture checks, not real GPU/NAS/VPN or physical iOS proof.
  Real Editing verification and the installation-specific outstanding work below
  remain relevant. No release, version bump, tag or main merge was performed.

Transient verification artifacts are under `/tmp/presentation-*`, including the
pre-change `web/` snapshot and per-engine screenshots. They may not survive
an environment replacement. The comparison baseline can be recreated from Git.

## Earlier handoff — historical application context


## Verified Git state and scope

- Repository: https://github.com/jhakuzi/comfyui-control; checkout:
  `/workspace/comfyui-control`; active branch: `testing/webui-workspace`.
- Application baseline: local HEAD, tracking ref and a fresh GitHub branch query agreed at
  **`a80cf6c5f66cd66d073a4d1c796015b3b260f97b`**. The checkout was clean before
  this documentation refresh. The subsequent documentation commit changes only
  `AGENTS.md` and `HANDOFF.md`; no application code changes are included.
- GitHub branches checked during this review: `main` at `7e500d9`,
  `testing/webui-workspace` at `a80cf6c`, and `testing/uninstaller` at `b0ee8f0`.
  Eleven obsolete branches were removed earlier at the user's request.
- Python metadata remains **1.1.0.dev7** in `pyproject.toml` and
  `comfyui_control/__init__.py`; RPM spec remains **1.1.0 / 0.2.dev2**.
  No release, tag, main merge, package rebuild or COPR build was performed.
- After reviewing the local document refresh, the user explicitly authorized
  committing and pushing these two documents to `testing/webui-workspace`.
  Recent UI/application changes were already pushed through `a80cf6c`.

Persistent architecture, setup and preservation rules are in `AGENTS.md`.
This handoff replaces obsolete session chronology; Git retains the change history.

## Current implementation

### One responsive frontend

- Buildless HTML/CSS/JS under `comfyui_control/mobile/web/`; no Gradio, new
  framework, second frontend, separate queue or new persistence store.
- Phone retains Create/Gallery tabs, compact disclosures and bottom Generate dock.
  Desktop uses the Forge-inspired arrangement: workflow/models across the top,
  broad positive/negative prompts with Generate alongside, open generation,
  resolution and LoRA panels left, sticky preview right, full-width gallery below.
  Advanced mappings remain collapsible. Palette stays charcoal-blue.
- Desktop/landscape mode starts at 1024px width with at least 4:3 aspect ratio,
  or 1440px width regardless of aspect ratio, both at least 600px high. Medium
  layout starts at 1000 × 600; ultrawide content is capped at 2560px. CSS and
  `studioLayout`/`wideLayout` in `app.js` must stay aligned.
- Shared controls move between layouts without duplication. Compact section
  preferences survive desktop forcing panels open, resizing and reloads. Desktop
  live progress and Cancel stay in the header; Generate stays beside the prompts.
  Selecting a bottom-gallery image scrolls its preview/actions into view.
- Generate's backdrop uses actual per-stage sampling progress; loading/queueing
  remain indeterminate, reconnect pauses it, completion resets it. Disclosures
  animate open/closed with reversal/keyboard support; reduced motion disables
  effects. Native select menus retain browser/OS behavior. Shell cache refreshed.

### Workflow and generation controls

- Picker lists live ComfyUI files first, manual imports separately; retained folder
  snapshots/internal action presets do not clutter normal choices. Explicit
  image/history reuse can show one Current saved settings entry. Offline copies
  are deduplicated; refresh preserves selection/drafts and deletes no presets.
- Generic, versioned control discovery adds missing model, resolution and
  generation mappings to old presets while retaining keys, roles and drafts.
  Explicit later mapping saves suppress repeated additions on normal loads;
  refreshing model/node choices can rediscover controls. Existing Advanced
  fields use presentation roles to appear in the appropriate panel. Only actual
  literal inputs are mapped; connected sampler/noise/scheduler inputs stay linked.
- Generation panel order: Steps/CFG, Sampler/Scheduler, Seed, random toggle plus
  Reuse last seed, Batch count/size. Randomization is normally on; switching it
  off allows a fixed seed. Reuse last seed copies exact seeds from the latest
  matching completed job in this browser without replacing prompt/settings edits.
- Batch count defaults to 1, persists in the draft, and queues 1–20 normal jobs
  within the existing global 20-unfinished-job cap. Batch size is the workflow's
  images-per-run input. Group/member UUIDs and pre-request journals prevent
  duplicate queueing on retry/restart. Validate all runs before submission; stop
  on uncertain/rejected responses or output changes and report partial batches.
  Never blindly submit their remainder. Random mode picks a seed per run; fixed
  mode retains the same seed and may produce cached results. Whole image/job
  settings reuse resets count to 1; seed-only reuse preserves it.
- Progress follows active batch members; History lists each. Batch cancellation
  reuses safe per-job cancellation with owner/output checks, queued members first.
  Unsupported running cancellation never falls back to global `/interrupt`.
- User identified VeryComfy's ControlAltAI `FluxResolutionNode`, node 59,
  version 1.1.4, saved at 2.0 MP / 2:3 portrait, linked to EmptySD3LatentImage.
  **Those installed settings are user-reported; the live workflow is not here.**
  Upstream source inspection showed string dropdowns for MP/rounding, a boolean
  custom-ratio switch and aspect-ratio choices. Code now retains native types,
  runtime choices and linked dimensions; MP/aspect controls appear first.
- Earlier screenshots with only Batch size used a stripped-down fixture without
  sampler/seed inputs, not the actual VeryComfy graph. Do not diagnose them as a
  blanket control-removal regression. A separate old-preset discovery gap was fixed.

### Gallery, favourites and selected-image actions

- Hearts are the only Favourites UI, replacing visible Keep/Kept terminology;
  existing `keep`/`kept` API fields and private sidecar marks remain compatible.
  History and Favourites have separate shortcuts. Prompt History retains search,
  reuse and deletion; prompt stars/filter UI are gone, legacy records/flags retained.
- Refresh icons attach to workflow and first model selectors. Broom requests
  idle-only VRAM cleanup after the server checks the entire ComfyUI queue.
  LoRA replacement updates the slot label/enabled state without disturbing others.
- Gallery retains comparison, History, Favourites, recoverable Trash/Restore,
  image Details/Copy prompt and settings reuse. Wide preview integrates viewer
  tools; phone uses a dialog. Metadata-sharing opt-in does not share live jobs,
  cancellation or prompt history. Originals remain untouched.
- Edit/Upscale use user-named saved workflows through the existing upload,
  mapping, journal, progress and reconnect paths. Input copies strip PNG metadata
  and remain in ComfyUI input storage; no automatic cleanup was added.

| Action | Saved workflow stem | Verified code/fixture binding |
| --- | --- | --- |
| Edit | `VeryComfy_Qwen21_Turbo_EDIT_ONLY` | `88.image` LoadImage; `89.prompt` TextEncodeQwenImage21; retain `images.image_1: ["88", 0]`. |
| Upscale | `OfficialComfy-SeedVR_Upscaler` | `1.image` LoadImage; optional unique `scale_multiplier` or `resize_type.multiplier` in scale-by-multiplier mode. |

- Saved editor settings take precedence over stale API companions; use a matching
  executable snapshot or metadata-validated conversion, then companion fallback.
  Converter handles declared IMAGEUPLOAD markers, V3 dynamic inputs, bounded
  namespaced subgraphs/promoted widgets, socketless ImageCompare and native notes.
  Unknown/ambiguous serialization still fails closed with export instructions.
- Redacted supplied fixtures retain important differences: Qwen editor preserves
  `90.model: ["99", 0]`, absent from its API example; SeedVR parent instance is
  3× while definition/API is 4×. Do not treat those examples as interchangeable.
- Standalone demo mode, its CLI flags/module/tests/docs were removed at the user's
  request. Desktop and configured SSH startup remain; `--start-webui` still needs
  saved configuration. Uninstall work remains separate and deferred.

## Relevant changes and entry points

Recent feature commits, newest first:

| Commit | Completed work |
| --- | --- |
| `a80cf6c` | Generation discovery, seed-only reuse, batch count/size and safe grouped jobs. |
| `2ad504b` | Native resolution dropdowns and legacy calculator-control discovery. |
| `8665823` | Forge-inspired desktop arrangement; preserve compact state. |
| `b8b29dc`, `12de7d0` | Image-heart Favourites, remove prompt-star UI, compact utility icons. |
| `c194a20` | Workflow catalog/snapshot separation. |
| `97be024` | Progress backdrop and disclosure motion; its three-column sizing was superseded. |
| `671e23d` | Remove temporary demo. |

Primary files changed during this session:

- `mobile/{workflows,service,server,image_actions}.py` under `comfyui_control/`:
  control discovery/validation, persisted batch requests/cancellation, catalog flags.
- `mobile/web/{app.js,index.html,style.css,sw.js,image_actions.js,prompt_history.js}`:
  layout, seed/batch UI, image hearts, history and cached shell.
- `comfyui_control/cli.py`; removed `mobile/demo.py`, `tests/test_demo_webui.py`
  and `tests/manual/mobile_demo_browser.py`.
- Added `tests/test_{generation,resolution}_controls.py` and corresponding
  `tests/manual/mobile_{generation,resolution}_browser.py`; updated workflow-source,
  image-reuse and responsive/extras/workflow browser coverage.
- `README.md`, `docs/{RESPONSIVE_WEBUI,IMAGE_WORKFLOW_INTEGRATION,MOBILE,
  MOBILE_ARCHITECTURE,SSH}.md`, plus these root guidance documents.
- Earlier converter integration lives in `mobile/{workflow_sources,editor_subgraphs,
  input_metadata,image_pixels}.py`, `tests/test_editor_workflow_compatibility.py`,
  `tests/fixtures/workflow_conversion/` and `docs/IMAGE_WORKFLOW_INTEGRATION.md`.

## Verification evidence and limits

**Completed earlier this session on the current application code:**

- **125 focused tests passed**: 90 covering generation/resolution controls, mobile
  core/integration, workflow/editor compatibility, image actions/details/sharing,
  prompt history; 35 covering preparation/statistics/LoRAs/UI/image reuse/actions.
  One known old-job Upscale fixture test was explicitly deselected from the latter.
- Chromium and Linux WebKit generation-panel and responsive/reconnect checks
  passed: native choices, legacy mappings/drafts, 64-bit fixed/random/reused seeds,
  count/size queueing, reload, per-batch progress, scoped cancellation, phone/tablet/
  ultrawide layouts, hearts, reuse, privacy and motion. Chromium supplied-editor
  Edit/Upscale browser check also passed. Earlier resolution/catalog/extras checks
  passed in both engines. JS syntax and whitespace checks passed.
- Full suite was last run after demo removal, before later UI/batch work:
  **409 passed, 1 failed**. Do not present that as a full-suite result for HEAD.

**Rechecked during this documentation-only review:**

- GitHub/local branch state, current source, metadata versions and artifact paths.
- The isolated failing test still fails at HEAD:
  `tests/test_image_workflows.py::test_old_action_preset_and_jobs_are_retained_when_multiplier_mapping_is_added`.
  Its old-preset comparison passes; background reconciliation adds
  `seconds_per_iteration: None` to the synthetic old job, breaking exact equality.
  The same failure was reproduced earlier on untouched `a2eade7`; it was not fixed.
- Broad application/browser suites were not rerun during this document review.
  Final document whitespace/scope checks are separate from application tests.

Protocol fixtures are **not** proof of GPU inference, installed-node compatibility,
physical iOS, VPN or real NAS operations. The user confirmed Upscaling worked and
likes the phone UI; actual Editing and the newest controls/batches remain to test.

Current workspace artifacts (verified present, not committed):
`/workspace/generation-controls-{chromium,webkit}-v2`,
`/workspace/generation-regression-{chromium,webkit}-v1`,
`/workspace/generation-editors-chromium-v1`,
`/workspace/resolution-controls-{chromium,webkit}-v2`.
Earlier screenshots use protocol placeholders; do not call them real user outputs.

## Outstanding work — recommended order

1. On the user's configured machine, test the actual VeryComfy workflow: confirm
   CFG/Sampler/Scheduler/Seed mappings and saved resolution choices, generate,
   reuse the exact completed seed without replacing an unsent prompt, then test
   count versus size, cancellation, reload and phone lock/VPN recovery. Check both
   phone and desktop appearance. Obtain the current graph/metadata if controls are
   absent; never fabricate inputs or replace the pipeline to satisfy a screenshot.
2. Verify real selected-image Editing, original preservation and GGUF/cache wiring.
   Upscaling was user-confirmed earlier; retest it after current queue changes and
   verify blank/default and fractional multipliers. Preserve the editor's settings.
3. Resolve the reproducible old-job fixture equality failure when authorized, then
   run the full suite before a release. Determine the correct compatibility
   assertion without removing legitimate job timing normalization.
4. Exercise actual NAS fallback/gallery/Trash/Restore and ownership/sharing on this
   branch. Agent tests have not verified real NAS or physical Apple hardware.
5. Uninstall remains deferred. The branch is separate; integrate/revalidate only
   when requested. Inpainting/Mask by Touch was superseded, not a pending approved
   feature. Gradio was discussed; no migration was requested or implemented.
6. Only for a separately authorized release: reconcile Python/spec version/Release,
   stale guides/screenshots/downloads, test, merge/tag/build via maintenance guides.
   `docs/RESPONSIVE_WEBUI.md` still mentions only `scale_multiplier` in its later
   action summary; the integration guide/code also support `resize_type.multiplier`.

## Running checks in a fresh environment

- Use repo `.venv/bin/python`; `.venv` and `/workspace/.playwright-browsers` exist
  here, but may not survive replacement. Setup commands are in `AGENTS.md`.
- Current browser commands use `QT_QPA_PLATFORM=offscreen`,
  `XDG_CACHE_HOME=/tmp/comfy-workspace-cache`,
  `PLAYWRIGHT_BROWSERS_PATH=/workspace/.playwright-browsers` and a fresh output dir:
  `.venv/bin/python tests/manual/mobile_generation_browser.py --browser chromium --output /tmp/control-generation-check`.
  Use the analogous resolution/responsive/saved-editors scripts as relevant.
- Linux WebKit required extracted OS libraries under `/tmp/comfy-browser-libs`
  linked into the downloaded browser bundle; `PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1`
  only bypasses validation, not missing libraries. Recreate dependencies if needed.
- Managed sandbox runs of loopback/browser and asyncio thread-wakeup tests may
  require tool network permission. A restricted generation-test run hung; its
  permitted rerun passed. Do not misdiagnose this as a product failure.
- The user's original uploaded workflows/live installation are not in this
  checkout. Use committed redacted fixtures for portable checks. No supported
  cloud preview URL or production deployment is established here.
