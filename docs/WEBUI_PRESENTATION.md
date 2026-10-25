# Shared WebUI and Desktop presentation (1.0.4)

The integration branch keeps main's yellow theme and original responsive layout.
It does not load Forge's presentation coordinator, adapters, theme or layout.
The existing `(min-width: 1000px) and (min-height: 600px)` media query remains the
desktop boundary. Phone, tablet portrait and short-window behavior stay on main's
existing presentation.

## Current presentation

Desktop uses equal-width columns, fixed last-result previews, a themed live header,
upward section overlays and panel-aligned prompt/negative-prompt overlays. Compare
in Preview and the enlarged viewer opens the shared second-image picker and existing
comparison dialog. VRAM cleanup uses the existing idle-only API; ComfyUI itself is
unchanged. Phone exposes shared saved-image actions and Compare with touch controls,
retaining its tabs, dock, native details and New variation. See
[PHONE_UI.md](PHONE_UI.md) and [HANDOFF.md](../HANDOFF.md)
for the complete current behavior, shared refresh/picker/LoRA changes and limitations.

## Responsibilities

| File | Responsibility |
| --- | --- |
| `mobile/web/style.css` | Unchanged main theme, component skins and responsive layout. |
| `mobile/web/presentation_desktop.css` | Desktop arrangement, overlays, controls and selected-image indication; every selector is scoped to `:where(html[data-presentation="desktop"])`. |
| `mobile/web/presentation_desktop.js` | Placement and desktop label changes only. Restores original nodes/labels on leaving desktop. No requests, workflow logic or application store. |
| `mobile/web/presentation_phone.css` | Phone touch targets, compact selectors, inline LoRA strength controls, action grids and bounded comparison picker. |
| `mobile/web/app.js` | Shared selection, requests, generation state, pending journal, settings reuse and reconnect. |
| `mobile/web/feature_image_actions.js` | Existing selected-image actions, confirmed heart state, capabilities, version/permission checks, pending/error rendering and stale-response guards. |
| `mobile/web/feature_image_api.js` | Existing image-workflow transport, using the same pending UUID journal and generation submission controller. |
| `mobile/web/feature_image_workflows.js` | Shared Edit/Upscale dialog behavior, adapted from the existing forms without Forge styling. |
| `mobile/web/feature_gallery_library.js/css` | Shared toolbar, collection dialogs and heart indicators; transport/selection remain supplied by the controller. |

One action row contains Heart, Edit, Upscale and Delete. It sits above the existing
Reuse settings / Compare row beneath the desktop result. The two rows stay
outside the scrolling image area so actions and Generate remain reachable. The
adapter records return anchors for the original nodes. Switching to Phone closes
action forms, hides desktop additions, restores the reuse row's original parent
and restores its Same seed / New variation labels and existing interactions.

The existing `same-seed`, `variation`, `reuse-image`, `vary-image` IDs and listeners
are retained. Desktop Preview reuse resolves the selected image and uses the same
full settings reuse path as the saved-image viewer, including exact seed strings,
mapping validation and explanatory errors. Reuse loads/validates metadata before
applying a settings snapshot; navigation invalidates stale results. It never starts
generation. Opening or cancelling an Edit/Upscale form leaves the generation form,
selected workflow, draft and job untouched.

The same four action controls move into the existing image viewer while it is
open, following its existing navigation and current image. They return to Preview
on close. No second set of controls, navigation listeners or selection persistence
is created. A thin accent outline identifies the selected desktop result when
there are multiple outputs. It is removed on Phone.

Components are mounted lazily after authentication and reused on both presentations.
Phone exposes them for completed results and the explicit image viewer.
Capability refreshes follow selection, confirmed
mutations, gallery refresh and existing connection events, with no new polling.
Disconnected/hidden pages invalidate pending reads and display disabled actions
without starting requests. Actual workflow submissions use the same busy state,
idempotent UUID, reconnect reconciliation and Generate retry path as generation.

Delete uses the existing confirmation and virtual Wastebin endpoint. It marks
metadata and removes that image from the current collections; originals stay in
place. Gallery now has Wastebin and Favourites preview dialogs beside Refresh,
with a heart indicator on marked thumbnails. See
[GALLERY_COLLECTIONS.md](GALLERY_COLLECTIONS.md). Wastebin browsing reads private
thumbnails. Clear Bin now permanently deletes a confirmed displayed snapshot,
retaining failures and newer entries. Desktop/Phone sessions share library marks
and bin contents within the controller/output scope; live jobs and history retain
their browser boundaries. Desktop collection popups are larger and avoid transient
loading/saving layout shifts. The shared collection guide records the full contract.

## Verification

Phone modernization intentionally supersedes the historical pixel-identical Phone
requirement below. Keep the frozen shared assets and Desktop geometry checks;
use `phone_image_actions_browser.py` for the authorized Phone changes. The older
baseline comparison remains useful only when inspecting unchanged regions.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/desktop_image_actions_browser.py --browser chromium --output /tmp/desktop-image-actions
.venv/bin/python tests/manual/mobile_responsive_browser.py --browser chromium --output /tmp/desktop-actions-responsive
mkdir -p /tmp/desktop-actions-baseline
git archive 3bbea58 | tar -x -C /tmp/desktop-actions-baseline
.venv/bin/python tests/manual/main_feature_port_browser.py --browser chromium --phone-only --baseline-root /tmp/desktop-actions-baseline --output /tmp/desktop-actions-phone-parity
.venv/bin/python tests/manual/mobile_generate_button_browser.py --browser chromium --output /tmp/desktop-actions-generate
```

Repeat with WebKit and fresh output directories. Phone comparison covers create,
gallery, running and completed results after desktop transitions at 390×844,
430×932, 768×1024 and 844×390. The desktop fixture exercises different images,
favourite persistence and delayed responses, exact full reuse, cancellation,
missing workflows, API failures, actual Edit/Upscale submissions, uncertain retry
and virtual Delete. These are protocol and local filesystem fixtures, not real
Qwen/SeedVR inference, NAS hardware or physical Phone verification.

## Desktop Gallery multi-selection

`feature_gallery_bulk.js` adds only transient Desktop selection and coordinates
with the existing Compare mode. Requests and confirmed-result updates remain in
`app.js` and use the current per-image API. Its layout/checkmarks are scoped in
`presentation_desktop.css`; Phone retains its original Gallery comparison row.
`feature_image_confirm.js` supplies a shared native dialog styled within the app
for single/bulk Delete and Clear Bin, including Cancel/Escape and stale guards.

Verify `tests/manual/desktop_gallery_bulk_browser.py` in Chromium and WebKit,
alongside Desktop/Phone actions and collection/shared-library fixtures.
