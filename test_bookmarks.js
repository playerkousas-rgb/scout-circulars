// index.html 收藏（★）功能測試
//   用法： npm i jsdom && node test_bookmarks.js
//
// 重點驗證「用戶揾唔返」呢個場景：
//   1. 收藏之後切換時間視窗（今天/7天…），收藏夾仍然睇得返 —— 呢個係功能存在嘅理由
//   2. 重新載入頁面（localStorage）收藏仲喺度
//   3. 區會清走通告之後，收藏唔會人間蒸發，而係標示「原站已移除」，
//      由用戶自己撳 ★ 取消 —— 系統唔會擅自幫佢刪嘢
//   4. ★ 收藏分頁掣（同「今天/7天」並排）撳得入、撳得返
const {JSDOM} = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');

const today = new Date();
const iso = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => iso(new Date(today.getTime() - n * 86400000));

// 一則今日、一則 60 日前 —— 用嚟測時間視窗
const cache = {
  last_updated: iso(today),
  meta: { total_notices: 2 },
  data: {
    港島南區: [
      { title: '小童軍聖誕老人村派對', pdf_url: 'https://drive.google.com/file/d/AAA/view',
        url: 'https://drive.google.com/file/d/AAA/view', date: iso(today),
        captured_date: iso(today), source_site: '港島南區', region: '港島地域' },
      { title: '幼童軍繩結章訓練班', pdf_url: 'https://drive.google.com/file/d/BBB/view',
        url: 'https://drive.google.com/file/d/BBB/view', date: daysAgo(60),
        captured_date: daysAgo(60), source_site: '港島南區', region: '港島地域' },
    ],
  },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };

function boot(storage) {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/',
    beforeParse(win) {
      win.fetch = (u) => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(String(u).includes('enrich') ? {} : cache),
      });
      win.alert = () => {}; win.confirm = () => true;
      if (storage) for (const [k, v] of Object.entries(storage)) win.localStorage.setItem(k, v);
    },
  });
  return dom;
}

const wait = (ms) => new Promise(r => setTimeout(r, ms));
const $$ = (d, s) => [...d.querySelectorAll(s)];
// 側欄「★ 我的收藏」入口
const bmNav = (d) => $$(d, '.region > button').find(b => b.textContent.includes('我的收藏'));
const cards = (d) => $$(d, '#cards .card');

(async () => {
  // ── 場景一：收藏 → 切時間視窗 → 收藏夾仲見到 ──
  let dom = boot(null);
  let w = dom.window, d = w.document;
  await wait(700);

  ok(!!bmNav(d), '側欄有「★ 我的收藏」入口');
  ok(cards(d).length > 0, `預設有卡片顯示（${cards(d).length} 張）`);
  ok($$(d, '.star-btn').length === cards(d).length, '每張卡片都有 ☆ 掣');

  // 預設視窗係「今天」，先切到「3個月」先見到 60 日前嗰則
  const chip90 = $$(d, '#window-chips .chip').find(b => b.textContent.trim() === '3個月');
  chip90.dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(60);

  // 收藏「60 日前」嗰則
  const oldCard = cards(d).find(c => c.querySelector('h3').textContent.includes('繩結章'));
  ok(!!oldCard, '切到「3個月」視窗後，見到 60 日前嗰則通告');
  oldCard.querySelector('.star-btn').dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(60);

  ok(oldCard.querySelector('.star-btn').textContent === '★', '撳完變實心 ★');
  ok(oldCard.querySelector('.star-btn').getAttribute('aria-pressed') === 'true', 'aria-pressed 已更新');
  ok(/1/.test(bmNav(d).textContent), '側欄收藏數變 1：' + bmNav(d).textContent.trim());

  // 切去「今天」視窗 —— 60 日前嗰則喺一般清單應該消失
  const todayChip = $$(d, '#window-chips .chip').find(b => b.textContent.trim() === '今天');
  todayChip.dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(60);
  const visible = cards(d).map(c => c.querySelector('h3').textContent);
  ok(!visible.some(t => t.includes('繩結章')), '「今天」視窗下，60 日前嗰則喺一般清單消失（預期行為）');

  // 但入收藏夾就要見返 —— 呢個係整個功能嘅重點
  bmNav(d).dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  const bmTitles = cards(d).map(c => c.querySelector('h3').textContent);
  ok(bmTitles.some(t => t.includes('繩結章')),
     '★ 收藏夾唔受時間視窗影響，60 日前嗰則照樣揾得返（功能核心）');
  ok(cards(d).length === 1, `收藏夾只有 1 張（實際 ${cards(d).length}）`);
  ok(!!d.querySelector('#bm-copy') && !!d.querySelector('#bm-clear'), '收藏夾有「複製清單」同「清空收藏」');

  const saved = w.localStorage.getItem('scl_bookmarks_v1');
  ok(!!saved && Object.keys(JSON.parse(saved)).length === 1, 'localStorage 已寫入 1 筆');

  // ── 場景二：重開頁面，收藏仲喺度 ──
  dom = boot({ scl_bookmarks_v1: saved });
  w = dom.window; d = w.document;
  await wait(700);
  ok(/1/.test(bmNav(d).textContent), '重開頁面後側欄仍然顯示 1 筆收藏');
  bmNav(d).dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 1 && cards(d)[0].querySelector('h3').textContent.includes('繩結章'),
     '重開後收藏內容正確');

  // 再撳一次 ★ = 取消收藏，即刻由收藏夾消失
  cards(d)[0].querySelector('.star-btn').dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 0, '喺收藏夾撳 ★ 即刻移除');
  ok(d.querySelector('#messages').textContent.includes('仲未收藏'), '空狀態有引導文字');

  // ── 場景三：區會清走通告 → 保留 + 標示，由用戶自己取消 ──
  // 一則仲喺 cache（AAA），一則已經落架（GONE）
  const mixed = JSON.stringify({
    'https://drive.google.com/file/d/AAA/view': {
      title: '小童軍聖誕老人村派對', pdf_url: 'https://drive.google.com/file/d/AAA/view',
      source_site: '港島南區', saved_at: new Date().toISOString(),
    },
    'https://drive.google.com/file/d/GONE/view': {
      title: '已被區會清走嘅舊通告', pdf_url: 'https://drive.google.com/file/d/GONE/view',
      date: daysAgo(200), source_site: '港島南區',
      saved_at: new Date(Date.now() - 1000).toISOString(),
    },
  });
  dom = boot({ scl_bookmarks_v1: mixed });
  w = dom.window; d = w.document;
  await wait(700);
  ok(/2/.test(bmNav(d).textContent),
     '已落架嗰則唔會被自動清走，側欄仍然 2：' + bmNav(d).textContent.trim());
  bmNav(d).dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 2, '收藏夾兩則都仲喺度');
  const goneCard = cards(d).find(c => c.classList.contains('bm-gone'));
  ok(!!goneCard, '已落架嗰張標示為 bm-gone');
  ok(!!goneCard && goneCard.textContent.includes('原站已移除'), '卡片上明示「原站已移除」');
  ok(d.querySelector('#messages').textContent.includes('報唔到'), '頂部提示講明報唔到');
  const stillThere = JSON.parse(w.localStorage.getItem('scl_bookmarks_v1'));
  ok(Object.keys(stillThere).length === 2, 'localStorage 冇被系統擅自刪嘢');

  // 用戶自己撳 ★ 取消已落架嗰則
  goneCard.querySelector('.star-btn').dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 1, '用戶撳 ★ 之後，已落架嗰則先至消失');
  const afterUserRemove = JSON.parse(w.localStorage.getItem('scl_bookmarks_v1'));
  ok(!('https://drive.google.com/file/d/GONE/view' in afterUserRemove),
     '用戶取消之後 localStorage 先至寫返乾淨');

  // ── 場景三之二：「清走已移除」一鍵批次清 ──
  dom = boot({ scl_bookmarks_v1: mixed });
  w = dom.window; d = w.document;
  await wait(700);
  bmNav(d).dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  const clearGone = d.querySelector('#bm-clear-gone');
  ok(!!clearGone, '有「清走已移除」掣：' + (clearGone ? clearGone.textContent.trim() : '冇'));
  clearGone.dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 1, '一鍵清走之後只剩仲報得到嗰則');
  ok(!d.querySelector('#bm-clear-gone'), '冇嘢好清時個掣會消失');

  // ── 場景三之三：只存過時間戳嗰版要讀得返（向後兼容）──
  dom = boot({ scl_bookmarks_v1: JSON.stringify({
    'https://drive.google.com/file/d/AAA/view': Date.now(),
  }) });
  w = dom.window; d = w.document;
  await wait(700);
  bmNav(d).dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(cards(d).length === 1, '舊版「只存時間戳」格式仍然讀得返，收藏唔會走失');
  ok(cards(d)[0].querySelector('h3').textContent.includes('小童軍聖誕老人村'),
     '標題以 cache 最新資料為準');

  // ── 場景四：★ 收藏分頁掣（同「今天/7天」並排）──
  dom = boot(null);
  w = dom.window; d = w.document;
  await wait(700);
  const bmChip = () => [...d.querySelectorAll('#window-chips .chip')]
    .find(c => c.textContent.includes('收藏'));
  ok(!!bmChip(), '時間視窗旁邊有「★ 收藏」分頁掣');
  ok(bmChip().classList.contains('chip-bm'), '★ 收藏掣有獨立樣式（唔會當成時間範圍）');

  // 收藏一則再撳個 chip
  cards(d)[0].querySelector('.star-btn').dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(60);
  ok(/1/.test(bmChip().textContent), '★ 收藏掣顯示數目：' + bmChip().textContent.trim());
  bmChip().dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(bmChip().classList.contains('active'), '撳完 ★ 收藏掣會 active');
  ok(d.querySelector('#page-title').textContent.includes('收藏'), '標題切到收藏夾');
  ok([...d.querySelectorAll('#window-chips .chip')].filter(c => c.classList.contains('active')).length === 1,
     '喺收藏夾時，時間視窗掣唔會同時 active');
  bmChip().dispatchEvent(new w.MouseEvent('click', {bubbles:true}));
  await wait(80);
  ok(!bmChip().classList.contains('active'), '再撳一次返返去一般通告');
  ok(!d.querySelector('#page-title').textContent.includes('收藏'), '標題切返一般來源');

  // ── 場景五：cache 載入失敗唔可以搞爛收藏 ──
  const domFail = new JSDOM(html, {
    runScripts: 'dangerously', url: 'https://example.org/',
    beforeParse(win) {
      win.fetch = () => Promise.reject(new Error('network down'));
      win.alert = () => {}; win.confirm = () => true;
      win.localStorage.setItem('scl_bookmarks_v1', mixed);
    },
  });
  await wait(700);
  const kept = JSON.parse(domFail.window.localStorage.getItem('scl_bookmarks_v1'));
  ok(Object.keys(kept).length === 2,
     'cache 載入失敗時唔會清走任何收藏（網絡問題唔應該炒晒用戶收藏）');

  // ── 場景四：localStorage 壞資料唔應該搞爛個站 ──
  dom = boot({ scl_bookmarks_v1: '{{{壞掉嘅JSON' });
  w = dom.window; d = w.document;
  await wait(700);
  ok(cards(d).length > 0, 'localStorage 有壞資料時，頁面仍然正常載入');
  ok(!!bmNav(d) && /0/.test(bmNav(d).textContent), '壞資料當作 0 筆收藏處理');

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.message); process.exit(1); });
