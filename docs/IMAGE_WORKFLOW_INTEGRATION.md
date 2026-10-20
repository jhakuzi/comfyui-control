# Saved-image workflows — testing branch

Select a saved image in the preview or phone viewer, then choose **Edit** or
**Upscale**. Both retain the original image and use the existing queue, live
progress, gallery, cancellation and session recovery. The main generation
workflow and unsent prompt stay selected. Edit opens an instruction dialog;
cancelling it never submits. Upscale asks for an optional multiplier; leaving
it blank preserves the saved workflow value. A supplied multiplier maps only
to a unique numeric `scale_multiplier` input and must satisfy its node's limits.
Ambiguous, missing or connected multiplier inputs are rejected when overridden.
The original workflow graph and image stay unchanged. Unsent edit instructions are retained per image in
this browser, including across refreshes.

## Setup in ComfyUI

Save these tested workflows in ComfyUI's **Workflows** list, then refresh the WebUI:

| Action | Saved filename | Explicit inputs |
| --- | --- | --- |
| Upscale | `OfficialComfy-SeedVR_Upscaler.json` | `1.image` (`LoadImage`) |
| Edit | `VeryComfy_Qwen21_Turbo_EDIT_ONLY.json` | `88.image` (`LoadImage`), `89.prompt` (`TextEncodeQwenImage21`) |

Qwen node 89 must retain `images.image_1: ["88", 0]`. The app verifies that
connection and leaves it intact. Models, LoRAs, seed defaults, custom nodes and
all other saved inputs/connections remain as saved in the action workflow.
These actions do not inherit the main generation form's current settings.

API-format saved workflows are supported. For editor-format workflows containing
custom widgets, run that exact saved workflow once in ComfyUI first so the
existing importer can find its executable snapshot. If conversion cannot be
verified, the error requests an API export or exact queued snapshot; custom
widget values and connections are never guessed.

If an action reports subgraphs or custom widgets, use ComfyUI's **Export (API)**
(or **Save (API Format)**; enable **Dev Mode** in ComfyUI settings if hidden).
Save the export alongside the original editor file in the same user workflows
folder (normally `ComfyUI/user/default/workflows/`), with this companion filename:

- Upscale: `OfficialComfy-SeedVR_Upscaler.api.json`
- Edit: `VeryComfy_Qwen21_Turbo_EDIT_ONLY.api.json`

Refresh the WebUI after adding the file. The app prefers the root API companion,
then the root original; otherwise it accepts a uniquely named nested API
companion or original. The original editor workflow stays untouched. Simply
renaming an editor-format JSON file does not turn it into an API export.

Missing saved workflows disable the action with an explanation. Missing custom
nodes, changed bindings, upload failures or invalid workflow inputs produce a
specific error before queueing. Full workflow graphs and models are supplied by
the user's ComfyUI installation, not bundled with this app.

## Source images and privacy

Actions support saved images in the configured local or NFS output folder.
Select an image with a current gallery version; unavailable/replaced files are
rejected. No client-supplied filesystem path is accepted. The original stays in
place, and a PNG copy of its pixels is uploaded through ComfyUI's `/upload/image`
API into `input/` with a unique `comfyui-control-` filename and overwrite
disabled. This location works with the standard LoadImage file selector.
These source copies remain in ComfyUI input storage for workflow reuse; they are
not automatically deleted. An upload followed by a failed validation can also
leave an unused input copy.

Embedded image metadata is stripped from the uploaded copy. Editing visible
pixels does not grant access to another browser's prompts/settings, job status
or cancellation. Existing metadata-sharing preferences and Trash ownership
checks are unchanged. Remote API-only output without a locally configured
output folder is unavailable for these actions.

## Implementation boundary

- `mobile/image_actions.py`: exact named workflow bindings, validation and
  per-browser Keep marks. No generation graph is constructed here.
- `MobileService.describe_image_actions()` discovers saved workflow names;
  `run_image_workflow()` validates the graph/source, uploads pixels and reuses
  existing mapped presets plus `submit()`. Job identity and persistence remain
  in the existing journal. Retrying an accepted request UUID never uploads or
  queues it again, including after a service restart.
- `GET/POST /api/images/{id}/actions`: explicit selected image, current `modified`
  version, action and request UUID. Edit also supplies an instruction.
- `web/image_actions.js`: shared preview/viewer actions. `app.js` keeps pending
  action submissions in the existing recovery store and uses the same live jobs.
- `mobile/image_pixels.py`: shared metadata-free encoding for HTTP responses
  and action source uploads. Original image files are never rewritten.
- `network_output.py`: existing bounded worker validates path/version and reads
  source pixels without blocking the embedded HTTP event loop.

Keep marks, recoverable Trash and browser-filtered generation history continue
using their existing stores and guards. No additional service, frontend,
ComfyUI node package or dependency is introduced.

Automated tests use representative API graphs, Chromium/Linux WebKit and a
ComfyUI protocol fixture. They do not establish inference compatibility with
the full SeedVR/Qwen workflows or installed models; verify those on your PC.

## VRAM cleanup

The WebUI's **VRAM cleanup** button uses ComfyUI's standard `POST /free` API
with `unload_models` and `free_memory`. It is available while connected and the
queue is empty. The backend checks the complete queue again before forwarding
the request, including work from ComfyUI's regular interface or other clients.
It does not interrupt generations, restart ComfyUI or alter images/workflows.
ComfyUI performs the release; the UI reports the request rather than claiming
an immediate amount of freed VRAM. Models reload on the next generation.
