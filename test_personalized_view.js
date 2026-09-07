// Browser integration check for controlled push settings and exact `?n=` notification results.
// Requires jsdom: npm i jsdom && node test_personalized_view.js
const assert = require('assert');
const { JSDOM } = require('jsdom');
const fs = require('fs');

const pushClient = fs.readFileSync('push-client.js', 'utf8');
let html = fs.readFileSync('index.html', 'utf8');
html = html.replace('<script src="push-client.js"></script>', `<script>${pushClient}</script>`);

const date = '2026-09-07';
const good = { title: '童軍繩結訓練班', pdf_url: 'https://example.test/good.pdf', url: 'https://example.test/good.pdf', captured_date: date, date, source_site: '總會', region: '全港' };
const wrongBranch = { title: '幼童軍繩結訓練班', pdf_url: 'https://example.test/cub.pdf', url: 'https://example.test/cub.pdf', captured_date: date, date, source_site: '總會', region: '全港' };
const wrongTopic = { title: '童軍社區服務日', pdf_url: 'https://example.test/service.pdf', url: 'https://example.test/service.pdf', captured_date: date, date, source_site: '總會', region: '全港' };
const cache = { data: { '總會': [good, wrongBranch, wrongTopic] }, _meta: { regions: { '全港': ['總會'] }, source_order: ['總會'] } };
const enrich = {
  [good.pdf_url]: { branch_tags: ['童軍'], subscription_tags: ['category:training'], categories: [{ id: 'training' }] },
  [wrongBranch.pdf_url]: { branch_tags: ['幼童軍'], subscription_tags: ['category:training'], categories: [{ id: 'training' }] },
  [wrongTopic.pdf_url]: { branch_tags: ['童軍'], subscription_tags: ['category:service'], categories: [{ id: 'service' }] },
};
const catalog = JSON.parse(fs.readFileSync('subscription_catalog.json', 'utf8'));

// Mirrors the compact, non-personal FNV-1a ID in notify.py/index.html.
function noticeId(item) {
  const input = Buffer.from(`${item.source_site || ''}\x1f${item.pdf_url || item.url || ''}`, 'utf8');
  let hash = 0xcbf29ce484222325n;
  const prime = 0x100000001b3n;
  for (const byte of input) hash = BigInt.asUintN(64, (hash ^ BigInt(byte)) * prime);
  return hash.toString(16).padStart(16, '0');
}

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: `https://example.org/?n=${noticeId(good)}`,
  pretendToBeVisual: true,
  beforeParse(win) {
    win.TextEncoder = TextEncoder;
    win.fetch = async url => {
      const text = String(url);
      if (text.includes('subscription_catalog.json')) return { ok: true, json: async () => catalog };
      if (text.includes('enrich')) return { ok: true, json: async () => enrich };
      return { ok: true, json: async () => cache };
    };
    // Deliberately conflicting settings prove that `n` selects this push batch
    // without exposing or depending on a user's local preference in the URL.
    win.localStorage.setItem('scl_push_preferences_v1', JSON.stringify({ branches: ['領袖'], topics: ['category:service'], catalogVersion: '1.1.0' }));
    win.alert = () => {}; win.confirm = () => true;
  },
});

setTimeout(() => {
  try {
    const d = dom.window.document;
    assert.strictEqual(d.querySelector('#page-title').textContent, '通知中的通告');
    const titles = [...d.querySelectorAll('#cards h3')].map(el => el.textContent);
    assert.deepStrictEqual(titles, ['童軍繩結訓練班']);
    assert(d.querySelector('#messages').textContent.includes('這次通知只顯示'), 'exact notification result banner is shown');
    assert.strictEqual(d.querySelectorAll('#push-settings input').length, 0, 'notification settings must have no free-text input');
    assert.strictEqual(d.querySelectorAll('#push-branches option').length, 8);
    assert(d.querySelectorAll('#push-topics optgroup').length >= 4, 'topics should be grouped into four controlled interests');
    assert(d.querySelector('#push-branches').multiple && d.querySelector('#push-topics').multiple);
    assert(d.querySelector('#push-settings').textContent.includes('不收集姓名'));
    assert([...d.querySelectorAll('#push-topics option')].some(option => option.textContent === '地圖閱讀'), 'base item label is visible');
    assert(![...d.querySelectorAll('#push-topics option')].some(option => option.textContent === '地圖閱讀訓練'), 'formal suffix is not a separate visible option');
    assert(d.querySelector('#open-library-menu'), 'mobile region drawer opener exists');
    const maintenance = d.querySelector('#site-maintenance');
    assert(maintenance && !maintenance.open, 'low-frequency site diagnostics start collapsed');
    assert(maintenance.textContent.includes('每天自動更新全港各區地域總會通告'), 'update disclaimer moved into maintenance details');
    assert(maintenance.querySelector('#sidebar-meta'), 'source/data/asset figures moved into maintenance details');
    assert(maintenance.querySelector('a[href="errors.html"]'), 'diagnostic link is kept in the unobtrusive maintenance section');
    assert.strictEqual(d.querySelectorAll('.brand p').length, 0, 'brand no longer pushes disclaimer/diagnostics above browsing');
    assert(!d.querySelector('#filters-section').classList.contains('is-open'), 'mobile filters start collapsed');
    d.querySelector('#open-library-menu').click();
    assert(d.body.classList.contains('library-drawer-open'), 'mobile drawer opens without moving cards above it');
    assert.strictEqual(d.querySelector('#mobile-drawer-backdrop').hidden, false, 'drawer backdrop becomes visible');
    d.querySelector('#close-library-menu').click();
    assert(!d.body.classList.contains('library-drawer-open'), 'mobile drawer closes');
    assert.strictEqual(d.querySelector('#mobile-drawer-backdrop').hidden, true, 'drawer backdrop is hidden again');
    console.log('🎉 controlled dropdowns, compact mobile controls, and exact notification result view passed');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    dom.window.close();
  }
}, 700);
