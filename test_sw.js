// Pure Service Worker payload guard checks. Run: node test_sw.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const handlers = {};
const context = {
  URL,
  self: {
    location: { origin: 'https://library.example' },
    addEventListener: (name, handler) => { handlers[name] = handler; },
    skipWaiting: () => {},
    clients: {},
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('sw.js', 'utf8'), context, { filename: 'sw.js' });

const asPayload = context.asPayload;
assert.strictEqual(typeof asPayload, 'function', 'service-worker payload parser should be available');

const exact = asPayload({ json: () => ({
  title: '🔔 童軍繩結訓練班',
  body: '點擊查看通告',
  url: 'https://library.example/?n=0123456789abcdef',
  tag: 'batch',
}) });
assert.strictEqual(exact.url, 'https://library.example/?n=0123456789abcdef');
assert.strictEqual(exact.body, '點擊查看通告');

for (const url of [
  'https://files.example/circular.pdf',
  'https://library.example/uploads/circular.pdf',
  '/uploads/circular.pdf',
  'javascript:alert(1)',
]) {
  const guarded = asPayload({ json: () => ({ url }) });
  assert.strictEqual(guarded.url, '/', `non-library result URL must fall back: ${url}`);
}

console.log('🎉 service worker only accepts same-origin exact library result URLs');
