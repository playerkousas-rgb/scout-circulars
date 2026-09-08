// Icon / manifest consistency checks. Run: node test_icons.js
//
// 為何要有呢個測試：manifest、index.html 同 sw.js 各自用字串指向 icons/ 入面嘅
// 檔案；改名或漏 commit PNG 唔會令任何嘢報錯，只會令主畫面圖示變成空白、
// 推送通知冇圖。呢度離線檢查所有引用都指向真實存在、尺寸正確嘅檔案。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = __dirname;
const exists = (rel) => fs.existsSync(path.join(ROOT, rel.replace(/^\//, '')));

function pngSize(rel) {
  const buf = fs.readFileSync(path.join(ROOT, rel.replace(/^\//, '')));
  assert.strictEqual(buf.toString('ascii', 1, 4), 'PNG', `${rel} should be a PNG`);
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

// ── manifest.webmanifest ──
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'manifest.webmanifest'), 'utf8'));
assert.ok(Array.isArray(manifest.icons) && manifest.icons.length >= 4, 'manifest should list several icons');
const purposes = new Set();
for (const icon of manifest.icons) {
  assert.ok(exists(icon.src), `manifest icon missing on disk: ${icon.src}`);
  purposes.add(icon.purpose || 'any');
  if (icon.type === 'image/png') {
    const [w, h] = icon.sizes.split('x').map(Number);
    assert.deepStrictEqual(pngSize(icon.src), { width: w, height: h }, `${icon.src} should be ${icon.sizes}`);
  }
}
assert.ok(purposes.has('any'), 'manifest needs a purpose=any icon');
assert.ok(purposes.has('maskable'), 'manifest needs a purpose=maskable icon (Android adaptive icon)');
assert.ok(
  manifest.icons.some(i => i.purpose === 'maskable' && i.sizes === '512x512'),
  'maskable icon should include a 512x512 PNG for the install splash screen'
);
for (const icon of manifest.icons) {
  // 「any maskable」合併寫法會令 iOS/桌面顯示被裁邊嘅版本；要分開兩張。
  assert.ok(!/\s/.test(icon.purpose || ''), `keep purposes separate, got "${icon.purpose}" for ${icon.src}`);
}

// ── index.html <head> ──
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const head = html.slice(0, html.indexOf('</head>'));
const linkHrefs = [...head.matchAll(/<link[^>]+rel="(?:icon|apple-touch-icon|manifest)"[^>]*href="([^"]+)"/g)].map(m => m[1]);
assert.ok(linkHrefs.includes('/manifest.webmanifest'), 'index.html must link the manifest');
assert.ok(linkHrefs.includes('/icons/apple-touch-icon.png'), 'index.html must link apple-touch-icon');
// The artwork is a painted raster; icon.svg is only a base64 wrapper for the manifest,
// so the tab favicon should be the small PNGs (fast) rather than the 60 KB SVG.
assert.ok(linkHrefs.includes('/icons/favicon-32.png'), 'index.html should link the 32px PNG favicon');
assert.ok(linkHrefs.includes('/icons/favicon-16.png'), 'index.html should link the 16px PNG favicon');
assert.ok(!linkHrefs.includes('/icon.svg'), 'do not use the heavy SVG wrapper as the tab favicon');
for (const href of linkHrefs) assert.ok(exists(href), `index.html links a missing file: ${href}`);
const apple = pngSize('/icons/apple-touch-icon.png');
assert.strictEqual(apple.width, 180, 'apple-touch-icon should be 180x180');

// ── sw.js notification art ──
const handlers = {};
const context = {
  URL,
  self: {
    location: { origin: 'https://library.example' },
    addEventListener: (name, handler) => { handlers[name] = handler; },
    skipWaiting: () => {},
    clients: {},
    registration: { showNotification: (title, options) => { context.__shown = { title, options }; return Promise.resolve(); } },
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'sw.js'), 'utf8'), context, { filename: 'sw.js' });
assert.strictEqual(typeof handlers.push, 'function', 'sw.js should register a push handler');
handlers.push({ data: null, waitUntil: () => {} });
const { options } = context.__shown;
assert.ok(options.icon && options.badge, 'push notification should set icon and badge');
for (const key of ['icon', 'badge']) {
  assert.ok(/\.png$/.test(options[key]), `notification ${key} should be a PNG (Android does not raster SVG), got ${options[key]}`);
  assert.ok(exists(options[key]), `notification ${key} missing on disk: ${options[key]}`);
}
assert.notStrictEqual(options.icon, options.badge, 'badge must be the monochrome silhouette, not the colour icon');
const badge = pngSize(options.badge);
assert.ok(badge.width >= 72 && badge.width === badge.height, `badge should be square and >= 72px, got ${badge.width}x${badge.height}`);

console.log('🎉 manifest, <head> and service-worker icons all point at real PNG/SVG files with the right sizes');
