/* Service Worker של mishelanu: קבצי הבסיס שמורים לעבודה ללא רשת, ותמונות שכבר נצפו נשארות בזיכרון.
   כשמשנים קבצים בתיקיית static — לעדכן את VERSION כדי שהשינוי יגיע לטלפונים. */
var VERSION = 'mishelanu-v10';
var PRECACHE = [
  './',
  './manifest.json',
  './static/css/site.css',
  './static/js/pwa.js',
  './static/js/site-sidebar.js',
  './static/vendor/leaflet/leaflet.css',
  './static/vendor/leaflet/leaflet.js',
  './static/icons/icon-192.png',
  './static/icons/icon-512.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(VERSION)
      .then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys
          .filter(function (key) { return key.indexOf('mishelanu-') === 0 && key !== VERSION; })
          .map(function (key) { return caches.delete(key); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);
  var scopePath = new URL('.', self.location.href).pathname;
  if (url.origin !== self.location.origin || url.pathname.indexOf(scopePath) !== 0) return;

  if (req.mode === 'navigate') {
    // דפים: קודם כל הרשת, ובלי רשת — דף הבית השמור
    event.respondWith(fetch(req).catch(function () { return caches.match('./'); }));
    return;
  }

  var path = url.pathname.slice(scopePath.length - 1);
  if (path.indexOf('/static/') === 0 || path.indexOf('/uploads/') === 0) {
    // קבצים ותמונות: קודם כל העותק השמור, וברקע העותק מתעדכן מהרשת
    event.respondWith(
      caches.match(req).then(function (cached) {
        var refresh = fetch(req).then(function (res) {
          if (res && res.ok) {
            caches.open(VERSION).then(function (cache) { cache.put(req, res.clone()); });
          }
          return res;
        });
        return cached || refresh;
      })
    );
  }
});
