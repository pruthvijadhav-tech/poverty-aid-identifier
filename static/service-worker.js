const CACHE_NAME = 'poverty-aid-v1';
const OFFLINE_URL = '/offline';

const ASSETS_TO_CACHE = [
    '/',
    '/track',
    '/corruption',
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

// Install Service Worker
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

// Activate Service Worker
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames
                    .filter(name => name !== CACHE_NAME)
                    .map(name => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

// Fetch Strategy — Network first, cache fallback
self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // Cache successful responses
                if (response && response.status === 200) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed — serve from cache
                return caches.match(event.request).then(cached => {
                    if (cached) return cached;
                    // If nothing in cache show offline message
                    return new Response(`
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>Offline - Poverty Aid Identifier</title>
                            <style>
                                body { font-family: Arial; background: #000080; color: white;
                                    display: flex; align-items: center; justify-content: center;
                                    min-height: 100vh; margin: 0; text-align: center; padding: 20px; }
                                .box { background: rgba(255,255,255,0.1); padding: 30px;
                                    border-radius: 20px; max-width: 300px; }
                                h2 { color: #FF9933; margin-bottom: 15px; }
                                p { font-size: 14px; opacity: 0.9; line-height: 1.6; }
                                .retry { margin-top: 20px; padding: 12px 25px;
                                    background: #FF9933; color: white; border: none;
                                    border-radius: 10px; font-size: 15px; cursor: pointer; }
                            </style>
                        </head>
                        <body>
                            <div class="box">
                                <h2>No Internet Connection</h2>
                                <p>You are currently offline. Please check your internet connection and try again.</p>
                                <p>इंटरनेट कनेक्शन नहीं है। कृपया जांचें।</p>
                                <p>इंटरनेट कनेक्शन नाही. कृपया तपासा.</p>
                                <button class="retry" onclick="window.location.reload()">
                                    Retry / पुनः प्रयास
                                </button>
                            </div>
                        </body>
                        </html>
                    `, { headers: { 'Content-Type': 'text/html' } });
                });
            })
    );
});

// Background sync for offline form submissions
self.addEventListener('sync', event => {
    if (event.tag === 'sync-forms') {
        event.waitUntil(syncForms());
    }
});

async function syncForms() {
    const db = await openDB();
    const forms = await db.getAll('pending-forms');
    for (const form of forms) {
        try {
            await fetch('/submit', {
                method: 'POST',
                body: JSON.stringify(form)
            });
            await db.delete('pending-forms', form.id);
        } catch (e) {
            console.log('Sync failed, will retry');
        }
    }
}