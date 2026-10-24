/* Only public shell assets are cached. Authenticated responses never enter CacheStorage. */
const CACHE = "comfy-control-mobile-gallery-library-3";
const SHELL = [
  "/",
  "/app.js",
  "/feature_generate.js",
  "/feature_generate.css",
  "/feature_image_actions.js",
  "/feature_image_api.js",
  "/feature_image_workflows.js",
  "/feature_gallery_library.js",
  "/feature_gallery_library.css",
  "/presentation_desktop.js",
  "/presentation_desktop.css",
  "/presentation_phone.css",
  "/comparison.js",
  "/prompt_history.js",
  "/image_details.js",
  "/style.css",
  "/icon.png",
  "/manifest.webmanifest",
];
self.addEventListener("install", (event) =>
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  ),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) => key.startsWith("comfy-control-mobile-") && key !== CACHE,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    !SHELL.includes(url.pathname)
  )
    return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(url.pathname)),
  );
});
