const NAV_CACHE = 'violeta-nav-v5';
const APP_SHELL_CACHE = 'violeta-app-shell-v2';
const NAV_CACHE_TTL_MS = 300000;
const PREFETCH_LIMIT = 12;
const OFFLINE_URL = '/static/offline.html';
const APP_SHELL_ASSETS = [
  OFFLINE_URL,
  '/manifest.json',
  '/manifest.webmanifest',
  '/static/images/favicon.png',
  '/static/images/pwa/icon-192.png',
  '/static/images/pwa/icon-512.png',
  '/static/images/pwa/maskable-512.png',
];
const EXCLUDED_PATHS = new Set([
  '/logout',
  '/service-worker.js',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/force-password-reset',
]);

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_SHELL_CACHE);
    await cache.addAll(APP_SHELL_ASSETS);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((name) => (
          (name.startsWith('violeta-nav-') && name !== NAV_CACHE)
          || (name.startsWith('violeta-app-shell-') && name !== APP_SHELL_CACHE)
        ))
        .map((name) => caches.delete(name)),
    );
    await self.clients.claim();
  })());
});

function normalizeUrl(input) {
  const url = new URL(input, self.location.origin);
  url.hash = '';
  return url.toString();
}

function isCacheableNavigationUrl(url) {
  const parsed = new URL(url, self.location.origin);
  const isSafetyPath = parsed.pathname === '/safety' || parsed.pathname.startsWith('/safety/');
  return parsed.origin === self.location.origin && !EXCLUDED_PATHS.has(parsed.pathname) && !isSafetyPath;
}

async function storeNavigationResponse(url, response) {
  const cache = await caches.open(NAV_CACHE);
  const body = await response.blob();
  const headers = new Headers(response.headers);
  headers.set('X-Violeta-Cached-At', String(Date.now()));
  const cachedResponse = new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
  await cache.put(url, cachedResponse);
}

async function fetchAndCacheNavigation(url) {
  if (!isCacheableNavigationUrl(url)) return null;
  const requestedUrl = new URL(url, self.location.origin);
  const response = await fetch(requestedUrl.toString(), {
    method: 'GET',
    credentials: 'include',
    headers: { 'X-Violeta-Prefetch': '1' },
  });
  const contentType = response.headers.get('content-type') || '';
  if (!response.ok || !contentType.includes('text/html')) {
    return response;
  }
  const finalUrl = new URL(response.url || requestedUrl.toString(), self.location.origin);
  if (response.redirected && finalUrl.pathname !== requestedUrl.pathname) {
    return response;
  }
  await storeNavigationResponse(normalizeUrl(requestedUrl.toString()), response.clone());
  return response;
}

async function getFreshNavigationResponse(url) {
  const cache = await caches.open(NAV_CACHE);
  const cached = await cache.match(url);
  if (!cached) return null;
  const cachedAt = Number(cached.headers.get('X-Violeta-Cached-At') || '0');
  if (!cachedAt || (Date.now() - cachedAt) > NAV_CACHE_TTL_MS) {
    await cache.delete(url);
    return null;
  }
  return cached;
}

async function clearNavigationCache() {
  await caches.delete(NAV_CACHE);
}

async function getOfflineShell() {
  const cache = await caches.open(APP_SHELL_CACHE);
  const offlineResponse = await cache.match(OFFLINE_URL);
  if (offlineResponse) return offlineResponse;
  return new Response('Sin conexion', {
    status: 503,
    statusText: 'Offline',
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'VIOLETA_CLEAR_NAV_CACHE') {
    event.waitUntil(clearNavigationCache());
    return;
  }
  if (data.type !== 'VIOLETA_PREFETCH_NAV' || !Array.isArray(data.urls)) {
    return;
  }
  const urls = data.urls
    .map((url) => normalizeUrl(url))
    .filter((url, index, arr) => arr.indexOf(url) === index)
    .filter(isCacheableNavigationUrl)
    .slice(0, PREFETCH_LIMIT);
  event.waitUntil(Promise.all(urls.map((url) => fetchAndCacheNavigation(url).catch(() => null))));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET' || request.mode !== 'navigate') {
    return;
  }
  if (!isCacheableNavigationUrl(request.url)) {
    return;
  }
  const normalizedUrl = normalizeUrl(request.url);
  event.respondWith((async () => {
    const cached = await getFreshNavigationResponse(normalizedUrl);
    if (cached) {
      event.waitUntil(fetchAndCacheNavigation(normalizedUrl).catch(() => null));
      return cached;
    }
    try {
      const networkResponse = await fetch(request);
      const contentType = networkResponse.headers.get('content-type') || '';
      if (networkResponse.ok && contentType.includes('text/html')) {
        const finalUrl = new URL(networkResponse.url || normalizedUrl, self.location.origin);
        const originalUrl = new URL(normalizedUrl, self.location.origin);
        if (!(networkResponse.redirected && finalUrl.pathname !== originalUrl.pathname)) {
          event.waitUntil(storeNavigationResponse(normalizedUrl, networkResponse.clone()));
        }
      }
      return networkResponse;
    } catch (error) {
      const stale = await caches.open(NAV_CACHE).then((cache) => cache.match(normalizedUrl));
      if (stale) return stale;
      return getOfflineShell();
    }
  })());
});
