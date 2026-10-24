# Session handoff — 2026-10-24

## Phone modernization testing branch

Branch: `testing/phone-ui-modernization`, created from the freshly cloned latest
main `2fb6352`. Changes are for review/testing only; no main merge, version bump,
tag, release rebuild or publish is authorized by this session. The previous
release handoff below remains historical context.

Read `docs/PHONE_UI.md` for the Desktop-to-Phone behavior mapping, architecture,
verification commands and remaining device checks. The existing Phone UI now has
shared Heart/Edit/Upscale/virtual Delete controls in completed results and the
viewer, plus a separate Compare button that preserves New variation. Workflow,
model and Gallery refresh icons, idle-only VRAM cleanup, prompt chevrons, compact
labelled LoRA strength rows and live step metrics match Desktop's vocabulary.
Touch controls, square scrolling Compare rows and flexible Save image navigation
fit narrow portrait/landscape screens.

Phone retains its tabs, fixed Generate/job dock, live preview, inline prompts,
native collapsing sections/negative prompt, history/favourites, seed hint, original
slider bounds, exact reuse, swipe/navigation and details. The viewer now hides
its filename and iPhone instructions and places Details below all action rows.
One shared component and placement helper serve both presentations; there is no
second state store, request/submission implementation or new polling. Action forms
close on Desktop breakpoint transitions. Shared stale-response, permissions,
confirmation and UUID retry behavior remain authoritative. No ComfyUI installation
or real user configuration was touched.

Phone styles are isolated in `presentation_phone.css`; the shared `style.css`,
Desktop stylesheet and 1000×600 breakpoint are unchanged. The public-asset allowlist
and service-worker shell include the new stylesheet, with cache
`comfy-control-mobile-phone-actions-3`. Private APIs/images remain uncached.

Verification completed:

- **431 pytest tests passed**, including optional Node shared-component checks.
- **16 browser runs passed**: Phone image actions plus Desktop image actions,
  responsive layout/reconnect/privacy/reuse, Generate feedback, refresh stability,
  bypassed LoRAs, saved-workflow picker and generation transitions, each in Chromium
  and WebKit. Phone uses touch input at 320×568, 390×844, 430×932, 768×1024 and
  844×390, plus Desktop transitions. Checks include real Edit/Upscale protocol
  submissions, pixel/parameter targeting, exact 64-bit seeds, uncertain UUID retry,
  draft preservation, Favourites, cancelled/confirmed virtual deletion and offline
  action disabling. Phone picker also covers short-screen scrolling and late
  responses after cancel; shared Desktop checks cover decoding/reduced motion.
- `git diff --check` passed. Phone screenshots were visually inspected in both
  engines. Historical assertions forbidding Phone controls were updated narrowly;
  frozen shared-asset and Desktop geometry checks remain active.

Tests used this checkout's `.venv` and isolated loopback protocol fixtures. Browser
downloads, compatibility libraries, logs and screenshots are session work assets,
not repository/runtime dependencies. The host needed session-local ICU/JPEG
libraries for WebKit; no system installation was changed. Fresh output directories
were used. Real GPU inference, physical Phone/keyboard/safe-area behavior, NAS/VPN
and custom-node compatibility still require hands-on testing before merge.

## Phone viewer review follow-up

The user requested hiding the filename and iPhone instructions and moving Details
to the bottom of the Phone viewer. Phone-scoped CSS hides the prose/header text;
the existing placement helper moves the original Details node after the action
rows so keyboard order matches visual order. Desktop restores the original DOM
placement. The service-worker shell was bumped to `phone-actions-2`. Phone and
Desktop action checks passed in Chromium and WebKit (four browser runs), along
with all three focused presentation-boundary tests and `git diff --check`.

## Phone Create results review follow-up

Phone Create now places the existing `job-output` section before the workflow
form. Completed results use the title `Preview & results` and hide the workflow
filename line. The original nodes, selected image, controls and handlers are reused.
Active jobs remain in the fixed dock; failure/unknown-job diagnostics are preserved.
Desktop restores the original output anchor and completed title. The service-worker
shell was bumped to `phone-actions-3`.

The Phone viewer now overlays Close at the image's top-right corner and uses a
viewport-height flex layout. The image fits the space remaining around the touch
controls; short landscape screens use single-row action grids. Details stays at
the bottom, with internal scrolling for expanded metadata. Diagnostic messages
also have bounded internal scroll areas instead of forcing whole-viewer scroll.

Verification: Phone/Desktop actions, responsive behavior and generation transitions
passed in both Chromium and WebKit (eight browser runs). All three focused
presentation-boundary tests and `git diff --check` passed. Phone checks assert
result order/title, hidden filename, top-right overlay bounds, visible touch controls
and no dialog overflow at all five portrait/tablet/landscape sizes. Screenshots
were visually inspected. Physical-device checks remain outstanding.

## Previous release handoff — 2026-10-23

## Release baseline and next session

This session's reviewed changes are **published as 1.0.4** on main.

- Testing/source branch `testing/ui-flicker-fixes` was pushed at `6cd5439`.
- Main merge/release commit: `493be93dc4358dd52d9c72bfc8568b1d42a2fdc5`.
- Annotated release tag: `v1.0.4`, pointing to that merge commit.
- GitHub build: https://github.com/jhakuzi/comfyui-control/actions/runs/40021478842
- COPR build: https://copr.fedorainfracloud.org/coprs/jhakuzi/comfyui-control/build/11199608/
  Package `comfyui-control-1.0.4-1`, chroot `fedora-44-x86_64`.

The user approved this push/merge/release and the handoff update. GitHub Actions
run **40021478842 completed successfully**, including the Fedora RPM build/tests.
COPR build **11199608 succeeded**, publishing **1.0.4-1** for Fedora 44 x86_64.
All release work requested in this session is complete; linked build pages remain
the source of truth for historical checks. No automatic monitoring was scheduled.
A documentation-only follow-up records the release after the tagged merge. A fresh
clone of `v1.0.4` and the exported ZIP both report `ComfyUI Control 1.0.4`.

The tag triggers `.github/workflows/copr.yml`: source RPM/app ZIP, Fedora RPM
build/tests, then COPR submission and build result. Inspect actual Git history,
remote refs and checks before any further release work. This approval applies to
this release only, not future version bumps or publishes.

Repository: https://github.com/jhakuzi/comfyui-control
Local development checkout used here:
`/home/jhaku/Downloads/Testing/comfyui-control-integration-testing`.
This is distinct from the chat's projectless Documents directory and the older
blue-themed `comfyui-control-presentation-testing` checkout. Use the actual Git
checkout, read `AGENTS.md`, and inspect branch/status before editing. Normal work
continues on main or a user-requested testing branch, one requested feature at a
time. Do not treat past approval as authorization for future releases.

## Changes completed in this session

### Shared application/backend

- Model refresh now reconciles option lists in place when graph/control signatures
  are unchanged. Controls, icon refresh buttons, handlers, live drafts, mapping
  edits, focus, text selection, scroll and 64-bit seed strings survive. Missing
  current choices remain available as saved unavailable values. Structural changes
  rebuild atomically from the response, without a second fetch; stale responses
  cannot resurrect old workflows. Saved-workflow refresh preserves its optgroup
  while awaiting a response and after failures. Preview height writes are deduped.
- Workflow picker now shows only saved files from ComfyUI's workflows directory,
  including nested names, plus one top `Reused image` entry after settings reuse.
  New reuse replaces that entry; choosing a saved workflow clears it. Reload keeps
  the appropriate selection/draft. Old/internal preset snapshots are retained for
  jobs/actions but are hidden from the menu. Removing a selected saved file clears
  its form safely. Backend descriptions expose `comfy_source`.
- Saved-editor import retains metadata-recognized active/bypassed LoRA loaders
  with unambiguous MODEL/CLIP passthrough links. All configured nodes remain in
  controls; unchecked means true bypass and checked means active. Saved model and
  strength values remain unchanged. `_meta.control_lora` marks routes/defaults;
  submitted graphs recursively bypass disabled nodes and strip this private marker.
  Legacy unmarked presets keep their earlier zero-strength disabling semantics.
  Exact queued snapshots preserve opaque custom widgets. Unknown/muted nodes are
  not guessed. Descriptions expose `default_disabled_loras`, used by new drafts.
- Existing shared queue, security/privacy, API, image-action journal and backend
  remain authoritative. No new app/frontend framework or ComfyUI extension.

### Desktop presentation

- Baseline retained from 1.0.3: equal-width columns share the tab bar's outer edges,
  centered 28px gap; main preview height tracks the first workflow card; Resolution
  and Advanced sit below Preview; last completed image remains during generation.
- Header live metrics are a compact themed row (existing s/it speed, VRAM, GPU,
  current/total steps). Blue native bar/workflow name were removed from the header.
  A matching `Reconnecting...` badge is shown during disconnection; existing right
  connection badge stays. Duplicate form/offline card and Preview missing-workflow
  prose are hidden on Desktop. Tooltips, action availability and errors remain.
- Gallery refresh uses the same icon as model refresh. Main prompt has a centered
  chevron and a broom for the existing idle-only VRAM action, with labels/tooltips.
  Cleanup refuses busy queues. The user declined changing any ComfyUI installation;
  `/free` timing remains server-controlled. No external patch was applied.
- LoRA rows are compact; redundant visual selector/strength labels are hidden but
  accessible names remain. Slider bounds are -2..2 on Desktop, restored on Phone;
  numeric input limits and saved values are unchanged.
- LoRAs, Generation settings, Resolution and Advanced open upward with shadows,
  bounded internal scrolling and no summary/column movement. Arrows point upward
  when open and rotate within fixed-width slots to prevent text movement.
- Desktop prompt history is hidden. Negative prompt opens by default and now has
  the same icon-only expansion behavior as the main editor, with the native summary
  arrow hidden. Both expand downward as shadowed overlays ending at the main left
  workflow card's bottom border. Flow rows and column positions stay fixed; shared
  expansion state/callbacks are reused, and Phone DOM/open state is restored.
- Fixed-seed explanation was first stabilized, then removed entirely on Desktop
  at the user's request, including reserved space. Phone retains its original hint.
- Removed the transient Phone submission card on Desktop Create: it exposed a blue
  native progress bar and squeezed the preview before acknowledgement. Normal
  queued/preparing/sampling/processing feedback no longer reserves 88px above the
  image. Preview dimensions stay fixed; Cancel sits beside Preview & Results.
  Failure/unknown-job diagnostics still have space. Phone status/dock is unchanged.
- Compare replaces New variation in both Desktop Preview and enlarged viewer.
  A modal, panel-sized gallery excludes the first selected image, accepts one
  additional image and opens the existing comparison window without changing drafts
  or generating. Empty/error/cancel/stale-response cases are handled. In the enlarged
  view it centers over Compare and its bottom meets Upscale/Delete, clamped to the
  viewport. Normal Preview picker placement is unchanged. Viewer filename and
  iPhone/swipe guidance are hidden only on Desktop.
- Picker rows use max-content heights to prevent thumbnail overlap. Thumbnail images
  retain alt labels but stay hidden until decoded, with small yellow loading rings;
  original-image fallback and reduced motion are supported. No artificial waits.
- Dependent ResizeObserver writes are frame-batched to avoid WebKit feedback loops.
  Desktop additions are reversible on breakpoint transitions; Phone keeps history,
  native negative details, New variation, filename/instructions and original sliders.

## Verification and limitations

Release preparation passed **431 pytest tests** without temporary plugins. The
local-fallback fixture now uses a reserved non-listening loopback endpoint, so it
cannot read images from the user's independently running ComfyUI. Historical counts
are not a substitute for fresh checks after future changes.

Final release checks passed all **14 browser runs** (seven scripts in Chromium
and WebKit) for in-place refresh, bypassed LoRAs,
saved-only workflow menu, image actions, Compare picker/selection/retry/cancel,
multiple thumbnail rows, delayed loading/decoding/reduced motion, exact heading and
picker alignment, Desktop/Phone transitions, stable generation frames, and expanded
positive/negative editor borders at 1000/1440/1920px widths. Numeric seeds remain
exact. Browser fixtures exercise actual shared HTTP APIs/protocol stubs, not GPU
inference, physical Phone hardware, NAS/VPN or actual Qwen/SeedVR model execution.

Use this checkout's `.venv-test` if present, or create `.venv` as in AGENTS.md.
Optional pytest/Playwright/browser dependencies for this session were kept under
`/home/jhaku/Documents/Codex/2026-10-22/i-m-continuing-development-of-comfyui-3/work`;
those caches/screenshots are not repo dependencies. New sessions should install
normal test dependencies rather than assume those absolute paths exist.

Focused scripts in `tests/manual/`:
- `refresh_stability_browser.py`: DOM/drafts/focus/scroll/catalogue/structural/stale
  refresh checks plus prompt overlay alignment and Phone restoration.
- `bypassed_loras_browser.py`: five optional nodes, saved defaults, true bypass,
  activation/submission, compact Desktop controls and slider/Phone restoration.
- `saved_workflow_picker_browser.py`: no duplicates, reuse entry replacement,
  reload/draft stability, failures and selected-file removal.
- `generate_transition_browser.py`: held first/repeated submissions, no native
  Desktop progress, stable preview through all normal phases, last completed image,
  Cancel/Phone status and retained failure diagnostics.
- `desktop_image_actions_browser.py`, `mobile_responsive_browser.py`: shared actions,
  comparison picker, responsive layout, privacy, reconnect and exact settings reuse.

## Known scope limits and release operations

- Existing imported snapshots cannot recreate bypassed nodes absent from their API
  graph. Reselect the saved VeryComfy workflow once to reimport its editor graph.
- API-only graphs/ambiguous custom serialization remain fail-closed. Named Edit and
  Upscale workflows still require saved `VeryComfy_Qwen21_Turbo_EDIT_ONLY` and
  `OfficialComfy-SeedVR_Upscaler` files. No graph pipeline was invented.
- Backend interruption still reports failed; queued cancellation reports cancelled.
  No queue redesign, Phone action UI, or Wastebin management UI was added.
- Do not touch ComfyUI installations, restart servers or install cleanup extensions.
  A proposed external queue patch was declined and is not part of this repository.
- Version must agree in pyproject, __init__, spec and tag. Versioned app ZIPs are ignored; keep versioned SRPM build outputs out of commits.
  Stable `downloads/comfyui-control.zip` and `.src.rpm` are rebuilt for release. The frozen presentation fixture's version-file hashes must
  track authorized version bumps; do not reset unrelated protected assets.
- Previous 1.0.3 Actions run `39844702309` and COPR `11194472` succeeded. Local COPR
  credentials were expired; release-tag Actions secrets handled publishing. Never
  print credentials. SSH Git transport worked; the origin URL remains HTTPS.
- Public Actions APIs/connector tools can inspect release checks. On a failure,
  inspect diagnostics, fix the cause and use a new version rather than moving tags.
