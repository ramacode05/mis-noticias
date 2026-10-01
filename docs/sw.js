// Service worker: permite instalar la app y verla sin conexión.
var VERSION = "v1";
var CACHE = "mis-noticias-" + VERSION;
var BASICOS = [
  "./",
  "index.html",
  "styles.css",
  "app.js",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png"
];

self.addEventListener("install", function (ev) {
  ev.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(BASICOS); }));
  self.skipWaiting();
});

self.addEventListener("activate", function (ev) {
  ev.waitUntil(
    caches.keys().then(function (claves) {
      return Promise.all(claves.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (ev) {
  var req = ev.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Datos y páginas: primero la red (lo más nuevo); si no hay conexión, lo guardado.
  if (url.pathname.indexOf("/data/") !== -1 || req.mode === "navigate" ||
      /\.(js|css|html)$/.test(url.pathname)) {
    var clave = url.pathname.indexOf("/data/") !== -1 ? new Request(url.origin + url.pathname) : req;
    ev.respondWith(
      fetch(req).then(function (resp) {
        if (resp.ok) {
          var copia = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(clave, copia); });
        }
        return resp;
      }).catch(function () {
        return caches.match(clave).then(function (r) { return r || caches.match("index.html"); });
      })
    );
    return;
  }

  // Íconos y demás: primero lo guardado.
  ev.respondWith(caches.match(req).then(function (r) { return r || fetch(req); }));
});
