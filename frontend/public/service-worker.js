const CACHE = "rootdrive-shell-__ROOTDRIVE_VERSION__";
const SHELL = ["/", "/offline.html", "/manifest.webmanifest"];
function asset(url) {
  return url.origin === self.location.origin && !url.search && /^\/assets\/(?:[^/]+-[a-zA-Z0-9_-]{6,}\.(?:js|css|mjs)|icons\/[^/]+\.(?:webp|png)|fonts\/[^/]+\.(?:woff2?))$/.test(url.pathname);
}
self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);
    const response = await cache.match("/");
    const html = await response.text();
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"?#]+\.(?:js|css))"/g)].map((match) => match[1]);
    await cache.addAll(assets);
  })());
});
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key.startsWith("rootdrive-shell-") && key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/share/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(async () => (await caches.match(url.pathname === "/" ? "/" : "/offline.html")) || Response.error()));
    return;
  }
  if (!asset(url)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(event.request);
    if (cached) return cached;
    const response = await fetch(event.request);
    if (response.ok && response.type === "basic") {
      await cache.put(event.request, response.clone());
      const keys = await cache.keys();
      const entries = keys.filter((request) => asset(new URL(request.url)));
      for (const request of entries.slice(0, Math.max(0, entries.length - 120))) await cache.delete(request);
    }
    return response;
  })());
});
