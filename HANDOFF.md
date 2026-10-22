# Session handoff — 2026-10-22

## Current baseline

- Active development/testing branch: `integration/main-feature-ports`.
- Latest application commit: `3063489` — desktop image-action integration, pushed
  to the same branch on `https://github.com/jhakuzi/comfyui-control.git`.
- Base: main `7e500d9` (version 1.0.1). Selected features came from
  `testing/webui-desktop-forge` at `292f216`; that branch is a reference, not the
  working branch. Its charcoal/blue theme and desktop redesign were not merged.
- This handoff update changes documentation only. No application work remains
  uncommitted from the completed desktop integration.

## Completed

- `26395f7`: shared backend/API support for Qwen Edit, SeedVR Upscale, Favourites,
  virtual Wastebin, idle-only VRAM cleanup and workflow compatibility. Main's
  existing opt-in cross-device metadata sharing is retained.
- `3bbea58`: Generate animation uses main's yellow theme and actual sampling
  progress, with an indeterminate highlight elsewhere and reduced-motion support.
  Existing completion, cancellation, failure and reconnect handling is retained.
- `3063489`: Desktop Preview & Results has Heart / Edit / Upscale / Delete above
  Reuse settings / New variation. One action component follows image navigation
  and moves into the existing image viewer; controls are not cloned.
- Reuse settings restores the selected image's complete available settings and
  exact seed without generating. Edit/Upscale use the existing named workflows
  and shared pending UUID journal. Cancel preserves the generation form/draft.
- Favourites persist in the existing sidecar. Delete confirms a virtual marker;
  original files stay in place. A fresh result's file version is resolved through
  the existing bounded gallery scan before actions become available.

## Desktop / Phone separation

Desktop and Phone are independently developed presentations of the same app,
state and backend. Desktop placement is isolated in `presentation_desktop.js/css`;
shared behavior stays in `app.js` and `feature_*.js`. Main's yellow theme and
1000×600 wide-layout boundary remain unchanged. No Forge presentation files load.

Phone keeps its original controls, Same seed label, layout and interactions.
Desktop image-action components mount lazily; Phone sends no capability requests.
Resizing restores original nodes/labels and closes desktop action forms. Shared
changes still require Phone regression checks. See `docs/WEBUI_PRESENTATION.md`.

## Pending scope and known limitations

- The user is reviewing the desktop integration and will request visual changes.
  Work proceeds one feature/request at a time; wait for the next instruction.
- Wastebin management/restore/permanent-delete UI and VRAM cleanup controls have
  not been integrated on this branch. Their APIs exist. Phone image-action UI is
  also deferred. These are not authorization to start further integration.
- Existing backend behavior reports interruption of running work as `failed`;
  queued cancellation reports `cancelled`. This was preserved, not fixed here.
- Edit requires saved workflow `VeryComfy_Qwen21_Turbo_EDIT_ONLY`; Upscale requires
  `OfficialComfy-SeedVR_Upscaler`. Missing workflows disable actions with reasons.
- Actual Qwen/SeedVR inference, installation-specific nodes, NAS hardware, VPN and
  physical Phone behavior were not established by the latest fixture tests.

## Verification and next session

Latest application validation: **428 pytest tests passed**. Chromium and WebKit
passed desktop action flows, favourite persistence/navigation races, full reuse,
dialog cancellation, missing workflows/errors, real API submissions against a
protocol stub, same-UUID retries, virtual Delete, responsive/privacy/reconnect and
Generate checks. Phone pixels matched pre-integration `3bbea58` at 390×844,
430×932, 768×1024 and 844×390 after desktop transitions. Chromium also preserved
empty/gallery/running layout outside the authorized button feedback.

For a fresh local session, confirm this branch and working tree, read `AGENTS.md`
and the two integration/presentation docs, then use a local `.venv`. Commands and
baseline export instructions are documented there; previous `/workspace` and
`/tmp` artifacts are not required or assumed to exist locally. Review the user's
next request before changing code. No main merge or release is authorized.
