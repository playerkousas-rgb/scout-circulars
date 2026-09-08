/* Anonymous Web Push service worker for Scout Circulars. */
'use strict';

// Kept in sync with manifest.webmanifest / icons/. See README「圖示」.
const NOTIFICATION_ICON = '/icons/notification-192.png';
const NOTIFICATION_BADGE = '/icons/badge-96.png';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

function asPayload(raw) {
  const fallback = {
    title: '🔔 香港童軍通告',
    body: '點擊查看通告',
    url: '/',
    tag: 'scout-circulars-personal',
  };
  function libraryResultUrl(value) {
    try {
      const parsed = new URL(String(value || ''), self.location.origin);
      // A valid new payload must point back to this library and carry its
      // opaque result filter. This prevents an old/malformed payload from
      // bypassing the card + bookmark flow by opening a PDF or another site.
      if (parsed.origin !== self.location.origin || !parsed.searchParams.get('n')) return fallback.url;
      return parsed.href;
    } catch (_) {
      return fallback.url;
    }
  }
  if (!raw) return fallback;
  try {
    const value = raw.json();
    if (!value || typeof value !== 'object') return fallback;
    return {
      title: typeof value.title === 'string' && value.title ? value.title : fallback.title,
      body: typeof value.body === 'string' ? value.body : fallback.body,
      url: libraryResultUrl(value.url),
      tag: typeof value.tag === 'string' && value.tag ? value.tag.slice(0, 120) : fallback.tag,
      count: Number(value.count) || 1,
      batchDate: typeof value.batchDate === 'string' ? value.batchDate : '',
      silent: value.silent === true,
    };
  } catch (_) {
    try {
      const title = raw.text();
      return { ...fallback, body: typeof title === 'string' ? title.slice(0, 250) : fallback.body };
    } catch (__) {
      return fallback;
    }
  }
}

self.addEventListener('push', event => {
  const payload = asPayload(event.data);
  const options = {
    body: payload.body,
    tag: payload.tag,
    // If a later same-day scrape changes the aggregate, this tag replaces the
    // existing notification without deliberately requesting another sound.
    renotify: false,
    // A later workflow run has already made an audible alert for this browser
    // today. Keep its replacement visible but make it explicitly silent even
    // if the user dismissed the earlier OS notification.
    silent: payload.silent,
    data: { url: payload.url, count: payload.count, batchDate: payload.batchDate },
    // PNG, not SVG: Android/Chrome only reliably raster PNG notification art.
    // `badge` is the monochrome fleur-de-lis shown in the Android status bar
    // (alpha only), `icon` is the full-colour app icon beside the message.
    badge: NOTIFICATION_BADGE,
    icon: NOTIFICATION_ICON,
    ...(payload.silent ? {} : { vibrate: [100, 40, 100] }),
  };
  event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil((async () => {
    const absoluteTarget = new URL(target, self.location.origin).href;
    const openClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of openClients) {
      // A matching page should be focused rather than opened repeatedly.
      if (client.url === absoluteTarget || client.url.startsWith(self.location.origin + '/')) {
        await client.focus();
        if (client.url !== absoluteTarget && 'navigate' in client) await client.navigate(absoluteTarget);
        return;
      }
    }
    return self.clients.openWindow(absoluteTarget);
  })());
});

self.addEventListener('pushsubscriptionchange', event => {
  // A service worker cannot safely recreate a VAPID-bound subscription without
  // the user's locally stored preference/config. Tell any open page to sync;
  // when no page is open, a rejected old endpoint is removed by notify.py.
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
    clients.forEach(client => client.postMessage({ type: 'scout-push-subscription-change' }));
  }));
});
