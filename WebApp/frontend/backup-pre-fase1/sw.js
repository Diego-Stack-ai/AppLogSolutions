const CACHE_NAME = 'log-solution-v6.037';
const ASSETS = [
    './',
    './index.html',
    './login.html',
    './dashboard.html',
    './gestione.html',
    './inserimento.html',
    './impostazioni.html',
    './visualizzazione.html',
    './mappa_consegne.html',
    './mappa_google.html',
    './elaborazione.html',
    './firebase-config.js',
    './manifest.json',
    './img/logo.png',
    'https://fonts.googleapis.com/icon?family=Material+Icons+Round'
];

// 1. Installazione: cache solo asset statici puri
self.addEventListener('install', (event) => {
    console.log(`[SW ${CACHE_NAME}] Installazione cache...`);
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
    );
    self.skipWaiting();
});

// 2. Attivazione: elimina TUTTE le cache vecchie + claim immediato
self.addEventListener('activate', (event) => {
    console.log(`[SW ${CACHE_NAME}] Attivazione: pulizia cache vecchie...`);
    event.waitUntil(
        caches.keys().then((cacheNames) =>
            Promise.all(
                cacheNames.map((name) => {
                    if (name !== CACHE_NAME) {
                        console.log('[SW] Eliminazione cache vecchia:', name);
                        return caches.delete(name);
                    }
                })
            )
        ).then(() => self.clients.claim())
    );
});

// 3. SKIP_WAITING via messaggio (forza aggiornamento immediato)
self.addEventListener('message', (event) => {
    if (event.data === 'SKIP_WAITING' || event.data?.type === 'SKIP_WAITING') {
        console.log(`[SW ${CACHE_NAME}] SKIP_WAITING ricevuto ï¿½ attivazione forzata.`);
        self.skipWaiting();
    }
});

// 4. Fetch: strategie differenziate per tipo di risorsa
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = event.request.url;

    // Ignora richieste non http (es: chrome-extension://) per evitare errori
    if (!url.startsWith('http')) return;

    // ? Bypass totale: Firebase, Firestore, Storage, autenticazione, Sentry, server locale ?
    if (
        url.includes('firebaseio.com') ||
        url.includes('firestore.googleapis.com') ||
        url.includes('firebasestorage.googleapis.com') ||
        url.includes('storage.googleapis.com') ||
        url.includes('identitytoolkit.googleapis.com') ||
        url.includes('securetoken.googleapis.com') ||
        url.includes('maps.googleapis.com') ||
        url.includes('sentry') ||
        url.includes('localhost') ||
        url.includes('127.0.0.1') ||
        url.includes('.json')
    ) {
        return;
    }

    if (event.request.mode === 'navigate' || url.endsWith('.html')) {
        event.respondWith(
            fetch(event.request.url, { cache: 'no-store' })
                .then((response) => {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
                    return response;
                })
                .catch(() => caches.match(event.request))
        );
        return;
    }

    // ? Network-First: JS e CSS (sempre freschi, fallback offline) ?
    if (url.match(/\.(js|css)(\?|$)/)) {
        event.respondWith(
            fetch(event.request.url, { cache: 'no-store' })
                .then((response) => {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
                    return response;
                })
                .catch(() =>
                    caches.match(event.request).then((res) => {
                        return res || new Response('', { status: 404 });
                    })
                )
        );
        return;
    }

    // ? Cache-First: immagini e altri asset statici (cambiano raramente) ?
    event.respondWith(
        caches.match(event.request).then((cached) => {
            if (cached) return cached;
            return fetch(event.request).then((response) => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
                return response;
            });
        })
    );
});
