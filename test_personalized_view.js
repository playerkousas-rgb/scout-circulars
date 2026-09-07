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
    win.localStorage.setItem('scl_push_preferences_v1', JSON.stringify({ branches: ['領袖'], topics: ['category:service'], catalogVersion: '2.0.0' }));
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
    // 🔔 通知設定：由搜尋列／收藏旁的掣開啟，唔再係獨立大區塊。
    assert(!d.querySelector('#push-section-wrap'), 'old standalone push block is gone');
    const opener = d.querySelector('#window-chips #open-push-settings');
    assert(opener && opener.previousElementSibling.classList.contains('chip-bm'), 'notification chip sits right after the 收藏 chip');
    assert.strictEqual(d.querySelector('#push-backdrop').hidden, true, 'settings sheet starts closed');
    opener.click();
    assert.strictEqual(d.querySelector('#push-backdrop').hidden, false, 'settings sheet opens from the chip');
    assert.strictEqual(d.querySelectorAll('#push-settings input:not([type="checkbox"])').length, 0, 'notification settings must have no free-text input');
    assert(!d.querySelector('#push-settings select'), 'no <select multiple>: every option is a click-to-tick checkbox');
    const branchInputs = d.querySelectorAll('#push-branches input[type="checkbox"]');
    assert.strictEqual(branchInputs.length, 8);
    assert.deepStrictEqual([...branchInputs].filter(i => i.checked).map(i => i.value), ['領袖'], 'saved branch is pre-ticked');
    const generalLabels = [...d.querySelectorAll('#push-general .pick-chip')].map(el => el.textContent.replace('✓', '').trim());
    assert.deepStrictEqual(generalLabels, ['服務', '活動：大露營', '活動：營火會', '活動：其他活動', '所有比賽'], '服務／活動／比賽 stay as they were');
    assert(d.querySelector('#push-general input[value="category:service"]').checked, 'saved topic is pre-ticked');
    // 訓練：先按支部；領袖分木章／非木章。
    const leaderBlock = d.querySelector('#push-topics .push-branch-block[data-branch="領袖"]');
    assert(leaderBlock, 'training list is grouped by the ticked branch');
    assert.deepStrictEqual([...leaderBlock.querySelectorAll('.push-section-title')].map(el => el.textContent), ['木章訓練班', '非木章訓練班'], '領袖 training is split into wood badge / non-wood badge');
    assert(leaderBlock.querySelector('input[value="training:領袖:木章"]') && leaderBlock.querySelector('input[value="training:領袖:非木章"]'), 'each 領袖 section has an "all" tick');
    const leaderOptions = [...leaderBlock.querySelectorAll('.pick-chip')].map(el => el.textContent.replace('✓', '').trim());
    assert(leaderOptions.includes('地圖閱讀'), 'base item label is visible');
    assert(!leaderOptions.includes('地圖閱讀訓練'), 'formal suffix is not a separate visible option');
    assert(leaderOptions.includes('童軍運動基本原則（單元1A／1B）'), 'wood badge module is listed');
    assert(!d.querySelector('#push-topics .push-branch-block[data-branch="童軍"]'), 'unticked branch has no training block yet');
    // 點一下即剔（唔使 Ctrl／Shift），而且揀多個支部時保留已剔項目。
    const scoutBranch = d.querySelector('#push-branches input[value="童軍"]');
    scoutBranch.click();
    assert(scoutBranch.checked && d.querySelector('#push-branches input[value="領袖"]').checked, 'plain click adds a second branch without deselecting the first');
    const scoutBlock = d.querySelector('#push-topics .push-branch-block[data-branch="童軍"]');
    assert(scoutBlock, 'ticking 童軍 adds its own training block');
    assert(scoutBlock.querySelector('input[value="training:童軍"]'), '童軍 has an "all 童軍 training" tick');
    const scoutLabels = [...scoutBlock.querySelectorAll('.pick-chip')].map(el => el.textContent.replace('✓', '').trim());
    for (const label of ['童軍領導才', '急救章', '初級航空活動章', '地圖閱讀章']) assert(scoutLabels.includes(label), `${label} is a 童軍 option`);
    for (const label of ['探索獎章', '標準獎章', '高級獎章', '總領袖獎章']) assert(!scoutLabels.includes(label), `${label} (進度性) must not be offered`);
    const subgroupNames = [...scoutBlock.querySelectorAll('.push-subgroup summary > span:first-child')].map(el => el.textContent.replace(/（\d+）$/, ''));
    for (const name of ['興趣組', '技能組', '服務組']) assert(subgroupNames.includes(name), `${name} subgroup exists for 童軍`);
    const firstAid = scoutBlock.querySelector('input[value="course:scout-first-aid-badge"]');
    firstAid.click();
    const leadership = scoutBlock.querySelector('input[value="course:scout-leadership"]');
    leadership.click();
    assert(firstAid.checked && leadership.checked, 'two plain clicks tick two items (no modifier key needed)');
    assert(firstAid.closest('.pick-chip').classList.contains('checked'), 'ticked chip is visibly highlighted');
    assert(d.querySelector('#push-count').textContent.includes('3 個項目'), 'live counter reflects 服務 + 2 ticked courses');
    d.querySelector('#push-branches input[value="領袖"]').click();
    assert(!d.querySelector('#push-topics .push-branch-block[data-branch="領袖"]'), 'unticking a branch removes its block');
    assert(d.querySelector('#push-topics input[value="course:scout-first-aid-badge"]').checked, 'ticks in remaining branches survive a branch change');
    d.querySelector('#push-close').click();
    assert.strictEqual(d.querySelector('#push-backdrop').hidden, true, 'settings sheet closes');
    assert(d.querySelector('#push-settings').textContent.includes('不收集姓名'));
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
    console.log('🎉 click-to-tick notification sheet, branch-first training list, compact mobile controls, and exact notification result view passed');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    // Opening the sheet kicks off an async status refresh; let it settle before tearing the window down.
    setTimeout(() => dom.window.close(), 100);
  }
}, 700);
