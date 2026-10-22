# Main-based feature port (UI integration deferred)

Branch: `integration/main-feature-ports`. Base: main `7e500d9`. Feature source:
`testing/webui-desktop-forge` at `292f216`. No merge or wholesale commit cherry-pick
is used. This stage ports backend features and prepares unloaded client modules.
It does not add controls, dialogs, navigation, layout or styling to the live app.

## Presentation boundary

Every pre-existing file under `mobile/web/` is unchanged from main. This includes
HTML, application JS, CSS, prompt favourites, manifest and service worker. Main's
`--accent: #e7f67b`, phone/tablet/desktop breakpoints, tabs, dock, previews and
button geometry stay intact. The Qt desktop/settings UI and release versions are
also unchanged. No Forge presentation coordinator/adapters or theme are included.

Four new `web/feature_*` files are packaged as dormant components. They are absent
from `index.html`, the public asset allowlist and the service-worker shell; HTTP
requests cannot load them. Future UI integration requires a separate request.

- `feature_generate.js/css`: explicit progress state/paint helpers and an overlay
  using main's colors, without layout declarations. The future adapter supplies
  main's job/state, calls `update()` and `paint()` on the existing button, and
  schedules a refresh after the controller's feedback duration. No listener,
  timer, request or DOM change happens on script load. Reduced motion is supported.
- `feature_image_actions.js`: portable selected-image component with optional
  presentation callbacks, no `ComfyPresentation` dependency and no automatic mount.
- `feature_image_api.js`: workflow/VRAM/Wastebin transport. The future adapter
  must inject main's existing API, UUID generator and pending-submission journal
  callbacks. It creates no additional store. Uncertain/malformed responses retain
  the original action UUID for an idempotent retry; normal generation retry stays
  with main's existing controller.

## Backend features

Qwen Edit and SeedVR Upscale use named saved ComfyUI workflows, upload only a
metadata-free pixel copy, and preserve original files and unknown graph nodes,
links, models, GGUF/cache wiring and saved editor settings. Dynamic inputs,
bounded subgraphs, upload widgets, numeric metadata and API companion fallback
are supported by the shared importer/validation helpers. No model pipeline or
ComfyUI installation is bundled.

The existing single-job `submit()` journal, queue, ownership and reconnect path
remain authoritative. Only optional output-scope checks are added for action
preparation. Batch count, batch/queue cancellation redesigns, generation/resolution
control rediscovery and Forge's workflow picker are excluded. Internal action
presets are hidden by the existing preset-list API without changing its ordinary
entries or main's picker markup/JS. Internal presets still count toward the
existing storage cap and are reused between actions.

Favourites and virtual Delete/Wastebin reuse the image-library sidecar. Marking
an image changes metadata only; original files remain in place. Gallery/job image
responses hide marked versions. Restore removes the marker even while output
storage is offline. Confirmed permanent deletion uses the bounded worker with
configured-root, directory/file identity, no-follow path and owner/scope guards.
Partial failures keep their markers and error messages. Legacy moved Trash
entries remain supported. VRAM cleanup checks the complete upstream queue is idle
under the existing submission lock before requesting ComfyUI `/free`.

Cross-device metadata sharing already exists on main and is retained. Sharing
settings never grants another browser access to live jobs, cancellation, prompt
history or another browser's Wastebin/deletion permissions.

## APIs

All new routes use main's existing session, authentication, Host/Origin, privacy,
request-size and no-cache policies. No client-supplied output filesystem path is
accepted. Actions identify a current saved-image ID and file version.

| Route | Purpose |
| --- | --- |
| `GET/POST /api/images/{id}/actions` | Capabilities, Favourites (`keep`), virtual Delete (`delete`, legacy `trash` alias), Edit and Upscale |
| `GET /api/trash` | Browser/output-scoped Wastebin entries and errors |
| `GET /api/trash/{token}/thumbnail` | Validated metadata-free thumbnail |
| `POST /api/trash/{token}/restore` | Remove marker (`confirm: true`) |
| `POST /api/trash/{token}/delete` | Permanently delete one confirmed entry |
| `POST /api/trash/empty` | Permanently delete an explicitly confirmed `tokens` snapshot |
| `POST /api/vram/cleanup` | Request idle-only model unload/memory cleanup |

Edit/Upscale require a request UUID and current `modified` value. Edit also needs
an instruction; Upscale optionally accepts a positive multiplier, preserving the
saved value when omitted. Permanent/bulk deletion requires `confirm: true`.

## Verification

The existing main suite and browser checks are retained. New tests cover action
retries, actual saved editor fixtures, original pixels, graph preservation,
Favourites, virtual/permanent/bulk deletion, ownership, NFS failures and unchanged
preset/queue/UI contracts. Staged JS tests use Node when available; it is optional
for tests and adds no build/runtime dependency.

`tests/fixtures/main_presentation_baseline.json` pins main's original presentation,
controller/settings and version files. `test_feature_port_boundaries.py` checks
those bytes, the public shell and dormant-asset exclusions. It also checks that
image actions leave main's picker/mappings unchanged and create single jobs.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/mobile_responsive_browser.py --browser chromium --output /tmp/main-responsive-check
mkdir -p /tmp/main-feature-baseline
git archive 7e500d9 | tar -x -C /tmp/main-feature-baseline
.venv/bin/python tests/manual/main_feature_port_browser.py --browser chromium --baseline-root /tmp/main-feature-baseline --output /tmp/main-feature-parity-check
```

Use `--browser webkit` for the other supported engine and fresh output directories.
The parity script serves the actual main and ported backends in separate processes
and compares create/gallery/running pixels at nine compact, tablet and desktop
sizes (one-channel antialiasing tolerance only). A separate fixture page explicitly
activates the staged animation to verify unchanged button geometry and reduced
motion. The live app remains untouched.

Final validation for this port: 427 Python tests passed; Chromium and WebKit passed
main's original responsive/reconnect/reuse/privacy tests and the main pixel/layout
comparison plus isolated animation checks. Protocol and local filesystem fixtures
do not establish real Qwen/SeedVR GPU inference, installed-node compatibility,
NAS hardware, VPN or physical iOS behavior.
