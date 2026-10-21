# WebUI presentation layers

ComfyUI Control serves one buildless application, with independent mobile and
desktop presentation adapters. This separation preserves the appearance and
behavior at `cddb86b`; it does not introduce another desktop design or backend.

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
```

Use `--browser webkit` for the other supported test engine. Playwright browser
paths and Linux library requirements remain the same as before this refactor.

To compare with the original presentation assets, export the chosen baseline
without modifying your working checkout:

```bash
mkdir -p /tmp/control-presentation-baseline
git archive cddb86b comfyui_control/mobile/web | tar -x -C /tmp/control-presentation-baseline
.venv/bin/python tests/manual/mobile_desktop_layout_browser.py --browser chromium --output /tmp/control-presentation-parity --baseline-web /tmp/control-presentation-baseline/comfyui_control/mobile/web
```

That check compares desktop geometry and component skins before/after for empty,
offline, running and portrait/landscape-result states, and compares compact
screenshots after a desktop round trip. A one-channel-level antialiasing tolerance
allows browser compositor rounding without permitting geometry/content changes.
The dedicated isolation check disables the inactive presentation stylesheet and
verifies the active UI is unchanged, checks unique/live controls, and exercises a
desktop-only placement unknown to mobile followed by automatic restoration.

Keep the known old-job equality fixture failure separate from presentation test
results: timing reconciliation adds `seconds_per_iteration: None` to its synthetic
job. Do not remove timing normalization as part of layout work.
