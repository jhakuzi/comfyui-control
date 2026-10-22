# Guide for Codex sessions

Read `HANDOFF.md`, `docs/WEBUI_PRESENTATION.md` and
`docs/FEATURE_PORT_INTEGRATION.md` before changing code. Inspect the current
branch, recent commits and working tree. Treat the implementation as the baseline;
do not assume earlier requests or deferred integrations are unfinished assignments.

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
| `network_output.py`, `background_process.py` | Authorized output filesystem operations and bounded workers. |
| `mobile/web/app.js` | One shared application controller, selection, drafts, requests, generation and pending journal. |
| `mobile/web/feature_*.js` | Shared Generate/image-action components and transport. |
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
  separate Phone adapter on this branch; do not import Forge layout/theme files.
- Reuse existing DOM nodes, IDs and handlers; restore their original placement and
  labels on leaving desktop. New desktop containers use `data-desktop-slot`.
  Phone changes require an explicit request. Desktop work must preserve Phone
  layout, styling, navigation, interactions, drafts and live jobs.
- Shared `style.css`, `index.html`, `app.js` and feature components affect both
  presentations. Make necessary changes narrowly and verify both. Do not add
  polling, duplicate listeners or redundant capability requests.
- Keep new public assets in `mobile/server.py`'s allowlist and `web/sw.js`'s shell;
  bump the shell cache when shipping changed assets. Never cache private APIs or
  images. Preserve reduced-motion support.

## Data and safety contracts

- Act on the explicitly selected image and version. Ignore stale async responses
  after navigation; opening/cancelling an action must preserve generation drafts.
  Full settings reuse preserves exact 64-bit seeds and never auto-generates.
- Use the existing pending-submission journal and UUID for uncertain retries,
  including image workflows. Reconnect must not resubmit accepted work.
- Preserve unknown workflow nodes, links, model choices, GGUF/LoRA wiring and
  saved editor settings. Change only validated mapped literals; never invent a
  replacement Qwen/SeedVR pipeline. Named action bindings live in `IMAGE_WORKFLOWS`.
- Favourites use the existing private Keep sidecar (`keep`/`kept`). Virtual Delete
  changes metadata only. Restore removes that marker; only explicitly confirmed
  permanent deletion may remove originals. Retain configured-root, file/directory
  identity, symlink, ownership and output-scope guards and bounded NFS workers.
  Failed deletion stays in Wastebin with its error.
- Preserve Host/Origin checks, authentication, CSP and browser isolation. Optional
  metadata sharing grants no access to another browser's jobs, cancellation,
  history or deletion permissions. Never commit credentials or private prompts.
- Keep blocking filesystem/NFS/GPU work off Qt and HTTP event loops. Preserve
  atomic metadata writes and corruption safeguards. Do not disturb user settings
  or unrelated mounts; do not start competing app instances against one config.

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
.venv/bin/python -m playwright install chromium webkit
.venv/bin/python tests/manual/desktop_image_actions_browser.py --browser chromium --output /tmp/control-desktop-actions-check
.venv/bin/python tests/manual/mobile_responsive_browser.py --browser chromium --output /tmp/control-responsive-check
.venv/bin/python tests/manual/mobile_generate_button_browser.py --browser chromium --output /tmp/control-generate-check
git diff --check
```

Repeat relevant browser checks with WebKit and fresh output directories. See
`docs/WEBUI_PRESENTATION.md` for Phone pixel comparisons against an exported
baseline. Node runs optional shared-JS tests; it is not a runtime/build dependency.
Browser/protocol fixtures do not prove real GPU inference, NAS or physical Phone
behavior. Historical test counts are evidence, not a substitute for current checks.

Keep changes focused, follow adjacent conventions and run relevant checks. Do not
change versions, rebuild release artifacts, merge, tag or publish unless requested.
Commit/push when authorized; never force-push by default. After a push, provide the
branch/commit and full fresh-clone, venv, install and launch testing commands.
