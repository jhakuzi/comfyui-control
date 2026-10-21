# Saved-image workflows — testing branch

Select a saved image in the preview or phone viewer, then choose **Edit** or
**Upscale**. Both retain the original image and use the existing queue, live
progress, gallery, cancellation and session recovery. The main generation
workflow and unsent prompt stay selected. Edit opens an instruction dialog;
cancelling it never submits. Upscale asks for an optional multiplier; leaving
it blank preserves the saved workflow value. A supplied multiplier maps only
to a unique numeric `scale_multiplier` input, or the native resize node's
`resize_type.multiplier` when its mode is `scale by multiplier`. Node limits
are checked before upload.
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

Normal saved editor workflows and API-format workflows are supported. The
converter understands declared upload controls, native canvas notes, ComfyUI V3
dynamic choices/image slots, and explicit subgraph connections/promoted widgets.
Expanded node IDs retain ComfyUI's namespace format, such as `66:57`. Exposed
subgraph instance settings take precedence over defaults inside its definition.
Installed ComfyUI input metadata remains authoritative.

An exact executable snapshot from ComfyUI's queue/history is still preferred
when it matches the complete saved editor data. Unknown widget serialization,
ambiguous boundary routing, recursive definitions, or muted/bypassed subgraph
instances require a matching snapshot or API export. No unknown connections
or widget values are guessed.

If an action reports subgraphs or custom widgets, use ComfyUI's **Export (API)**
(or **Save (API Format)**; enable **Dev Mode** in ComfyUI settings if hidden).
Save the export alongside the original editor file in the same user workflows
folder (normally `ComfyUI/user/default/workflows/`), with this companion filename:

- Upscale: `OfficialComfy-SeedVR_Upscaler.api.json`
- Edit: `VeryComfy_Qwen21_Turbo_EDIT_ONLY.api.json`

Refresh the WebUI after adding the file. The normal saved editor workflow is
preferred (root file first, otherwise a uniquely named nested copy). An API
companion is used if no original exists or its editor data cannot be converted.
This prevents an older API export from silently overriding current editor
settings. Original files are never overwritten. Simply renaming editor-format
JSON does not turn it into an API export.

The supplied Qwen Edit and SeedVR editor structures are regression-tested. The
Edit upload control is omitted from API inputs; its `images.image_1` and GGUF
model/cache links remain connected. The SeedVR subgraph is expanded without
changing its model, sampler, save paths or default scale. The supplied editor
and API examples have different settings, so they are not interchangeable copies.
Tests use redacted fixtures rather than distributing personal workflow values.

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
  per-browser image Favourites (stored in the existing Keep sidecar).
  No model-specific processing pipeline is constructed.
- `mobile/editor_subgraphs.py`: bounded, explicit subgraph boundary expansion
  with separate namespaced nodes and promoted literal values.
- `mobile/input_metadata.py`: shared V3 dynamic metadata expansion used by the
  importer and mapped-control validation; it respects the selected branch.
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

Image favourites, recoverable Trash and browser-filtered generation history continue
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
