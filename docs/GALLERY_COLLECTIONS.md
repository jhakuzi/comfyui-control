# Shared Gallery library

Desktop and Phone share Refresh, Wastebin (bin) and Favourites (heart) controls.
They have accessible names and 48px touch targets, wrapping together on narrow
screens. Devices connected to the same controller and configured output folder
see the same heart marks and bin contents, including existing marks/deletions.

ComfyUI Control has one shared WebUI access boundary/password. Clients admitted
by those access rules share the image library. Authentication, browser identity,
Host/Origin checks, CSP and no-cache policies still apply. Live jobs, cancellation,
prompt history and the optional image-settings sharing preference keep their
existing browser boundaries. Initial image Delete permission is unchanged.

## Collection views and stable layout

Both collections use the shared thumbnail renderer, native modal and yellow theme.
Desktop popups are clamped to the viewport up to 1200×900 and use four columns.
Phone keeps its original collection bounds and two columns. Thumbnail rows stay
square and scroll inside the dialog. Favourites opens the existing image viewer;
unmarking removes that entry and safely advances/closes its viewer. Wastebin uses
its thumbnail-only preview with filename, stored error and storage notices.

Marked Gallery/Favourites tiles show a yellow heart with an accessible description.
Mark changes preserve thumbnail/button DOM and generation drafts. The image viewer
no longer inserts a temporary “Saving…” row or clears capability prose for an
unchanged selection. Confirmed heart saves update existing capabilities directly.
Popup loading uses accessible busy state and stable reserved status/grid geometry,
without flashing “Loading images…” or an early empty-state message. Errors remain
visible. Local metadata edits invalidate both pending reads and the Gallery revision,
so another device returning to an earlier server state still reconciles correctly.

## Clear Bin

Clear Bin appears only in Wastebin and is disabled while empty/loading/clearing.
It captures the displayed token list before showing an in-app confirmation, including the
image count and the fact that original files will be removed permanently. Cancel
sends no request. Confirmation calls the existing `POST /api/trash/empty` with
`confirm: true` and that exact token snapshot. Images binned later are not added.

The server authorizes every token against the current output scope before doing
filesystem work. It retains each record’s original owner for source-ownership and
legacy-worker validation. Existing exact-file, root/parent directory, symlink,
regular-file, replacement and bounded NFS-worker guards remain. Failed deletions
stay in Wastebin with their errors, while successful records become tombstones.
The dialog refreshes after a confirmed result and reports partial failures.

Duplicate Clear/Refresh actions are disabled while deletion runs. A lost or invalid
response shows guidance to Refresh and is never automatically resubmitted. Close
dismisses the view; an already-confirmed deletion continues. Opening/previewing a
collection never restores or removes files. No restore control was added.

## Desktop bulk selection

Select two images and Select share the former selection-button width, while Compare
keeps the other half. Select enables any number of visible Gallery images with a
checkmarks. Right-click a selected thumbnail to open Favourite selected
and Delete selected for the whole selection. These actions no longer occupy a
permanent button row. Desktop hides its Gallery heading/introductory copy and the
selection count/hint; feedback overlays the page to avoid shifting the grid.
Phone headings/layout remain unchanged. Shift+F10 opens the same menu from a focused selection; use
arrows/Home/End, Escape or Tab to navigate/dismiss it. Outside clicks, scroll,
resize and stale selections also dismiss it. Favourite selected explicitly adds every selection to Favourites
without toggling existing hearts off. Delete selected asks once and moves only the
captured image versions to Wastebin; original files remain in place.

Bulk and Compare selection are mutually exclusive. Requests use the existing image
action API serially and reconcile through the controller. Permission/stale errors
stay selected and report their reason. A lost response stops further requests and
requires Gallery reconciliation before retry; there is no automatic write retry.
Leaving Gallery/Desktop, authentication changes or backgrounding clears selection
and stops further batch requests. Refresh drops removed/replaced versions. Phone
keeps its existing comparison row and normal image opening behavior.

## Confirmations and unavailable originals

Delete, bulk Delete and Clear Bin use one themed in-app alertdialog. Cancel is
focused initially; Cancel/Escape sends no write. Confirmations are bound to the
captured image versions or Bin tokens, and stale views cannot authorize an action.

A Bin preview depends on its original file. If unavailable, the tile shows its
filename and a preview-unavailable label with storage guidance. On explicitly
confirmed Clear Bin, an already-missing original can complete its tombstone only
if the configured root and every saved parent directory still match and are
rechecked. An NFS remount can change the Linux device number while preserving
inode IDs. For an already-missing leaf only, matching inode IDs throughout the
saved parent chain on a currently mounted NFS/NFS4 root can complete the record;
nested device changes are rejected and the current directories/mount are rechecked.
Nothing is unlinked for that entry. Existing files retain the full original
fingerprint check, including the saved device ID. Missing/changed storage or parents,
symlinks, replacements, ownership and permission failures remain in the Bin.
Identity-mismatch errors now explain why a missing-file record was retained.
Listing/previewing does not silently prune records.

## Data and shared implementation

- `feature_gallery_library.js/css` owns transient presentation. The controller
  supplies transport, `renderImages`, `openImage` and the existing permanent-delete
  transport. No second selection store, queue or submission path is created.
- Favourites uses `GET /api/gallery?favourites=1&refresh=1`; the recent Gallery stays
  at 200, while marked references remain available beyond recent 200/retained 500.
  Existing scan, mark and metadata-size bounds remain in effect.
- The existing version-2 sidecar is retained. A validated scan folds old browser
  marks into a shared bucket for that output scope using atomic worker writes.
  Other outputs, missing/replaced versions and corrupt metadata are preserved.
  Explicit unmarking removes legacy copies of that image to prevent resurrection.
- Wastebin uses the existing `/api/trash` list, thumbnail, restore and permanent
  deletion APIs within the shared output scope. Normal and legacy entries retain
  their original record ownership and identities. Legacy listing now discovers all
  valid owners in the same scope; legacy reads/writes still validate the original
  owner. Deleted thumbnails remain metadata-free 384px previews.
- Popups read on open/Refresh, with no new polling. The existing Gallery timer is
  unchanged. Close, navigation, lifecycle and authentication invalidate reads.
  Private grids clear on sign-in; late responses cannot repaint a different view.
  Thumbnails retain decoding, fallback, loading rings and reduced-motion behavior.
- Public assets remain allowlisted. Shell cache is
  `comfy-control-desktop-gallery-bulk-4`; APIs/images remain uncached.

Restart the app for the Python library change, then reload Desktop and Phone.
Sharing applies to the same controller/output, independently of whether a device
uses the LAN address or localhost to reach that controller.

## Verification

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/gallery_collections_browser.py --browser chromium --output /tmp/gallery-collections-chromium
.venv/bin/python tests/manual/gallery_collections_browser.py --browser webkit --output /tmp/gallery-collections-webkit
.venv/bin/python tests/manual/gallery_library_updates_browser.py --browser chromium --output /tmp/shared-library-chromium
.venv/bin/python tests/manual/gallery_library_updates_browser.py --browser webkit --output /tmp/shared-library-webkit
git diff --check
```

Also run Desktop/Phone actions, responsive, Gallery-sync and comparison fixtures
in both engines. Collection checks cover five viewport sizes, empty/multiple rows,
decoding, badge identity, stale/error/auth guards, older-favourite viewing/Compare
and preserved drafts. The update fixture holds requests and measures consecutive
frames for both flicker paths; signs in two independent clients; tests bidirectional
marks, shared bins, confirmation cancellation, newly added entries outside a
snapshot, partial failure, duplicate blocking and a lost reply after actual deletion.
Python tests cover legacy mark/bin migration, shared authenticated access, denied
unauthenticated reads/deletion, private live jobs/history, changed versions/output,
confirmation, corruption and local/network exact-file safety.

These are real application HTTP/filesystem fixtures without real GPU inference,
physical Phone or NAS/VPN hardware verification. Permanent-deletion tests act only
on their generated fixture images.
