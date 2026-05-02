// Minimal service worker for PWA standalone app
// No caching - all requests go to network only

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => caches.delete(cacheName))
      );
    })
  );
  self.clients.claim();
});

// Network only - no caching
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
