const VERSION = 'race-pwa-3';
const PRECACHE = [
  'index.html',
  'manifest.json',
  'assets/pwa-icon-192.png',
  'assets/pwa-icon-512.png',
  'assets/pwa-register.js',
  'assets/site.css',
  'assets/site-sidebar.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith('race-pwa-') && k !== VERSION)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('api/')) {
    event.respondWith(fetch(request));
    return;
  }
  event.respondWith(
    fetch(request)
      .then((res) => {
        if (res && res.ok) return res;
        return caches.match(request);
      })
      .catch(() => caches.match(request))
      .then((res) => res || caches.match('index.html'))
  );
});
