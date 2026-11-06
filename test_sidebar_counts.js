// 側欄件數對數測試（2026-11-06）
//   用法： npm i jsdom && node test_sidebar_counts.js
//
// 用戶喺真機見到嘅問題（兩張截圖）：
//   ・側欄「全港（所有層級）36」，撳落去只見到 21 件；
//   ・一撳入 Scout System 揀「今天更新/發布」，同一個側欄由 36 變 21、Scout System 由 17 變 2。
//   根因：通告跟通告視窗、小工具跟「今天／之前發布」視窗，兩套時間定義加埋一齊。
//
// 而家嘅規則（呢個測試釘住）：
//   1. 側欄數字 = 「撳落去會見到幾多件」，同該視圖嘅列表完全對數。
//   2. 側欄數字唔會因為你喺另一個分頁撳過乜而變（Scout System 個視窗唔會漏入全港）。
//   3. 小工具一欄寫「今日新上架／已發布總數」（例 2/3），唔會再只寫一個「17」。
const { JSDOM } = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const now = Date.now();
const daysAgo = (n) => isoHKT(now - n * 86400000);

const mk = (title, url, src, date, region) => ({
  title, url, pdf_url: url, date, captured_date: date, source_site: src, region,
});

// 通告：今日 2 件、3 日前 1 件、40 日前 1 件
const notices = [
  mk('今日通告甲', 'https://example.test/a.pdf', '總會', isoHKT(now), '總會'),
  mk('今日通告乙', 'https://example.test/b.pdf', '總會', isoHKT(now), '總會'),
  mk('三日內通告', 'https://example.test/c.pdf', '總會', daysAgo(3), '總會'),
  mk('好舊嘅通告', 'https://example.test/d.pdf', '總會', daysAgo(40), '總會'),
];

// 小工具：今日新上架 2 件、40 日前 1 件（長期資產）
const tools = [
  Object.assign(mk('【助手】今日新集會流程', 'https://example.test/h1', 'Scout System', isoHKT(now), 'Scout System'), { tags: ['助手'] }),
  Object.assign(mk('【遊戲】今日新計時器', 'https://example.test/g1', 'Scout System', isoHKT(now), 'Scout System'), { tags: ['遊戲'] }),
  Object.assign(mk('【助手】舊集會流程', 'https://example.test/h2', 'Scout System', daysAgo(40), 'Scout System'), { tags: ['助手'] }),
];

const cache = {
  last_updated: isoHKT(now),
  data: { 總會: notices, 'Scout System': tools },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'https://example.org/',
  pretendToBeVisual: true,
  beforeParse(win) {
    win.fetch = (u) => {
      const s = String(u);
      if (s.includes('enrich')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      if (s.includes('/stories/stories/index.json')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ version: 1, items: [] }) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cache) });
    };
    win.alert = () => {}; win.confirm = () => true;
    win.HTMLCanvasElement.prototype.getContext = () => ({
      measureText: (t) => ({ width: String(t).length * 18 }),
      fillRect() {}, strokeRect() {}, fillText() {}, beginPath() {}, closePath() {},
      moveTo() {}, lineTo() {}, arc() {}, arcTo() {}, save() {}, restore() {},
      translate() {}, rotate() {}, scale() {}, stroke() {}, fill() {}, rect() {}, clip() {},
      createLinearGradient: () => ({ addColorStop() {} }),
      createRadialGradient: () => ({ addColorStop() {} }),
    });
  },
});

const d = dom.window.document;
const $$ = (s) => [...d.querySelectorAll(s)];
const regionSection = (name) => $$('#accordion .region').find(sec => {
  const btn = sec.querySelector(':scope > button');
  return !!btn && btn.querySelector('span').textContent.includes(name);
});
const badgeText = (name) => {
  const sec = regionSection(name);
  const b = sec && sec.querySelector(':scope > button .count-badge');
  return b ? b.textContent.trim() : '(冇 badge)';
};
const badgeNumber = (name) => Number(badgeText(name).split('/')[0]);
const sourceBtn = (label) => $$('#accordion .source-btn').find(b => b.querySelector('span')?.textContent.trim() === label);
const smallOf = (label) => sourceBtn(label)?.querySelector('small')?.textContent.trim();
const cardCount = () => $$('#cards .card').length;
const paneTitle = () => d.querySelector('#page-title')?.textContent.trim();
const chip = (label) => $$('#window-chips button').find(b => b.textContent.trim() === label);

(async () => {
  await wait(1200);

  // ── 1. 全港「今天」：側欄數字 = 列表件數 ─────────────────────────
  ok(cardCount() === 4, '全港「今天」列表 4 件（2 通告＋2 今日新上架工具）：' + cardCount());
  ok(badgeNumber('全港 (所有層級)') === cardCount(),
     '側欄全港 = 列表件數（今日窗）：' + badgeText('全港 (所有層級)') + ' vs ' + cardCount());
  ok(badgeNumber('總會') === 2, '總會跟通告視窗 = 2 件：' + badgeText('總會'));
  ok(badgeText('Scout System') === '2/3', '小工具寫「今日新上架／總數」= 2/3：' + badgeText('Scout System'));

  // ── 2. 換 7 天窗：側欄即刻對數 ─────────────────────────────────
  chip('7天')?.click();
  await wait(500);
  ok(cardCount() === 5, '全港「7天」列表 5 件（3 通告＋2 工具）：' + cardCount());
  ok(badgeNumber('全港 (所有層級)') === cardCount(),
     '換窗後側欄仍然等於列表件數：' + badgeText('全港 (所有層級)') + ' vs ' + cardCount());
  chip('今天')?.click();
  await wait(400);

  const allBadgeBefore = badgeText('全港 (所有層級)');

  // ── 3. 入 Scout System：全港個數唔准跳 ─────────────────────────
  const ssHeader = regionSection('Scout System')?.querySelector(':scope > button');
  if (ssHeader && !regionSection('Scout System').classList.contains('open')) ssHeader.click();
  await wait(200);
  sourceBtn('全部 (Scout System)')?.click();
  await wait(600);
  ok(badgeText('全港 (所有層級)') === allBadgeBefore,
     '入 Scout System 之後全港件數唔變（唔會 36↔21）：' + badgeText('全港 (所有層級)') + ' / 之前 ' + allBadgeBefore);
  ok(cardCount() === 3, '「之前發布」見到全部 3 件工具：' + cardCount());
  ok(paneTitle() === 'Scout System（之前發布）', '標題跟視窗寫「之前發布」：' + paneTitle());
  ok(smallOf('全部 (Scout System)') === '3 / 3 則', '「全部」= 目前 3 / 共 3：' + smallOf('全部 (Scout System)'));

  // ── 4. 切「今天更新/發布」：側欄件數唔跳，列表收窄 ─────────────
  chip('今天更新/發布')?.click();
  await wait(600);
  ok(cardCount() === 2, '「今天更新/發布」只見到 2 件今日新上架：' + cardCount());
  ok(badgeText('Scout System') === '2/3', '側欄仍然寫 2/3（唔會變咗做 2）：' + badgeText('Scout System'));
  ok(badgeText('全港 (所有層級)') === allBadgeBefore, '小工具視窗唔會滲入全港個數：' + badgeText('全港 (所有層級)'));
  ok(paneTitle() === 'Scout System（今天新上架）', '標題跟住變「今天新上架」：' + paneTitle());
  ok(smallOf('全部 (Scout System)') === '2 / 3 則', '「全部」= 目前 2 / 共 3：' + smallOf('全部 (Scout System)'));
  ok(smallOf('助手') === '1 / 2 則', '「助手」目前 1 / 共 2：' + smallOf('助手'));
  ok(smallOf('遊戲') === '1 / 1 則', '「遊戲」目前 1 / 共 1：' + smallOf('遊戲'));

  // ── 5. 返全港：數字前後一致 ────────────────────────────────────
  regionSection('全港 (所有層級)')?.querySelector(':scope > button')?.click();
  await wait(600);
  ok(badgeNumber('全港 (所有層級)') === cardCount(),
     '返全港後側欄仍然等於列表件數：' + badgeText('全港 (所有層級)') + ' vs ' + cardCount());
  ok(badgeNumber('全港 (所有層級)') === 4, '返全港後回到「今天」4 件（工具跟通告視窗）：' + badgeText('全港 (所有層級)'));

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 側欄件數同列表完全對數');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.stack || e.message); process.exit(1); });
