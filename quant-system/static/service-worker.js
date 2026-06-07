/* Alpha Quant — PWA Service Worker v1.0 */
const CACHE_NAME = 'alpha-quant-v1';

/* 앱 껍데기(App Shell) 캐싱 대상 */
const SHELL_URLS = [
  '/',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.json',
];

/* ── Install: 앱 셸 사전 캐싱 ─────────────────────────── */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(SHELL_URLS).catch(() => {
        /* 일부 URL 실패 시 무시하고 설치 계속 */
      });
    })
  );
  self.skipWaiting();
});

/* ── Activate: 구 캐시 정리 ────────────────────────────── */
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

/* ── Fetch: 네트워크 우선, 오프라인 시 캐시 폴백 ─────────
   Streamlit 실시간 데이터(WebSocket, /_stcore/)는 캐싱 제외
   정적 자산(아이콘, manifest)만 캐시 우선
──────────────────────────────────────────────────────── */
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  /* Streamlit 내부 WebSocket/SSE/실시간 경로 → 항상 네트워크 직통 */
  if (
    event.request.method !== 'GET' ||
    url.pathname.startsWith('/_stcore/') ||
    url.pathname.startsWith('/stream') ||
    event.request.headers.get('upgrade') === 'websocket'
  ) {
    return;
  }

  /* 정적 자산: 캐시 우선 → 네트워크 폴백 */
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  /* 그 외 요청: 네트워크 우선 → 오프라인 시 캐시된 / 반환 */
  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match('/').then(r => r || new Response('오프라인 상태입니다.', {status: 503}))
    )
  );
});
