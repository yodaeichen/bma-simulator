// Service Worker des BMA Simulators: macht Ausbilderansicht und Anzeigen als App installierbar
// und liefert eine Hinweisseite, wenn der Server nicht erreichbar ist.
// Seiten und der Zustand der Anlage werden nie zwischengespeichert, nur Stil, Skripte und Symbole.
var VERSION = "__VERSION__";
var CACHE = "bma-" + VERSION;
var PRECACHE = ["/offline", "/static/icons/icon-192.png"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) { return cache.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key.indexOf("bma-") === 0 && key !== CACHE; }).map(function (key) { return caches.delete(key); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf("/static/") === 0) {
    // Erst aus dem Zwischenspeicher antworten, im Hintergrund auffrischen
    event.respondWith(caches.open(CACHE).then(function (cache) {
      return cache.match(request).then(function (hit) {
        var fresh = fetch(request).then(function (response) {
          if (response.ok) cache.put(request, response.clone());
          return response;
        });
        if (hit) { fresh.catch(function () {}); return hit; }
        return fresh;
      });
    }));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(function () { return caches.match("/offline"); }));
  }
});
