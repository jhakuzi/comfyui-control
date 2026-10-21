# Session handoff — 2026-10-21

## Snapshot and current authorization

- Repository: `https://github.com/jhakuzi/comfyui-control`, local checkout
  `/workspace/comfyui-control`.
- Active branch: **`testing/webui-workspace`**.
- Application baseline before this documentation commit: **`7239ef6`**,
  version **`1.1.0.dev7`**. A fresh clone confirmed the remote testing branch
  still pointed there when preparing this documentation push.
- At the previous review, local `main` and `origin/main` pointed to **`7e500d9`**,
  the 1.0.1 release. They were inspected local refs, not a current main-branch query.
- The user initially requested these documents without committing or pushing.
  Their subsequent instruction explicitly authorizes **committing and pushing
  these two documents to GitHub**. No application changes, main merge, release
  tag, package rebuild or COPR build are authorized by this documentation push.
- The workspace was replaced after the initial local documents were written.
  Those files were restored from the prepared conversation text and checked
  against a fresh clone; previous local runtimes/artifacts are not available here.
- Uninstall work is separate: `testing/uninstaller`, commit **`b0ee8f0`**, adds
  uninstall script/UI/safety tests. The user explicitly said to merge it later;
  it is not present in the current application tree. Do not assume otherwise.

Durable code map, setup commands and project constraints are in `AGENTS.md`.
This file records session state and evidence, not a second architecture manual.

## Objectives and conversation context

The supplied conversation spans the project's earlier desktop/mobile releases,
then this unreleased responsive workspace. Earlier stable functionality includes
tray behavior, optional NFS output/fallback, SSH startup, PNG metadata reuse,
monitoring, prompt history, comparison and mobile reconnection. Preserve it.
The user reported successful real-device tests of those older features, including
iPhone recovery, NAS setup/removal and output/gallery fallback. Those reports
are not fresh verification of every change in this branch.

Current development objectives, in order:

1. Extend the same WebUI to three desktop columns while retaining the compact
   mobile interface, shared state/recovery and custom workflow compatibility.
2. Add actions tied to the selected saved image: Keep, Edit, Upscale and Trash;
   retain original images and expose unavailable actions honestly.
3. Apply and refine the supplied charcoal/blue native-app visual reference,
   without adding a separate frontend or changing persistence architecture.
4. Fix LoRA replacement behavior; integrate full-view tools into the wide
   preview, retain phone dialogs and move Generation settings before LoRAs.
5. Wire user-named Edit/Upscale workflows, optional upscale multiplier, idle VRAM
   cleanup, boxed Details/Copy prompt and richer generation progress/loading UI.
6. Resolve the actual supplied editor-workflow import errors using normal/API
   exports, preserving real settings and connections.
7. Document Debian 13 headless dependencies and provide UI-only testing without
   an existing desktop-configured ComfyUI environment.

The earlier inpainting/Mask by Touch compatibility plan was explicitly superseded
by the responsive-workspace request. There is **no approved pending inpainting
implementation** to resume automatically. The visual reference's Inpaint UI was
a style reference, not authorization to add its feature set.

The user prefers small/lightweight software, concise README text, clear errors,
short button labels without `...`, practical testing commands, and testing
branches before release. Current requests do not authorize a release/build.

## Work completed and why

### Responsive workspace and styling

- One existing frontend now adapts to phone, two-column medium and three-column
  desktop/landscape layouts. Settings/prompt remain left, selected preview center,
  gallery/history right; exact breakpoints are documented in
  `docs/RESPONSIVE_WEBUI.md` and implemented in CSS.
- Shared charcoal surfaces, blue action states, compact controls and centralized
  CSS tokens; focus, disabled/error states and reduced motion remain supported.
- Wide preview includes Previous/Next, Save image, Details and shared actions.
  Phone full-size viewer remains separate. Generation settings precede LoRAs.
- LoRA replacement now updates the slot's checkbox label/enabled state. Another
  slot's selected filename/strength is preserved; manual disabling remains possible.
- Header progress is boxed and only visible when active, with reduced-motion
  aware fades. Loading spinner/statistics occupy the empty preview, or overlay a
  live preview. They reuse existing monitoring rather than adding GPU polling.
- Details uses matching boxes and prompt-copy controls, including a LAN HTTP
  clipboard fallback. Existing thumbnail sizes and comparison behavior are retained.

### Saved-image actions and generation utilities

- Keep is a browser/output/file-version scoped sidecar mark; it moves no files.
- Trash/Restore uses private `.comfyui-control-trash` storage under the output
  root with local and bounded NFS-worker paths. No permanent-delete operation.
- Edit/Upscale validate selected image identity/version and explicit workflow
  inputs; copy pixels through `/upload/image` without embedded private metadata.
  Original files remain. The main generation preset and unsent draft stay selected.
- Both actions reuse normal mapped presets, submission UUIDs, journal, ownership,
  progress/cancellation and recovery. Retrying an accepted request does not queue
  or upload twice, including after a service restart.
- VRAM cleanup forwards ComfyUI's `/free` only after checking the entire queue
  is empty. It requests unloading/freeing rather than claiming measured freed
  memory. No server restart or global interruption is introduced.
- API companions remain a recovery path with actionable errors; a renamed editor
  file is never treated as a converted API export.

### Real editor/API compatibility fixes

The user supplied both normal editor files and API exports for:

| Action | Workflow stem | Verified binding |
| --- | --- | --- |
| Edit | `VeryComfy_Qwen21_Turbo_EDIT_ONLY` | `LoadImage` node `88.image`; `TextEncodeQwenImage21` node `89.prompt`. Preserve `images.image_1: ["88", 0]`. |
| Upscale | `OfficialComfy-SeedVR_Upscaler` | `LoadImage` node `1.image`; native resize input `66:57.resize_type.multiplier` in `scale by multiplier` mode. |

The explicit workflow names/bindings are user-approved. General importer logic
remains metadata-driven; no Krea/Qwen/SeedVR processing pipeline is embedded.

Verified causes of the reported import failures:

- LoadImage serializes an extra declared `IMAGEUPLOAD` UI marker (`"image"`)
  beyond its backend `image` input. The strict importer previously rejected it
  as an unknown custom widget. Only the matching declared upload marker is skipped.
- Qwen reference slots use native V3 Autogrow metadata and qualified
  `images.image_1` names; these are expanded from installed input definitions.
- The upscaler contains a native subgraph instance `66`. The importer previously
  rejected subgraphs wholesale. New bounded expansion preserves namespaced node
  IDs, explicit input/output boundary links and promoted parent widget values.
- Its displayed `scale_multiplier` label is not the executable input name. The
  actual qualified FLOAT is `resize_type.multiplier`, with metadata limits.
- Native socketless ImageCompare's empty UI data is serialized as its API wrapper;
  unregistered native canvas notes are omitted. Unknown serialization still fails
  closed. Muted/bypassed subgraph instances still require snapshot/API fallback.

Important differences between the user's supplied files:

- The normal Qwen editor has `90.model: ["99", 0]`, a GGUF/cache model link missing
  from the supplied API export. Conversion retains the editor's complete link.
- The normal SeedVR instance exposes **3×** while its definition/API export
  contains **4×**. The parent instance wins; blank multiplier uses the saved 3×.
- Prompts, seed, filenames/output prefixes and device settings also differ.
  These exports are not interchangeable snapshots of identical settings.
- Normal editor files now take precedence over API companions. A companion is
  used if no original exists or original conversion fails, rather than silently
  replacing current settings with an older export.
- Integer-looking defaults for metadata-declared FLOAT controls accept fractional
  changes; e.g. a multiplier of 1.5 is validated against the installed schema.
- Redacted copies of the supplied structures are committed under
  `tests/fixtures/workflow_conversion/`; private uploaded originals are not bundled.

### Debian documentation and standalone demo

- README and SSH/usage guides explain Python packages versus OS Qt libraries,
  Debian 13 runtime installation, real import checks, xcb/display failures and
  optional NFS packages. Installing a desktop is not necessary for terminal mode.
- Normal `--start-webui` still requires saved configuration. That was the user's
  latest blocker on a new headless server; it was not a missing Qt-library error.
- New **`--demo-webui`** uses the real MobileHTTP/MobileService/frontend with a
  loopback ComfyUI protocol simulator and six abstract sample images. No desktop
  configuration, real ComfyUI server, models, GPU, mount setup or real output
  folder is loaded. It includes sample model/VAE/encoder/LoRA controls.
- Generate creates another abstract image with simulated progress. History,
  details, Keep, reuse and recovery use existing code. Real Edit/Upscale remain
  disabled because their workflows are absent; GPU metrics remain unavailable.
- Demo has a visible notice, a temporary data directory and clean Ctrl+C/SIGTERM
  shutdown. Default is `127.0.0.1:8190`; `--demo-host 0.0.0.0` enables LAN access.
  Separate default port avoids sharing real WebUI localStorage on port 8189.
- Conflicting CLI flags, invalid IP/port and occupied ports produce terminal
  errors without a traceback. Demo mode does not repair or overwrite corrupt
  existing configuration. SIGKILL cannot guarantee temporary-directory cleanup.
- A workspace-local preview was run earlier, but no supported inbound URL could
  be exposed from that cloud environment. Do not promise a remotely reachable
  preview without checking current hosting capabilities. The new demo lets the
  user test on their own Debian machine.

## Change history and files

Main feature commits on this branch, oldest first:

| Commit | Change |
| --- | --- |
| `e9dc056` | Responsive workspace and saved-image actions. |
| `304249d` | Landscape/ultrawide layout tuning. |
| `b9f0c89`, `4723771` | Shared visual system and refinement. |
| `3c78fa5` | LoRA fix and wide-preview tools. |
| `d047d69` | Named workflow Edit/Upscale integration and active progress styling. |
| `9eec3f3` | API companion fallback and actionable import errors. |
| `7245ac1` | VRAM cleanup, multiplier, Details and generation feedback. |
| `a6d8cc0` | Native saved-editor/dynamic-input/subgraph support. |
| `3f992da` | Debian headless documentation. |
| `7239ef6` | Isolated demo mode, tests and documentation. |

File inventory relative to the inspected 1.0.1 baseline (`7e500d9`):

- **Added runtime:** `mobile/{demo,editor_subgraphs,image_actions,image_pixels,input_metadata}.py`
  under `comfyui_control/`, and `mobile/web/image_actions.js`.
- **Modified runtime:** `comfyui_control/{__init__,cli,network_output}.py` and
  `comfyui_control/mobile/{client,server,service,workflow_sources,workflows}.py`.
- **Modified frontend:** `mobile/web/{app.js,image_details.js,index.html,
  manifest.webmanifest,style.css,sw.js}` under `comfyui_control/`.
- **Added tests:** `tests/test_{demo_webui,editor_workflow_compatibility,image_actions,image_workflows}.py`;
  four `tests/fixtures/workflow_conversion/{qwen,seedvr}-{editor,api}.json` fixtures;
  `tests/manual/mobile_{demo,image_workflows,saved_editors}_browser.py`.
- **Modified browser checks:** `tests/manual/mobile_{extras,loras,responsive}_browser.py`.
- **Added documentation:** `docs/IMAGE_WORKFLOW_INTEGRATION.md`.
- **Modified documentation:** `README.md`,
  `docs/{MOBILE,MOBILE_ARCHITECTURE,RESPONSIVE_WEBUI,SSH,USAGE}.md`.
- **Modified metadata/packaging:** `pyproject.toml`, `packaging/comfyui-control.spec`.
- No files were removed. The handoff/documentation push additionally creates the
  two root documents; it does not rebuild packages or alter application files.

## Verification evidence and limits

These results were actually obtained earlier in the session; they were **not
rerun during the documentation-only review or subsequent documentation push**:

| Check | Result / scope |
| --- | --- |
| Full pytest suite before demo addition | **410 passed** after real-editor compatibility work. |
| Latest full pytest suite | **419 passed in 29.72s**, including nine demo cases, before the final demo-default-port adjustment to 8190. Subsequent Debian/browser checks passed; the full suite was not rerun after that adjustment. |
| Supplied original JSON conversion | Both uploaded normal workflows converted to 13-node API graphs with saved values/connections preserved; original files unchanged. Installed-node definitions were inspected as source, not exercised with models. |
| Saved-editor browser flow | Chromium and Linux WebKit passed Edit → result → Upscale 1.5 → reload/reuse using redacted real structures and a protocol fixture. |
| Existing action browser regression | Chromium passed dialogs/default multiplier/cancel, cleanup, draft preservation, progress/reload, lost response and API fallback. |
| LoRA regression | Chromium passed the replacement/isolation check after converter changes. |
| Demo integration tests | No display or valid config required; simulated result/recovery, cancellation, invalid/conflicting flags, port conflict and cleanup; sentinel settings remained unchanged. |
| Demo browser checks | Chromium and Linux WebKit passed responsive sizes, draft/LoRA refresh persistence, simulated result and Keep. Chromium also waited for decoded gallery image dimensions. |
| Clean Debian 13 amd64 container | Python 3.13/PySide6 6.12 import and headless startup/stop passed with the documented OS packages. New demo LAN binding/frontend/gallery/shutdown also passed with the current source mounted into that container. No GPU inference. |
| Whitespace | `git diff --check` passed before implementation commits. |

Artifact directories in the **previous, now unavailable workspace** included
`/workspace/saved-editor-conversion-chromium-v2`,
`/workspace/saved-editor-conversion-webkit-v1`,
`/workspace/saved-editor-actions-chromium-final`,
`/workspace/demo-webui-chromium-v2`, `/workspace/demo-webui-webkit-v1`.
They are not repository files and are not present in the replacement workspace.
Do not claim to have re-inspected them here; recreate checks when new evidence is needed.

## Open issues, limitations and release debt

**Verified current limitations:**

- Real Qwen/SeedVR GPU inference has not been tested in the agent environment or
  confirmed by the user after the latest converter fix. The full required models
  and GPU runtime were unavailable. Passing graph tests is not inference proof.
- Unknown custom widgets, ambiguous subgraph promotion/routing, recursive/deep
  definitions and muted/bypassed subgraph instances intentionally request API
  exports or exact queued snapshots. Do not weaken these safeguards to hide errors.
- Image actions require a configured local/NFS output folder. Remote API-only
  images are not action sources. Uploaded input copies remain in ComfyUI `input/`;
  failed attempts after upload can leave unused copies. No automatic deletion.
- The existing service reports interruption of a running generation as `failed`
  with an interruption message; queued cancellation can be `cancelled`. Demo tests
  respect this behavior rather than changing production session semantics.
- No deployment/package rebuild was performed for dev7. RPM spec remains
  `Version: 1.1.0`, `Release: 0.2.dev2`, while Python metadata is `1.1.0.dev7`.
  The SRPM script accepts `.devN` Python suffixes, but release metadata needs
  reconciliation before an authorized release. Do not publish this mismatch.
- README/release downloads and several guides retain stable/historical version
  text and screenshots. `docs/RESPONSIVE_WEBUI.md` still mentions only the older
  `scale_multiplier` alias in its action summary; the integration guide/code also
  supports the actual `resize_type.multiplier`. No unrelated docs were edited here.
- Uninstall integration remains in its separate branch and has not been merged
  or revalidated against this workspace.

**Unresolved observations/questions, not confirmed product defects:**

- Full-page demo screenshots showed dark thumbnail cells despite nonzero decoded
  image dimensions. A direct PNG/JPEG pixel check returned colored sample pixels.
  This may be browser screenshot/paint timing; visually inspect on a real browser
  before claiming either a gallery bug or full visual verification.
- The user has not yet reported running the new demo mode on their Debian server.
- Current branch changes need physical iPhone/iPad and real NAS Trash/Restore
  checks. Earlier user confirmations apply to the older output/reconnect features.

## Recommended next steps (priority order)

1. Let the user update their testing checkout and run the new demo command below;
   collect any actual Debian import, bind/firewall or visual issues. Investigate
   thumbnail painting if reproduced. Keep demo distinct from real generation.
2. On the user's configured PC, verify selected older image → Edit instruction
   and Upscale with blank/1.5 multiplier using the current saved editor workflows.
   Check actual outputs, GGUF/cache wiring, saved 3× default, model availability
   and clear errors. Do not silently replace graphs with the supplied older API.
3. Manually exercise real-generation refresh/phone lock/VPN recovery, duplicate
   prevention, cancellation, image ownership/sharing, source preservation and NFS
   fallback/gallery/Trash restore on this branch.
4. If requested, merge `testing/uninstaller` separately. Reconcile CLI/metadata,
   installer/ZIP contents, Settings UI and uninstall safety tests; run regressions.
5. After user approval only: reconcile documentation/version/spec/downloads,
   rerun appropriate tests, merge to main, tag and queue COPR using release guides.
   No new release authorization has been given.

Latest command supplied to the user, from their existing testing checkout:

```bash
git pull --ff-only
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control --demo-webui --demo-host 0.0.0.0
```

Open `http://YOUR_SERVER_IP:8190/` on the trusted LAN/VPN. Qt OS dependencies are
still required. Ctrl+C stops the demo; it performs no real inference.

## Workspace-specific cautions

- The previous environment used `/workspace/.venv/bin/python` and
  `/workspace/.playwright-browsers`. They are conveniences, not project requirements,
  and were not carried into this replacement workspace. Set up fresh tooling as needed.
- In the previous managed workspace, loopback/subprocess/browser tests needed tool
  network permission; restricted runs could hang in asyncio thread wakeups.
  Do not diagnose those hangs as application failures without a permitted rerun.
- Browser runs used `QT_QPA_PLATFORM=offscreen`,
  `XDG_CACHE_HOME=/tmp/comfy-workspace-cache`,
  `PLAYWRIGHT_BROWSERS_PATH=/workspace/.playwright-browsers`; Linux WebKit also
  used `PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1` after libraries were present.
- The original workflow uploads were downloaded under `/workspace/attachments/`
  in the previous environment. Use committed redacted fixtures for portable tests;
  never distribute personal originals. Its
  `/workspace/comfyui-real-test/fedora/ComfyUI` checkout was read only to inspect
  native node definitions, not changed or used for Qwen/SeedVR inference.
- Old workspace-local QA preview processes were stopped before replacement.
  Do not rely on a live cloud preview URL or old temporary containers/artifacts.
