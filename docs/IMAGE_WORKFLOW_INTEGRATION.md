# Saved-image actions and future workflows

This branch uses the existing frontend, `MobileService`, preset mappings,
ComfyUI client, generation queue, SSE progress and session recovery.

## Current boundary

- `mobile/image_actions.py`: image workflow role descriptors (`edit`, `upscale`)
  and atomic per-browser Keep marks. `workflow_capabilities()` reports both
  workflow roles unavailable, with human-readable reasons.
- `MobileService.image_action_capabilities(image_id, owner)`: capability query
  for one registered saved image, including its current file version. This is
  the shared point for future workflow readiness checks.
- `GET/POST /api/images/{id}/actions`: explicit image target, action name and
  expected `modified` version. No client-supplied filesystem path is accepted.
  Unsupported workflow actions are rejected rather than simulated.
- `web/image_actions.js`: one action component used in the center preview and
  existing mobile image viewer. Selection epochs guard late capability responses;
  mutations capture the image ID/version before awaiting the server.
- `network_output.py`: the existing bounded filesystem worker handles Trash,
  listing and restore for local or NFS output. Private trash entries contain the
  file and a recovery manifest; gallery/path guards exclude that directory.

Keep marks live in `mobile/image-library.json`, independently of jobs, presets
and prompt favorites. Public job views omit unavailable images; stored jobs are
not rewritten when an image is trashed. Browser history renders existing jobs.

## Adding edit/upscale execution later

1. Inspect a tested ComfyUI API workflow and its installed node definitions.
   Associate the role with an existing preset and explicit image/mask inputs.
   A configured role must only become available once its bindings are usable.
2. Resolve the selected source by its registered image ID, current output scope
   and version. Apply existing ownership/metadata policy. Recheck after I/O; a
   changed output folder or replaced file must invalidate preparation.
3. Upload a source copy to ComfyUI using its supported API when required. Keep
   the original saved image untouched. Do not expose arbitrary local paths.
4. Prepare a draft using the current preset/mapping renderer. Queue only through
   `MobileService.submit`, retaining its request UUID/idempotency and browser owner.
   Store source-image provenance as additive metadata, not a second job journal.
5. Receive progress, cancellation, reconnect recovery and saved results through
   the current client/service/SSE/gallery paths. New results get new filenames.

Enabling a capability alone does not install an execution handler: extend the
explicit action dispatcher when the actual workflow integration is implemented.
There is intentionally no placeholder graph, alternate queue, browser-session
system, workflow-purpose migration, or model-specific execution in this branch.
