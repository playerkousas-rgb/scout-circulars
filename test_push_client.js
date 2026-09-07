// push-client.js unit test — no browser or real network required.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { webcrypto } = require('crypto');

const values = new Map();
const localStorage = {
  getItem: key => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: key => values.delete(key),
};
let activeSubscription = null;
let unsubscribed = false;
const requestBodies = [];
const registration = {
  pushManager: {
    getSubscription: async () => activeSubscription,
    subscribe: async () => {
      activeSubscription = {
        toJSON: () => ({ endpoint: 'https://fcm.googleapis.com/fcm/send/test', keys: { p256dh: 'A'.repeat(87), auth: 'B'.repeat(22) } }),
        unsubscribe: async () => { unsubscribed = true; activeSubscription = null; return true; },
      };
      return activeSubscription;
    },
  },
};
const win = {
  localStorage,
  isSecureContext: true,
  crypto: webcrypto,
  atob: value => Buffer.from(value, 'base64').toString('binary'),
  btoa: value => Buffer.from(value, 'binary').toString('base64'),
  PushManager: function PushManager() {},
  Notification: { permission: 'granted', requestPermission: async () => 'granted' },
  navigator: { serviceWorker: { register: async () => registration } },
  fetch: async (url, options = {}) => {
    if (url === '/api/push-config') {
      return { ok: true, json: async () => ({ ok: true, enabled: true, vapidPublicKey: 'A'.repeat(87) }) };
    }
    if (url === '/api/push-subscriptions') {
      requestBodies.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ ok: true, status: 'saved' }) };
    }
    throw new Error('unexpected URL ' + url);
  },
};
const context = vm.createContext({ window: win, Uint8Array, Set, JSON, Date, String, Array, Boolean, Error, Object, Promise, RegExp });
vm.runInContext(fs.readFileSync('push-client.js', 'utf8'), context, { filename: 'push-client.js' });
const client = win.ScoutPushClient;

(async () => {
  assert(client && client.isSupported(), 'secure browser mock should be supported');
  const local = client.savePreferences({ branches: ['童軍', '童軍'], topics: ['category:training'], catalogVersion: '1.0.0' });
  assert.deepStrictEqual([...local.branches], ['童軍']);
  assert.deepStrictEqual([...client.loadPreferences().topics], ['category:training']);

  const result = await client.enable({ branches: ['童軍'], topics: ['category:training'] });
  assert.strictEqual(result.status, 'enabled');
  assert.strictEqual(requestBodies.length, 1);
  assert.strictEqual(requestBodies[0].action, 'upsert');
  assert.deepStrictEqual([...requestBodies[0].branches], ['童軍']);
  assert.deepStrictEqual([...requestBodies[0].topics], ['category:training']);
  assert.match(requestBodies[0].clientToken, /^[A-Za-z0-9_-]{43}$/);
  assert(!JSON.stringify(requestBodies[0]).includes('email'), 'payload must contain no personal profile field');

  await client.disable();
  assert(unsubscribed, 'browser subscription must be cancelled on disable');
  assert.strictEqual(requestBodies[1].action, 'delete');
  assert.strictEqual(localStorage.getItem('scl_push_enabled_v1'), null);
  assert.strictEqual(localStorage.getItem('scl_push_client_token_v1'), null);
  console.log('🎉 push-client LocalStorage, anonymous upsert, and delete lifecycle passed');
})().catch(error => { console.error(error); process.exit(1); });
