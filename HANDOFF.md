# Session handoff — 2026-10-21

## Current update: independent presentation layers

- Active work branch: `testing/webui-presentation-layers`, created from pushed
  `testing/webui-workspace` commit `cddb86b`. Use Git for the final commit/ref;
  the older branch/application descriptions below are historical context.
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

Verification on this refactor:

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

Current uncommitted artifacts are under `/tmp/presentation-*`, including the
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
