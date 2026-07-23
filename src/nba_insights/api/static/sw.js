// App shell is network-first so a deployed UI cannot stay pinned behind an
// older service worker. The cache is only an offline fallback.
const SHELL_CACHE = "nba-insights-shell-v20";
const PUBLIC_DATA_CACHE = "nba-insights-public-data-v1";
const SHELL = [
  "/app/",
  "/app/index.html",
  "/app/manifest.json",
  "/app/icon.svg",
  "/app/icon-192.png",
  "/app/icon-512.png",
  "/app/maskable-512.png",
  "/app/apple-touch-icon.png",
  "/app/fonts/dm-mono-400.ttf",
  "/app/fonts/dm-mono-500.ttf",
  "/app/fonts/manrope-400.ttf",
  "/app/fonts/manrope-500.ttf",
  "/app/fonts/manrope-600.ttf",
  "/app/fonts/manrope-700.ttf",
  "/app/fonts/oswald-500.ttf",
  "/app/fonts/oswald-600.ttf",
  "/app/fonts/oswald-700.ttf",
];
const PUBLIC_DATA = [
  /^\/meta$/,
  /^\/league\/pulse$/,
  /^\/games$/,
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => ![SHELL_CACHE, PUBLIC_DATA_CACHE].includes(k))
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (SHELL.includes(url.pathname)) {
    e.respondWith(
      fetch(e.request).then((response) => {
        const copy = response.clone();
        caches.open(SHELL_CACHE).then((cache) => cache.put(e.request, copy));
        return response;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  const publicData = e.request.method === "GET"
    && url.origin === self.location.origin
    && PUBLIC_DATA.some((pattern) => pattern.test(url.pathname))
    && !e.request.headers.has("Authorization")
    && !e.request.headers.has("X-API-Key");
  if (publicData) {
    e.respondWith(
      fetch(e.request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(PUBLIC_DATA_CACHE).then((cache) => cache.put(e.request, copy));
        }
        return response;
      }).catch(() => caches.match(e.request))
    );
  }
});
