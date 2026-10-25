# Session handoff — 2026-10-24

## Desktop selection context menu follow-up — 2026-10-25

The user requested replacing the permanent Favourite selected/Delete selected
buttons with a right-click menu. The same bulk action handlers now live in a
Desktop-only menu on selected Gallery thumbnails; the count and a short hint stay
above the grid. Unselected images and Phone retain their native context menus.
The custom menu applies to the entire current selection, stays within viewport
bounds and supports Shift+F10/ContextMenu, arrows, Home/End, Escape and Tab.
Outside clicks, scrolling, resize, selection pruning and lifecycle resets dismiss
it. Delete still uses the existing in-app confirmation and exact-version snapshot.
No backend changes or action semantics were added. Shell cache is
`comfy-control-desktop-gallery-bulk-3`.

Verification: 440 pytest tests passed; the bulk real-API browser fixture passed
in Chromium and WebKit, including right-click/keyboard focus and dismissal,
viewport-edge positioning, no toolbar buttons, bulk actions/partial failures,
unknown replies, stale versions, Compare, Phone and preserved drafts.

## Desktop Gallery and Bin follow-up — 2026-10-25

New local branch `testing/desktop-gallery-bulk` starts from main `59fe52f` after
1.0.5. This addition is for testing; no new merge, release or COPR build is part
of this request.

Desktop splits the old Select two images footprint into that button and Select,
with Compare retaining the other half. Select supports more than two images,
checkmarks/count, Favourite selected and Delete selected. Compare selection is
mutually exclusive. Existing image-action POSTs run serially with exact selected
versions, current permissions, explicit keep:true and one confirmed Delete
snapshot. Confirmed results reconcile through `imageActionChanged`; failures stay
selected. Uncertain replies stop the batch without automatic retry. Navigation,
authentication, backgrounding and leaving Desktop stop further batch requests.
Refresh prunes removed/replaced versions. Drafts/jobs remain in the controller;
selection is transient and never persisted. Phone's Gallery layout/Compare remains
unchanged.

One shared themed alertdialog replaces browser confirm for single Delete, bulk
Delete and Clear Bin on both presentations. Cancel/Escape sends nothing; focus
starts on Cancel; stale selections/dialogs cannot authorize later actions. New
assets are allowlisted and shell cache is `comfy-control-desktop-gallery-bulk-2`.

The user's Clear Bin error was reproduced with an original removed outside the
app. Explicit clearing can now finish an already-missing leaf only after matching
and rechecking the saved root/parent identity chain. No replacement is unlinked;
missing/changed mounts or parents, permissions, symlinks and ownership still fail
closed. Tombstones prevent replay. Unavailable Bin previews show the filename
and explanatory copy; images absent from storage cannot have a preview rebuilt.
No real user files or Bin entries were removed during this work.

Verification: 440 pytest tests and ten browser script/engine checks passed in
Chromium/WebKit (new bulk/missing-file fixture, shared-library updates, Desktop
and Phone image actions, collection previews). Tests cover >2 selection, idempotent
favourites, cancellation, partial permission failures, duplicate guards, changed
versions, lost replies, navigation, drafts, Phone layout and confirmed missing-file
cleanup. Use `tests/manual/desktop_gallery_bulk_browser.py` for the new fixture.
Restart the testing app for the backend fix and reload both WebUI pages.

## Authorized 1.0.5 release

The user authorized pushing the testing branch, merging to main and building COPR.
This supersedes the earlier testing-only restriction below. Version 1.0.5-1
packages the Phone modernization and shared Gallery library. Version hashes and
stable ZIP/source RPM downloads are refreshed for the release. The reported
Phone Gallery load delay remains unconfirmed and unchanged. Release checks passed: 437 pytest tests and six fresh Phone/Desktop/shared-library
browser checks across Chromium/WebKit.

Merged via PR #1 at `122346abc2b9b997cb799de84579023747c8e3cc`; tag `v1.0.5`
points to that merge. GitHub Actions run `40130379790` built/tested the Fedora RPM
and submitted COPR build `11203296`, which succeeded for Fedora 44 x86_64.
Version `1.0.5-1` is published. Downloads testing checkout was fast-forwarded to
release source `e3552fd` on its existing testing branch.

- PR: https://github.com/jhakuzi/comfyui-control/pull/1
- Actions: https://github.com/jhakuzi/comfyui-control/actions/runs/40130379790
- COPR: https://copr.fedorainfracloud.org/coprs/jhakuzi/comfyui-control/build/11203296/

Upgrade with `sudo dnf upgrade --refresh comfyui-control`, restart the app, then
reload Desktop/Phone. No GitHub release object was created; the tag, main download
ZIP/source RPM and COPR package were published.

## Phone Gallery copy follow-up

Phone hides the introductory “Recent images from ComfyUI output…” paragraph
using scoped presentation CSS. Desktop copy and the Gallery empty-state hint
remain unchanged. Shell cache is bumped to `gallery-library-3`.

## Phone modernization testing branch

Branch: `testing/phone-ui-modernization`, created from the freshly cloned latest
main `2fb6352`. Changes are for review/testing only; no main merge, version bump,
tag, release rebuild or publish is authorized by this session. The previous
release handoff below remains historical context.

Read `docs/GALLERY_COLLECTIONS.md` for the new shared Gallery collection views.
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
`comfy-control-mobile-gallery-library-2`. Private APIs/images remain uncached.

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

## Desktop and Phone Gallery collections

Gallery now has bin and heart icon buttons immediately after Refresh, using one
shared `feature_gallery_library.js/css` component. Both open bounded native
dialogs with square, scrolling thumbnail rows using the existing `renderImages`
and decoded/reduced-motion thumbnail handling. Favourites opens the shared image
viewer/actions. Wastebin uses the existing private list/thumbnail API and can show
a larger thumbnail with its filename and stored error/notice; browsing performs
no restore or permanent deletion. No new polling, queue or selection store exists.

Main Gallery and Favourites tiles display small yellow hearts. Metadata changes
update badges in place without replacing image/button DOM. Confirmed mutations
invalidate older Gallery reads, preventing a delayed response from reversing a
heart. Popup close/tab/lifecycle/authentication guards ignore stale reads and clear
private grids on sign-in. Unmarking in Favourites safely advances/closes its viewer.

`GET /api/gallery?favourites=1` lists the requesting browser's exact-version marks,
including older files beyond the recent 200/ordinary retained 500. The existing
bounded local/network scan retains marked references across restarts and scans by
other browsers. Recent Gallery remains capped at 200; private marks, output scope,
permissions, corruption safeguards and scan/mark bounds stay authoritative.
Older favourites can still use full viewing/actions and Compare. Deleted entries
remain excluded from ordinary Gallery/Favourites and original files stay intact.

The new public JS/CSS are allowlisted and included in shell cache
`comfy-control-mobile-gallery-library-1`. Shared `style.css`, Desktop/Phone
arrangement styles, versions and release assets are unchanged. Restart a running
app for the Python query update, then reload both WebUI pages.

Verification: **434 pytest tests passed**, including new local/network cases for
older favourites beyond both limits, restart, browser isolation, replaced versions,
deleted exclusion and private thumbnail authorization. **12 browser runs passed**:
collection flow plus existing Desktop/Phone actions, responsive behavior, Gallery
synchronization and comparison, each in Chromium and WebKit. The new flow covers
five viewport sizes, live badges/DOM identity, empty/multiple rows, decoded previews,
private collections, stale Gallery/collection responses, error/retry, sign-in
clearing, preserved drafts/files and older-favourite viewing/Compare. Screenshots
were inspected. Physical Phone and actual NAS/GPU checks remain outside fixtures.

## Shared library, stable Desktop actions and Clear Bin follow-up

The user explicitly requested sharing hearts/bin contents across Desktop and Phone,
larger Desktop popups, removal of heart-click flicker and confirmed Clear Bin.
These changes supersede the browser-private image-library contracts above. The
controller has one WebUI access boundary/password; admitted clients now share
library metadata in the same output scope. Jobs, cancellation, prompt history,
optional image-settings sharing and initial per-image Delete ownership stay intact.

Existing version-2 sidecars remain compatible. Scans atomically merge validated
legacy marks into a shared output bucket, preserving other/stale records and
corruption safeguards. Unmarking removes old copies so they cannot resurrect a
heart. Bin records retain their original owner and identity; shared listing,
thumbnails, restore and confirmed permanent deletion still check output scope.
Legacy listing discovers original owners, and the worker uses those owners for
legacy reads/writes. Permanent deletion checks source ownership against the original
record, retaining all filesystem, symlink, replacement, root and NFS guards.

Reproduction measured a 15.5px movement in viewer controls from the temporary
“Saving…” row and a 41px popup-grid movement from loading prose. Both now measure
zero movement. Heart saves acknowledge the same capabilities without another GET;
read refreshes retain existing prose. Collection grid/status geometry is fixed,
with accessible busy state and no visible transient loading/empty text. Desktop
popups are up to 1200×900 with four columns; Phone retains two columns/bounds.
A cross-device test also found the Gallery revision remained stale after optimistic
metadata changes; invalidating it on confirmed edits fixes reversed device marks.

Clear Bin confirms the exact displayed token snapshot before calling the existing
permanent-delete transport. Cancel does nothing; new entries stay out; failed
entries retain errors. Duplicate actions are disabled. Confirmed results refresh
the list, and uncertain responses require a read refresh without automatic retry.
Only generated fixture files were permanently removed during verification.

The shell cache is `comfy-control-mobile-gallery-library-2`. Restart the app for
backend changes, then reload both WebUI pages. See `docs/GALLERY_COLLECTIONS.md`.

Verification completed: **437 pytest tests passed**, including authenticated
cross-device access, denied unauthenticated library/deletion routes, private
jobs/history, lossless legacy marks, original-owner changes, output/version guards,
legacy trash, local/network deletion and partial failures. **14 browser checks
passed**: collections, shared-library/Clear Bin updates, Desktop/Phone actions,
responsive behavior, Gallery synchronization and comparison in Chromium and WebKit.
The final update checks include a lost response after actual fixture deletion,
with read reconciliation and no automatic retry. `git diff --check` passed.
Screenshots and before/after geometry were inspected. No real user files, ComfyUI
installation, version, release artifact or system setting was modified by tests.

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
