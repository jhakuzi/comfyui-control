# Gallery collection previews

Desktop and Phone share a toolbar with Refresh, Wastebin (bin) and Favourites
(heart) icons. Each icon has an accessible name and a 48px touch target. The
toolbar wraps within narrow screens while keeping its three buttons together.

Both collections use a native modal with the existing yellow theme, square
thumbnail rows, an independently scrolling grid, Refresh and Close. Favourites
opens the existing image viewer and its actions. Removing a heart removes that
image from the collection and advances/closes its viewer safely. Wastebin shows
the authenticated browser's deleted entries; selecting a tile opens a larger
thumbnail preview, filename and any stored error/storage notice. Back returns to
the grid. Browsing never restores or permanently deletes files.

Marked Gallery/Favourites tiles have a small yellow heart, with an accessible
description. Confirmed mark changes update the badge in place without replacing
the button or image, changing selection, or losing generation drafts. A stale
Gallery response cannot overwrite a newer confirmed mark.

## Shared implementation

- `feature_gallery_library.js` owns temporary collection presentation. The
  application supplies transport, `renderImages` and `openImage`; there is no
  second selection store, generation implementation or submission path.
- `feature_gallery_library.css` styles the shared toolbar, dialog and badge.
  Existing shared skins and Desktop/Phone arrangement styles remain intact.
- `app.js` supplies Favourites from `GET /api/gallery?favourites=1&refresh=1` and
  Wastebin from the existing `GET /api/trash`. Wastebin entries use only their
  private `/api/trash/{token}/thumbnail` URLs, never normal image/reuse endpoints.
  Deleted thumbnails have the backend's 384px preview resolution.
- Favourites filters the existing private Keep marks by exact saved-file version.
  The bounded scan retains marked references beyond the recent 200 and ordinary
  500-image pool, so older favourites remain available after refresh/restart and
  can use the existing viewer, actions and Compare. The recent Gallery stays at
  200. Existing 2,000-mark and 10,000-scanned-entry limits remain in effect.
- Existing filesystem/NFS workers, scope/version validation and metadata permission
  rules remain authoritative. Another browser cannot read these private marks or
  Wastebin records/thumbnails. Deleted images remain excluded from Gallery and
  Favourites; originals stay in place.
- Popups load on open or explicit Refresh, with no new polling. The existing
  Gallery timer remains unchanged. Close, tab/lifecycle changes and authentication
  invalidate reads; late responses cannot repaint a closed or different collection.
  Failed refreshes retain the current grid and show a retry message. Thumbnails
  reuse the existing decode/fallback/spinner/reduced-motion behavior.
- The two new public assets are allowlisted and included in service-worker shell
  cache `comfy-control-mobile-gallery-library-1`. Private APIs/images stay uncached.

Restart a running app after installing this update, then reload both WebUI pages:
the Favourites query also updates the Python backend.

## Verification

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tests/manual/gallery_collections_browser.py --browser chromium --output /tmp/gallery-collections-chromium
.venv/bin/python tests/manual/gallery_collections_browser.py --browser webkit --output /tmp/gallery-collections-webkit
git diff --check
```

Also run Desktop/Phone image actions, responsive behavior, Gallery synchronization
and comparison scripts in both engines. The collection fixture covers 1440×1000,
390×844, 320×568, 844×390 and 768×1024; icon ordering and size, empty/multiple rows,
decoded previews, in-place badges, a stale Gallery response after a mark, stale
collection responses after switching, failed refresh/retry, private browser
isolation, sign-in clearing, original files and preserved drafts. It also views
and compares an older favourite beyond recent 200. Python tests exercise older
marks beyond both recent and retained limits on local/network output, restart,
other-browser scans, changed versions, deleted exclusions and private thumbnails.

These checks use real application HTTP APIs with local protocol/filesystem
fixtures, not real GPU inference, physical Phones or NAS/VPN hardware.
