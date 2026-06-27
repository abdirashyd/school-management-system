// Service Worker for EduNexus PWA
const CACHE_NAME = 'edunexus-v9';

// Files to cache (only those that definitely exist)
const FILES_TO_CACHE = [
    '/',
    '/static/css/style.css',
    '/static/manifest.json',
    '/static/icons/icon-192x192-v2.png',
    '/static/icons/icon-512x512-v2.png'
];

// Install event - cache files individually (one failure won't break everything)
self.addEventListener('install', (event) => {
    console.log('Service Worker: Installing...');
    
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('Service Worker: Caching files');
            // Use Promise.allSettled or individual catches to prevent one failure from breaking everything
            return Promise.all(
                FILES_TO_CACHE.map((url) => {
                    return cache.add(url).catch((err) => console.error(`Failed to cache ${url}:`, err));
                })
            );
        }).then(() => {
            console.log('Service Worker: Installation complete');
            return self.skipWaiting();
        })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('Service Worker: Activating...');
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cache => {
                    if (cache !== CACHE_NAME) {
                        console.log('Service Worker: Clearing old cache', cache);
                        return caches.delete(cache);
                    }
                })
            );
        }).then(() => {
            console.log('Service Worker: Activated');
            return self.clients.claim();
        })
    );
});

// Fetch event - network first, cache fallback
self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request)
            .catch(() => {
                return caches.match(event.request)
                    .then(response => {
                        if (response) {
                            return response;
                        }
                        // Return a simple offline message for HTML requests
                        if (event.request.headers.get('accept').includes('text/html')) {
                            return new Response(`
                                <!DOCTYPE html>
                                <html>
                                <head><title>Offline</title></head>
                                <body style="text-align:center;padding:50px;font-family:sans-serif;">
                                    <h1>You're Offline</h1>
                                    <p>Please check your internet connection.</p>
                                    <button onclick="location.reload()">Try Again</button>
                                </body>
                                </html>
                            `, {
                                status: 200,
                                headers: new Headers({ 'Content-Type': 'text/html' })
                            });
                        }
                        return new Response('You are offline. Please check your connection.', {
                            status: 200,
                            headers: new Headers({ 'Content-Type': 'text/plain' })
                        });
                    });
            })
    );
});