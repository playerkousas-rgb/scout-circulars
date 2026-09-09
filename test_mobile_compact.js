// index.html 手機版壓縮佈局測試（支部 2 行／分類 1 行／天數 1 行／頂欄置頂／兩欄卡片）
//   用法： npm i jsdom && node test_mobile_compact.js
//
// 重點驗證：
//   1. 頂欄有 ☰／★／🔔，★ 撳得入收藏夾、有數字、同桌面收藏掣同步
//   2. 頂欄 position: sticky（碌到底都撳到）
//   3. ScoutSystem 接入＋卡片「加入 ScoutSystem」手機唔顯示（CSS 隱藏，DOM 保留）
//   4. 天數旁邊嘅收藏／通知掣手機唔顯示（已搬去頂欄，DOM 保留俾桌面用）
//   5. 卡片：來源 badge＋分類標籤＋通告名排埋一齊（h3 仍然只係純標題），標題行全闊
//   6. 分享掣得返 icon，同 ★ 一齊放卡片底行（同「開啟附件」一排，唔再擠壓標題）；
//      地區搬上日期行；卡片底部只留 ScoutSystem（手機 CSS 隱藏）
//   7. 手機卡片兩欄（grid-template-columns: repeat(2, 1fr)）
const {JSDOM} = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const css = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));

const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const today = isoHKT(Date.now());

const cache = {
  last_updated: today,
  meta: { total_notices: 2 },
  data: {
    '總會': [
      { title: '童軍繩結訓練班', pdf_url: 'https://example.test/a.pdf',
        url: 'https://example.test/a.pdf', date: today,
        captured_date: today, source_site: '總會', region: '全港' },
      { title: '幼童軍日營', pdf_url: 'https://example.test/b.pdf',
        url: 'https://example.test/b.pdf', date: today,
        captured_date: today, source_site: '總會', region: '全港' },
    ],
  },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));

(async () => {
  // ── CSS 靜態檢查（手機 media query 內） ──
  const mobileCss = css.slice(css.indexOf('@media (max-width: 980px)'));
  ok(mobileCss.includes('.mobile-library-bar') && mobileCss.includes('position: sticky'),
     '頂欄 sticky 長期置頂');
  ok(mobileCss.includes('.scoutsystem-section { display: none !important; }'),
     'ScoutSystem 接入手機唔顯示');
  ok(mobileCss.includes('#window-chips .chip-bm, #window-chips #open-push-settings { display: none; }'),
     '天數旁邊嘅收藏／通知手機唔再重複佔位');
  ok(mobileCss.includes('#branch-chips { display: grid; grid-template-columns: repeat(5, 1fr);'),
     '支部 9 粒掣固定兩行（5+4）');
  ok(mobileCss.includes('#category-chips, #window-chips { display: grid; grid-template-columns: repeat(6, 1fr);'),
     '分類／天數各一行（6 欄）');
  ok(mobileCss.includes('.cards { margin-top: 12px; grid-template-columns: repeat(2, 1fr);'),
     '手機卡片兩欄（一版約 6–8 張）');
  ok(mobileCss.includes('.card-actions { display: none; }'),
     '手機卡片唔留「加入 ScoutSystem」嗰行');
  ok(!css.includes("${SHARE_SVG.share}<span>"),
     '分享掣冇咗「分享」文字（icon-only）');

  // ── DOM＋互動檢查 ──
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/',
    beforeParse(win) {
      win.fetch = (u) => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(String(u).includes('enrich') ? {} : cache),
      });
      win.alert = () => {}; win.confirm = () => true;
    },
  });
  const w = dom.window, d = w.document;
  await wait(700);

  const cards = [...d.querySelectorAll('#cards .card')];
  ok(cards.length === 2, `有 2 張卡片（${cards.length} 張）`);

  // 頂欄 ★
  const bmTop = d.querySelector('#open-bookmarks-mobile');
  ok(!!bmTop && bmTop.closest('.mobile-top-actions'), '頂欄有 ★ 收藏 icon');
  ok(!!d.querySelector('#open-library-menu') && !!d.querySelector('#open-push-mobile'),
     '頂欄齊 ☰／🔔');
  const bmCount = d.querySelector('#mobile-bm-count');
  ok(!!bmCount && bmCount.hidden, '未收藏時數字收起');

  // 卡片結構：badge＋分類＋標題排埋一齊，h3 仍然純標題
  const first = cards.find(c => c.querySelector('h3').textContent === '童軍繩結訓練班');
  ok(!!first, '搵到「童軍繩結訓練班」卡片');
  const wrap = first.querySelector('.card-title-wrap');
  ok(!!wrap && !!wrap.querySelector('.badge') && !!wrap.querySelector('.cat-tags') && !!wrap.querySelector('h3'),
     '卡片標題區有 badge＋分類＋h3');
  ok(first.querySelector('h3').textContent === '童軍繩結訓練班', 'h3 仍然只係純標題');
  const icons = first.querySelector('.card-icons');
  ok(!!icons && !!icons.querySelector('.star-btn') && !!icons.querySelector('.share-btn'),
     '收藏 ★＋分享 icon 齊喺卡片');
  ok(!first.querySelector('.card-head .card-icons'),
     '★／分享唔再喺標題隔籬（標題全闊，唔會被兩粒掣擠壓）');
  ok(!!icons.parentElement && icons.parentElement.classList.contains('meta-foot'),
     '★／分享搬咗去卡片底行，同「開啟附件」一排');
  ok(!!first.querySelector('.meta-date .host') && !!first.querySelector('.meta-date .meta-region'),
     '地區搬上日期行（騰空底行俾 ★／分享）');
  ok(mobileCss.includes('.card .meta-foot .link'),
     '手機「開啟附件」加大撳到手範圍');
  ok(css.includes('.meta-row { display: flex; align-items: center;'),
     'meta 行文字同掣置中對齊');
  ok(first.querySelector('.share-btn').textContent.trim() === '', '分享掣得返 icon，冇文字');
  const actions = first.querySelector('.card-actions');
  ok(actions.children.length === 1 && !!actions.querySelector('.ss-import'),
     '卡片底部只留「加入 ScoutSystem」（手機成行 CSS 隱藏）');

  // 收藏一張 → 頂欄數字變 1
  click(w, first.querySelector('.star-btn')); await wait(60);
  ok(d.querySelector('#mobile-bm-count').textContent === '1', '收藏後頂欄 ★ 顯示 1');

  // 頂欄 ★ 撳入收藏夾＋再撳返出嚟
  click(w, bmTop); await wait(80);
  ok(d.querySelector('#page-title').textContent.includes('收藏'), '頂欄 ★ 撳得入收藏夾');
  ok(bmTop.classList.contains('active'), '喺收藏夾時頂欄 ★ 高亮');
  ok(d.querySelectorAll('#cards .card').length === 1, '收藏夾得返 1 張');
  click(w, bmTop); await wait(80);
  ok(!d.querySelector('#page-title').textContent.includes('收藏'), '再撳頂欄 ★ 返返去一般通告');
  ok(!bmTop.classList.contains('active'), '離開收藏夾後高亮取消');

  // 桌面收藏掣 ↔ 頂欄 ★ 同步
  const bmChip = [...d.querySelectorAll('#window-chips .chip')].find(c => c.textContent.includes('收藏'));
  click(w, bmChip); await wait(80);
  ok(bmTop.classList.contains('active'), '撳桌面收藏掣，頂欄 ★ 跟住高亮');

  // 桌面結構保留：通知掣仍然喺收藏掣隔籬（俾桌面用，手機先 CSS 隱藏）
  const opener = d.querySelector('#window-chips #open-push-settings');
  ok(!!opener && opener.previousElementSibling.classList.contains('chip-bm'),
     '通知掣仍然喺收藏掣隔籬（DOM 保留）');
  ok(!!d.querySelector('#scoutsystem-url'), 'ScoutSystem 設定輸入框 DOM 保留（桌面用）');

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.message); process.exit(1); });
