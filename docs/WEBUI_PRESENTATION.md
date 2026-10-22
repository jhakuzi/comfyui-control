# WebUI presentation layers

ComfyUI Control serves one buildless application, with independent mobile and
desktop presentation adapters. The initial separation preserved the appearance
and behavior at `cddb86b`. The desktop workspace described below evolves only
the desktop adapter; mobile/tablet presentation and the shared backend remain
unchanged.

## File responsibilities

Paths below are relative to `comfyui_control/mobile/web/`.

| Files | Responsibility |
| --- | --- |
| `theme.css` | Shared colors, typography, spacing, radii and design tokens. |
| `style.css` | Shared component skins, controls, dialogs, image/gallery components and animations, including Generate and cancellation. |
| `presentation_mobile.css` | Phone layout, compact navigation/dock, small-screen rules, and the existing medium-width tablet layout. All selectors are scoped to the mobile presentation. |
| `presentation_mobile.js` | Mobile/tablet navigation, panel/metrics placement, dialog tool placement, and compact section restoration. |
| `presentation_desktop.css` | Desktop page layout, toolbar, prompts/actions, settings columns, preview and gallery geometry. All selectors are scoped to desktop. |
| `presentation_desktop.js` | Desktop component placement, forced-open sections, inline image viewer and presentation interactions. |
| `presentation.js` | Viewport selection and adapter coordination, temporary layout preferences, geometry observers and reversible DOM placements. No network or persistence operations. |
| `index.html` | One shared shell and set of controls, with stable IDs and desktop-only staging slots. |
| `app.js` | One application controller: requests, state, workflow fields/drafts, jobs/progress, reconnect, and shared rendering. Delegates placement/navigation to presentation adapters. |
| `comparison.js`, `image_details.js`, `image_actions.js`, `prompt_history.js` | Shared feature components and interactions. |
| `sw.js` | Public shell cache, including all presentation assets; never private API or image data. |

The Python service, workflow bindings, generation queue, API routes and persistence
are shared and unchanged by presentation selection. The only server adjustment
for this refactor is permitting the additional public CSS/JS assets. Existing
`web/*` package data includes them without a new build step or dependency.

## Desktop workspace

The desktop adapter uses a wrapping workflow/model/VAE/encoder toolbar with a
reserved cancellation slot at its upper right. Reuse last generation sits with
the toolbar utilities so queue state cannot change the height of the prompt row.
Prompts appear side by side from 1280px, with visually hidden accessible labels,
Expand inside the positive editor, and Generate/History/Favourites aligned beside
them. The positive/negative split is 2.2:1; narrower desktop windows stack the
prompts. Expanding the positive prompt floats its existing padded editor above the
workspace with a shadow, retaining the collapsed footprint so other panels do not
move. Its initial bottom edge tracks the bottom of Batch count through the desktop
geometry observer; manual textarea resizing remains available. Collapse returns
it to normal flow. Both modes keep the same live textarea,
draft and existing Expand/Collapse state. The positive placeholder omits
its ellipsis only on desktop and restores the original attribute on mobile.

Generation, resolution and LoRAs occupy one bounded column. Completed images and
live image previews scale to the same bottom edge as those settings, preserving
aspect ratios and room for compact image actions. The existing Favourites heart
moves reversibly to the image's upper-right corner, following its rendered bounds
rather than the surrounding letterbox. Edit/Upscale/Details/Trash use four equal
columns, and Reuse settings/New variation use two aligned columns. The Save image
and arrow row retains its existing layout. Empty workflow-status text is hidden
on desktop so the gaps between Save/actions/reuse rows are consistently 6px. While viewing a saved image, an empty
or previous job output must not reserve flex space above it; live generation still
uses the original preview when the user is not inspecting a saved result.
Idle/loading placeholders stay compact. The gallery follows the aligned workspace, with Advanced & workflows
below it while remaining inside the original form. Gallery thumbnails use flexible
columns of at least 200px, filling the available width. A desktop ResizeObserver
caps the grid at eight complete rows plus gaps/padding; additional rows scroll
inside the grid. The existing comparison controls move into the gallery filter
bar through `place()`. The redundant gallery History shortcut is hidden on desktop;
the prompt History shortcut and mobile job-history controls remain available.

Desktop textareas retain their original elements inside reversible padded frames,
keeping native scrollbars and resize grips clear of rounded borders. Dialogs scroll
inside an inset viewer, and action button labels are centered consistently. Prompt
History is up to 1080px wide with six larger cards visible before internal scrolling;
Delete sits inside each card's upper-right corner. Search, reuse and deletion still
use the shared prompt-history component.

Double-clicking the desktop saved-image preview opens a centered native dialog
with a dimmed backdrop and the existing shadow token. Enter/Space on the focused
preview also opens it. The original image, Favourites heart and complete selected-
image action components move through `place()` into the popup. The same Save/arrow,
four-action and two-reuse rows sit below the image, using the same IDs, classes,
style declarations and handlers as the regular preview. Moving the entire
`selected-image-tools` container keeps the navigation handler's collection context
intact. No controls, action state, request handling or ordering logic are cloned.

The popup uses the existing `.viewer` scrolling component and `.heading` class.
Heart/Close float over the image in its upper-right corner, as explicitly
requested. The three action rows remain in normal flow below the image. The image keeps its viewport-derived size
and the viewer scrolls vertically to reveal the controls. Desktop component sizing
rules apply to both original locations without changing the regular preview.
Left/Right in the popup activate the existing navigation buttons, respecting
disabled states, text inputs, modifier keys and nested dialogs. Image navigation
keeps the viewer open and updates its aspect ratio after the image loads. Shared
workflow/reuse actions close it when they navigate to generation settings; empty
selection, sign-in and mobile transitions also close it. Close/Escape restores
all original nodes and returns keyboard focus. Mobile attributes and placements
are restored by the existing coordinator.

A small shared action-state fix refreshes the current capability state after an
action ends, even when `select()` advanced its epoch during the refresh. Without
this, a fast favourite response could permanently disable the current buttons.
It adds no requests or alternate action path; the same fix is checked in regular,
enlarged and mobile views, including delayed-response navigation.

The desktop Details button opens a native dialog containing the existing metadata
controls, moved through `place()`. The shared loader still owns all metadata
requests. Desktop Copy details serializes the rendered metadata, including collapsed
sections, and retains exact seed strings. Escape/Close restore focus; switching to
mobile closes the popup and restores the original controls. All new desktop
containers are marked `data-desktop-slot`.

The coordinator exposes optional image-action presentation hooks. The shared
renderer delegates only presentation of unavailable Trash actions: desktop shows
the existing reason on attempted use, while mobile retains its disabled button
and explanatory text. Unavailable actions still return before any API mutation;
backend ownership checks are unchanged. Theme/component skins, mobile/tablet
adapters, application state, mode selection and backend remain unchanged.

## Mode selection and isolation

`presentation.js` selects the presentation before the first application paint,
using the existing viewport conditions:

- Desktop: at least 1024px wide, 600px tall and 4:3 aspect ratio; or at least
  1440px wide and 600px tall.
- Mobile presentation: all other viewports, including tablet portrait and short
  windows. Its existing medium layout still starts at 1000×600; the 700px and
  360px responsive adjustments are retained.

The root gets `data-presentation="mobile"` or `"desktop"`. Each layout selector
starts with `:where(html[data-presentation="…"])`. The scope adds no specificity,
so the old component cascade stays intact. Layout rules never leak to the other
mode. The desktop sheet contains its own initial baseline geometry rather than
inheriting mobile layout rules; some initial layout declarations are therefore
intentionally similar in the two sheets. They may now evolve independently.

There is one DOM instance of each control. Desktop adapters use the coordinator's
`place(node, parent, before)` helper. It records an invisible return anchor the
first time a node moves. Leaving desktop restores those nodes automatically,
then the mobile adapter applies its own layout. This includes future desktop
placements that the mobile adapter does not know about. Mark any new desktop-only
container `data-desktop-slot` so it stays hidden in mobile.

The coordinator also remembers compact disclosure preferences while desktop
temporarily forces sections open. The application still saves those preferences
in its original UI store. Input values, node identities/listeners, request UUIDs,
queued jobs and connection state stay with the single shared application; a
viewport change neither submits work nor resets state.

## Making a desktop-only change

1. Edit `presentation_desktop.css` for arrangement/geometry or
   `presentation_desktop.js` for placement/navigation. Preserve its root scope.
2. Move shared controls using the supplied `place()` helper rather than cloning,
   recreating or detaching them without a return anchor. Keep IDs stable.
3. Leave mobile files, `theme.css`, `style.css` and shared application functions
   alone unless the requirement explicitly involves them. Add no API calls or
   competing state to an adapter.
4. If markup needs another desktop slot, mark it `data-desktop-slot`. Altering
   shared component markup or its ID contract requires checking both modes.
5. Refresh the shell cache version when shipping changed public assets. New files
   must be listed in `mobile/server.py`'s public asset allowlist and `sw.js`'s shell.
6. Run the isolation and responsive checks, including rotation and live jobs.

The deliberately shared presentation dependencies are theme/component styling,
the HTML/control ID contract, shared field/feature renderers and dialog contents,
the coordinator and viewport conditions, plus responsive thumbnail choices.
Changing one of these shared contracts can affect both presentations; the
separation does not make shared component changes mobile-safe automatically.

## Verification

Use fresh output directories. These commands use protocol fixtures, not real GPU
inference, NAS storage, VPN recovery or physical Apple hardware:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/mobile_presentation_browser.py --browser chromium --output /tmp/control-presentation-check
.venv/bin/python tests/manual/mobile_responsive_browser.py --browser chromium --output /tmp/control-responsive-check
.venv/bin/python tests/manual/mobile_generation_browser.py --browser chromium --output /tmp/control-generation-check
.venv/bin/python tests/manual/desktop_gallery_browser.py --browser chromium --output /tmp/control-desktop-gallery-check
.venv/bin/python tests/manual/desktop_viewer_actions_browser.py --browser chromium --output /tmp/control-desktop-viewer-check
.venv/bin/python tests/manual/mobile_saved_editors_browser.py --browser chromium --enlarged --output /tmp/control-enlarged-editors-check
```

Use `--browser webkit` for the other supported test engine. Playwright browser
paths and Linux library requirements remain the same as before this refactor.

To compare with the original presentation assets, export the chosen baseline
without modifying your working checkout:

```bash
mkdir -p /tmp/control-presentation-baseline
git archive 3a7ae41 comfyui_control/mobile/web | tar -x -C /tmp/control-presentation-baseline
.venv/bin/python tests/manual/mobile_desktop_layout_browser.py --browser chromium --output /tmp/control-presentation-parity --desktop-redesign --baseline-web /tmp/control-presentation-baseline/comfyui_control/mobile/web
```

That check compares desktop component skins before/after for empty, offline,
running and portrait/landscape-result states, validates the new desktop geometry,
and compares compact screenshots after a desktop round trip. A one-channel-level
antialiasing tolerance allows browser compositor rounding without permitting
mobile geometry/content changes. The completed separation baseline is `3a7ae41`.

`--desktop-redesign` allows the intentional desktop geometry changes while keeping
shared skins and mobile pixel comparisons mandatory. Without the flag, desktop
geometry parity also applies. Running the layout check without a baseline validates
the current desktop geometry alone.

The desktop gallery check uses 110 fixture images and 15 private prompt records.
It verifies full-width tiles and the exact eight-row cap at all four target widths,
unified comparison controls and their behavior, Advanced below the gallery, six
prompt cards with inset Delete buttons, search/reuse/deletion, centered labels and
a mobile restoration check. It does not replace the mobile pixel/isolation checks.

The desktop viewer check compares original control identities and normal/hover/
disabled computed styles between regular and enlarged previews. It checks the
three-row geometry, scroll bounds, keyboard/collection navigation, actual Save
downloads, nested dialogs, permission and confirmation handling, favourites,
Trash/restore, exact seed/settings reuse, variation, delayed-action targeting and
mobile restoration. Run the saved-editor script both with and without `--enlarged`
to exercise actual Edit/Upscale submissions with the same redacted workflow graphs.

The dedicated isolation check disables the inactive presentation stylesheet and
verifies the active UI is unchanged, checks unique/live controls, and exercises a
desktop-only placement unknown to mobile followed by automatic restoration.

Keep the known old-job equality fixture failure separate from presentation test
results: timing reconciliation adds `seconds_per_iteration: None` to its synthetic
job. Do not remove timing normalization as part of layout work.
