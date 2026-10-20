/* Only public shell assets are cached. Authenticated responses never enter CacheStorage. */
const CACHE = "comfy-control-mobile-workspace-tools-1";
const SHELL = [
  "/",
  "/app.js",
  "/comparison.js",
  "/prompt_history.js",
  "/image_details.js",
  "/image_actions.js",
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
