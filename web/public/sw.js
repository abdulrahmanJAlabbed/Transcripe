/* Transcripe app shell — network-first, cache fallback, /api never cached. */
const CACHE = "transcripe-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api")) return;

  // Fonts CDN: cache-first, they're immutable.
  if (url.hostname.endsWith("gstatic.com") || url.hostname.endsWith("googleapis.com")) {
    e.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        const fresh = await fetch(e.request);
        if (fresh.ok || fresh.type === "opaque") cache.put(e.request, fresh.clone());
        return fresh;
      })
    );
    return;
  }

  if (url.origin !== location.origin) return;

  /* Built assets carry a content hash in the filename, so a given URL's bytes
     can never change — a new build arrives under a new name. Cache-first means
     a repeat visit costs no request at all, and works offline. */
  if (url.pathname.includes("/assets/")) {
    e.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        const fresh = await fetch(e.request);
        if (fresh.ok) cache.put(e.request, fresh.clone());
        return fresh;
      })
    );
    return;
  }

  // Same-origin app shell: network-first so updates land, cache when offline.
  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      try {
        const fresh = await fetch(e.request);
        if (fresh.ok) cache.put(e.request, fresh.clone());
        return fresh;
      } catch (err) {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        if (e.request.mode === "navigate") {
          const shell = await cache.match(self.registration.scope);
          if (shell) return shell;
        }
        throw err;
      }
    })
  );
});
