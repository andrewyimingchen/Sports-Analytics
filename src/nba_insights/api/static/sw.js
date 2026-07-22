// App shell is network-first so a deployed UI cannot stay pinned behind an
// older service worker. The cache is only an offline fallback.
const SHELL_CACHE = "nba-insights-shell-v11";
const SHELL = ["/app/", "/app/index.html", "/app/manifest.json", "/app/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
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
  }
});
