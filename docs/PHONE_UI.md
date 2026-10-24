# Phone UI modernization

Testing branch: `testing/phone-ui-modernization`, based on main `2fb6352`.
The app version remains 1.0.4. This work does not merge or release it.

## Desktop review and Phone integration

| Desktop improvement | Phone behavior |
| --- | --- |
| Shared Heart, Edit, Upscale and virtual Delete | The same component and controls appear beneath completed results and move into the existing viewer. Two columns give every button a 48px minimum touch height. |
| Compare with a second-image gallery | An additional Compare button preserves Phone's New variation action. The existing gallery loader/renderer and comparison dialog are reused. |
| Compact refresh/cleanup icons and prompt chevrons | Workflow/model selectors have adjacent refresh buttons; Gallery uses the same icon. Positive prompts expose idle-only VRAM cleanup and an accessible expansion toggle. |
| Live speed, VRAM, GPU and step metrics | Yellow metrics remain in Phone's existing job dock, including current/total steps. Phone keeps its progress bar, status and Cancel. |
| Compact LoRA controls | Labelled strength sliders and numeric inputs share a row. Phone retains its original metadata-driven slider bounds and true bypass toggles. |
| Stable workflow/model refresh and saved-only picker | Already shared on main; retained with existing DOM identity, drafts, mappings and exact 64-bit seed strings. Refresh icons call the original handlers. |
| Fixed Desktop preview and section/prompt overlays | Desktop retains these arrangements. Phone keeps live previews, native collapsing details and inline expanded prompts in normal page flow. |

Phone also retains Create/Gallery navigation, the fixed Generate dock, prompt
history/favourites, fixed-seed explanation, filenames, image details, saving,
previous/next buttons, swipe handlers and iPhone guidance. Save image gets the
flexible middle column between 48px navigation buttons to avoid narrow-screen
wrapping. No new framework, application state, selection store or backend exists.

## Implementation boundaries

- `presentation_phone.css` scopes every selector to the existing `mobile`
  presentation. Shared `style.css` and `presentation_desktop.css` are unchanged.
  The Desktop breakpoint stays at 1000px width and 600px height.
- The existing placement helper in `presentation_desktop.js` places shared
  image controls and selector/cleanup buttons in both modes. Desktop-specific
  columns, overlays, labels and slider bounds still restore on leaving Desktop.
- One `ComfySavedImageActions` instance follows the explicit current image/version
  between Preview and the viewer. Authentication, capability signatures, stale
  response guards, permissions and collection updates remain shared.
- Edit/Upscale use the existing dialogs, graph validation, pixel-copy upload,
  pending UUID journal, job queue and Generate retry. Opening/cancelling preserves
  generation drafts. Breakpoint transitions close action forms without submitting.
- Compare excludes its source, preserves drafts and selection on cancel, ignores
  late results after close, and uses decoded thumbnails with reduced-motion
  support. Phone uses a bounded native dialog with safe-area/dynamic-viewport
  sizing and square, independently scrolling gallery rows.
- Running Phone jobs keep their existing live dock/preview without saved-image
  actions. Reconnect disables image actions. VRAM cleanup remains idle-only.
- Delete retains confirmation, permissions and metadata-only Wastebin semantics.
  This adds no permanent-delete or Wastebin management interface.
- The new stylesheet is public and included in the bumped service-worker shell.
  Authenticated APIs, prompts and images remain outside CacheStorage.

## Verification

Run from a fresh checkout with its own environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest playwright
.venv/bin/python -m playwright install chromium webkit
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/phone_image_actions_browser.py --browser chromium --output /tmp/phone-actions-chromium
.venv/bin/python tests/manual/phone_image_actions_browser.py --browser webkit --output /tmp/phone-actions-webkit
git diff --check
```

Also run `desktop_image_actions_browser.py`, `mobile_responsive_browser.py`,
`mobile_generate_button_browser.py`, `refresh_stability_browser.py`,
`bypassed_loras_browser.py`, `saved_workflow_picker_browser.py` and
`generate_transition_browser.py` in both engines, each with a fresh `--output`
directory. Linux browser system libraries may be required. Node enables the
optional shared-JS tests; it is not an application dependency.

The Phone fixture uses touch input at 320×568, 390×844, 430×932, 768×1024 and
844×390, plus Desktop round trips. It verifies touch dimensions, overflow, Compare
source selection, square scrolling rows, late gallery responses after cancel,
native details, prompt DOM identity/drafts, exact seeds, New variation,
Edit/Upscale pixel/parameter targeting, uncertain UUID retry, persisted Favourites,
confirmed/cancelled virtual Delete and disabled offline actions.

The historical Phone pixel-parity script describes an earlier Desktop-only port;
this branch intentionally changes Phone presentation. Frozen shared-asset tests
and Desktop layout/geometry checks remain in force. These fixtures exercise actual
application HTTP routes and a local ComfyUI protocol stub. They do not prove real
GPU/model inference, physical iPhone/Android behavior, mobile keyboards, safe-area
hardware, NAS/VPN or installed custom-node compatibility. Test those before merge.
