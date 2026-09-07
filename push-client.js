/*
 * Browser-side anonymous Web Push lifecycle.
 *
 * Preferences stay in localStorage first.  The only network write is a
 * browser-created PushSubscription (endpoint + encryption keys) together with
 * controlled catalog IDs.  No account, name, email, phone, troop or district
 * data is collected.
 */
(function (global) {
  'use strict';

  const PREF_KEY = 'scl_push_preferences_v1';
  const TOKEN_KEY = 'scl_push_client_token_v1';
  const ENABLED_KEY = 'scl_push_enabled_v1';

  class PushClientError extends Error {
    constructor(message, code) {
      super(message);
      this.name = 'PushClientError';
      this.code = code || 'push_error';
    }
  }

  function safeStorageGet(key) {
    try { return global.localStorage.getItem(key); } catch (_) { return null; }
  }

  function safeStorageSet(key, value) {
    try { global.localStorage.setItem(key, value); return true; } catch (_) { return false; }
  }

  function safeStorageRemove(key) {
    try { global.localStorage.removeItem(key); } catch (_) {}
  }

  function uniqueStrings(values) {
    if (!Array.isArray(values)) return [];
    return [...new Set(values.filter(value => typeof value === 'string' && value.length > 0))];
  }

  function loadPreferences() {
    try {
      const raw = safeStorageGet(PREF_KEY);
      const value = raw ? JSON.parse(raw) : null;
      if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
      return {
        branches: uniqueStrings(value.branches),
        topics: uniqueStrings(value.topics),
        catalogVersion: typeof value.catalogVersion === 'string' ? value.catalogVersion : '',
        savedAt: typeof value.savedAt === 'string' ? value.savedAt : '',
      };
    } catch (_) {
      return null;
    }
  }

  function savePreferences(preferences) {
    const value = {
      branches: uniqueStrings(preferences && preferences.branches),
      topics: uniqueStrings(preferences && preferences.topics),
      catalogVersion: String((preferences && preferences.catalogVersion) || ''),
      savedAt: new Date().toISOString(),
    };
    if (!safeStorageSet(PREF_KEY, JSON.stringify(value))) {
      throw new PushClientError('瀏覽器無法儲存本機設定；請關閉無痕模式或容許網站儲存資料。', 'storage_unavailable');
    }
    return value;
  }

  function isSupported() {
    return Boolean(
      global.isSecureContext
      && global.navigator
      && global.navigator.serviceWorker
      && global.PushManager
      && global.Notification
      && global.crypto
      && global.crypto.getRandomValues
    );
  }

  function base64UrlToUint8Array(value) {
    const normalised = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalised + '='.repeat((4 - normalised.length % 4) % 4);
    let raw;
    try { raw = global.atob(padded); } catch (_) { throw new PushClientError('通知公開金鑰格式無效。', 'invalid_vapid_key'); }
    return Uint8Array.from(raw, char => char.charCodeAt(0));
  }

  function randomToken() {
    const bytes = new Uint8Array(32);
    global.crypto.getRandomValues(bytes);
    let binary = '';
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return global.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function clientToken() {
    let token = safeStorageGet(TOKEN_KEY);
    if (!/^[A-Za-z0-9_-]{32,128}$/.test(token || '')) {
      token = randomToken();
      if (!safeStorageSet(TOKEN_KEY, token)) {
        throw new PushClientError('瀏覽器無法建立本機通知識別碼。', 'storage_unavailable');
      }
    }
    return token;
  }

  async function responseJson(response) {
    try { return await response.json(); } catch (_) { return {}; }
  }

  async function fetchConfig() {
    let response;
    try {
      response = await global.fetch('/api/push-config', {
        method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' },
      });
    } catch (_) {
      throw new PushClientError('無法連接通知服務，請稍後再試。', 'network_error');
    }
    const body = await responseJson(response);
    if (!response.ok || !body || !body.enabled || typeof body.vapidPublicKey !== 'string') {
      throw new PushClientError((body && body.message) || '通知服務尚未完成設定。', (body && body.error) || 'push_unavailable');
    }
    return body;
  }

  async function postSubscription(payload) {
    let response;
    try {
      response = await global.fetch('/api/push-subscriptions', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw new PushClientError('無法儲存通知設定，請稍後再試。', 'network_error');
    }
    const body = await responseJson(response);
    if (!response.ok || !body || !body.ok) {
      throw new PushClientError((body && body.message) || '無法儲存通知設定。', (body && body.error) || 'storage_error');
    }
    return body;
  }

  async function registration() {
    if (!isSupported()) {
      throw new PushClientError('這個瀏覽器或目前的非 HTTPS 連線不支援網頁通知。', 'unsupported');
    }
    try {
      return await global.navigator.serviceWorker.register('/sw.js', { scope: '/' });
    } catch (_) {
      throw new PushClientError('無法啟動通知服務程式。', 'service_worker_error');
    }
  }

  function serialiseSubscription(subscription) {
    const json = subscription && typeof subscription.toJSON === 'function' ? subscription.toJSON() : null;
    if (!json || !json.endpoint || !json.keys || !json.keys.p256dh || !json.keys.auth) {
      throw new PushClientError('瀏覽器未能提供有效的通知訂閱資料。', 'invalid_subscription');
    }
    return { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } };
  }

  async function ensureSubscription(reg, publicKey, mayCreate) {
    let subscription = await reg.pushManager.getSubscription();
    if (!subscription && mayCreate) {
      try {
        subscription = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64UrlToUint8Array(publicKey),
        });
      } catch (error) {
        if (error && error.name === 'NotAllowedError') {
          throw new PushClientError('瀏覽器拒絕了通知權限。請在網址列的網站設定中重新允許。', 'permission_denied');
        }
        throw new PushClientError('未能建立瀏覽器通知訂閱。', 'subscribe_failed');
      }
    }
    return subscription;
  }

  async function persistSubscription(subscription, preferences) {
    return postSubscription({
      action: 'upsert',
      clientToken: clientToken(),
      subscription: serialiseSubscription(subscription),
      branches: preferences.branches,
      topics: preferences.topics,
    });
  }

  function validatePreferences(preferences) {
    const branches = uniqueStrings(preferences && preferences.branches);
    const topics = uniqueStrings(preferences && preferences.topics);
    if (!branches.length) throw new PushClientError('請至少選擇一個支部。', 'missing_branch');
    if (!topics.length) throw new PushClientError('請至少選擇一個關注項目。', 'missing_topic');
    return { ...preferences, branches, topics };
  }

  async function enable(preferences) {
    const saved = savePreferences(validatePreferences(preferences));
    const config = await fetchConfig();
    const reg = await registration();
    let permission = global.Notification.permission;
    if (permission === 'default') {
      permission = await global.Notification.requestPermission();
    }
    if (permission !== 'granted') {
      throw new PushClientError('尚未獲得通知權限；設定已只保存在這個瀏覽器。', 'permission_denied');
    }
    const subscription = await ensureSubscription(reg, config.vapidPublicKey, true);
    await persistSubscription(subscription, saved);
    safeStorageSet(ENABLED_KEY, '1');
    return { status: 'enabled', preferences: saved };
  }

  async function sync(preferences, options) {
    const saved = savePreferences(validatePreferences(preferences));
    const allowResubscribe = Boolean(options && options.resubscribe);
    if (!isSupported() || global.Notification.permission !== 'granted') {
      return { status: 'saved_local_only', preferences: saved };
    }
    const config = await fetchConfig();
    const reg = await registration();
    const subscription = await ensureSubscription(reg, config.vapidPublicKey, allowResubscribe);
    if (!subscription) return { status: 'saved_local_only', preferences: saved };
    await persistSubscription(subscription, saved);
    safeStorageSet(ENABLED_KEY, '1');
    return { status: 'synced', preferences: saved };
  }

  async function disable() {
    let subscription = null;
    try {
      if (isSupported()) {
        const reg = await registration();
        subscription = await reg.pushManager.getSubscription();
      }
    } catch (_) {
      // Still remove local state. A remote endpoint that cannot be reached is
      // safely cleaned by the dispatcher if the browser later rejects it.
    }

    let serverError = null;
    if (subscription) {
      try {
        await postSubscription({ action: 'delete', clientToken: clientToken(), subscription: serialiseSubscription(subscription) });
      } catch (error) {
        serverError = error;
      }
      try { await subscription.unsubscribe(); } catch (_) {}
    }
    safeStorageRemove(ENABLED_KEY);
    safeStorageRemove(TOKEN_KEY);
    if (serverError) {
      throw new PushClientError('此裝置已停止接收通知；伺服器清理會在失效時自動完成。', 'remote_delete_pending');
    }
    return { status: 'disabled' };
  }

  async function status() {
    const preferences = loadPreferences();
    const result = {
      supported: isSupported(),
      permission: global.Notification ? global.Notification.permission : 'unsupported',
      subscribed: false,
      enabledLocally: safeStorageGet(ENABLED_KEY) === '1',
      preferences,
    };
    if (result.supported) {
      try {
        const reg = await registration();
        result.subscribed = Boolean(await reg.pushManager.getSubscription());
      } catch (_) {}
    }
    return result;
  }

  global.ScoutPushClient = Object.freeze({
    PREF_KEY,
    loadPreferences,
    savePreferences,
    isSupported,
    enable,
    sync,
    disable,
    status,
    PushClientError,
  });
}(window));
