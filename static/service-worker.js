

const CACHE_NAME = 'pai-offline-v1';
const CACHE_URLS = [
  '/',
  '/home',
  '/eligibility',
  '/static/offline-scoring.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.all(
        CACHE_URLS.map((url) =>
          cache.add(url).catch((err) => {
            // Don't let one missing/unreachable URL block the whole install
            console.warn('Service worker: could not cache', url, err);
          })
        )
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Never cache/intercept API calls or POST requests — those need real
  // server responses (chatbot, OCR, complaint filing, form submission).
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.pathname.startsWith('/chatbot') ||
      url.pathname.startsWith('/ocr-extract') ||
      url.pathname.startsWith('/sms-webhook') ||
      url.pathname.startsWith('/voice-webhook') ||
      url.pathname.startsWith('/voice-collect') ||
      url.pathname.startsWith('/admin') ||
      url.pathname.startsWith('/volunteer')) {
    return;
  }

  // Network-first for pages (so people online always see fresh content),
  // falling back to cache when offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('/home')))
  );
});