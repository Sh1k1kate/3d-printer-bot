self.addEventListener('install', e => {
  e.waitUntil(caches.open('tracker-cache-v1').then(cache => {
    return cache.addAll(['/', '/tracker', '/static/manifest.json']);
  }));
});
self.addEventListener('fetch', e => {
  e.respondWith(caches.match(e.request).then(response => response || fetch(e.request)));
});
