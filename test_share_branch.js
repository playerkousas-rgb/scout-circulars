// index.html 分享 + 支部標籤功能測試
//   用法： npm i jsdom && node test_share_branch.js
//
// 重點驗證：
//   1. 支部標籤：9 個（全部 + 8 支部），單選、再撳取消、唔顯示數字
//   2. 「童軍」唔會命中「幼童軍 / 深資童軍 / 樂行童軍」（audience 同標題都係）
//   3. 冇 audience 嘅通告退而求其次用標題（機構名唔特別處理，用戶可配合關鍵字）
//   4. 舊嘅「成員（精準）/ 支部」欄位同「只顯示明確日期」已移除
//   5. 分享面板：社交連結、複製網址（附件直連）、複製文字、圖片產生（mock /api/render）
//   6. 圖片產生失敗（not_pdf）有中文提示，唔會炸
const {JSDOM} = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
// 「今天」視窗以香港時間計，所以測試資料嘅日期都要用 HKT（唔係 UTC），
// 否則 UTC 16:00 之後跑測試，UTC 日期仲係「尋日」，資料會跌出「今天」視窗。
const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const now = Date.now();
const today = { iso: isoHKT(now) };
const iso = (d) => (d && d.iso) || isoHKT(d.getTime());
const daysAgo = (n) => isoHKT(now - n * 86400000);

const PDF_A = 'https://www.skwscout.org.hk/uploads/A 幼童軍.pdf';        // 有空格 + 中文
const PDF_B = 'https://scout.org.hk/uploads/B.pdf';
const PDF_C = 'https://scout.org.hk/uploads/C.pdf';
const PDF_D = 'https://scout.org.hk/uploads/D.pdf';
const PDF_E = 'https://drive.google.com/file/d/XYZ/view';
const HTML_F = 'https://www.wanchaiscout.org.hk/index.php?option=com_content&id=1';

const mk = (title, url, src, date, region) => ({ title, url, pdf_url: url, date, captured_date: date, source_site: src, region });
const cache = {
  last_updated: iso(today),
  data: {
    筲箕灣區: [
      mk('幼童軍繩結章訓練班', PDF_A, '筲箕灣區', iso(today), '港島地域'),           // audience: 幼童軍
      mk('童軍技能訓練班', PDF_B, '筲箕灣區', iso(today), '港島地域'),               // audience: 童軍、領袖
      mk('深資童軍海上旅程', PDF_C, '筲箕灣區', daysAgo(20), '港島地域'),           // 冇 enrich → 標題：深資童軍
      mk('旅團註冊須知', PDF_D, '筲箕灣區', iso(today), '港島地域'),                 // 冇 enrich → 標題冇任何支部詞
      mk('樂行童軍暨領袖交流日', PDF_E, '筲箕灣區', iso(today), '港島地域'),       // audience: 所有成員
      mk('灣仔區網頁通告', HTML_F, '筲箕灣區', iso(today), '港島地域'),            // 網頁，唔係 PDF
    ],
  },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};
const enrich = {
  [PDF_A]: { audience: '幼童軍', deadline: '2026-09-20', fee: 'HK$50' },
  [PDF_B]: { audience: '童軍、領袖', deadline: '', fee: '' },
  [PDF_E]: { audience: '所有成員', deadline: '', fee: '' },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));

// 模擬 /api/render：B.pdf 兩頁成功；網頁連結回 not_pdf；其他 fetch_failed
const renderCalls = [];
function fakeFetch(win) {
  return (u, opts) => {
    const s = String(u);
    if (s.includes('enrich')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(enrich) });
    if (s.includes('/api/render')) {
      renderCalls.push(s);
      const q = new win.URL(s, 'https://example.org').searchParams;
      const target = q.get('url');
      const page = Number(q.get('page') || 1);
      if (target === PDF_B) {
        if (page > 2) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ error: 'page_out_of_range', message: '只有 2 頁' }) });
        const blob = new win.Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: 'image/jpeg' });
        return Promise.resolve({ ok: true, status: 200, headers: new win.Headers({ 'X-Pdf-Pages': '2', 'X-Pdf-Page': String(page) }), blob: () => Promise.resolve(blob) });
      }
      if (target === HTML_F) return Promise.resolve({ ok: false, status: 415, json: () => Promise.resolve({ error: 'not_pdf', message: '呢個連結唔係 PDF 檔' }) });
      return Promise.resolve({ ok: false, status: 502, json: () => Promise.resolve({ error: 'fetch_failed', message: '連唔到原站' }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cache) });
  };
}

function boot() {
  const clip = { text: null, items: null };
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/',
    pretendToBeVisual: true,
    beforeParse(win) {
      win.fetch = fakeFetch(win);
      win.alert = () => {}; win.confirm = () => true;
      win.URL.createObjectURL = () => 'blob:fake'; win.URL.revokeObjectURL = () => {};
      Object.defineProperty(win.navigator, 'clipboard', { value: {
        writeText: (t) => { clip.text = t; return Promise.resolve(); },
        write: (items) => { clip.items = items; return Promise.resolve(); },
      }, configurable: true });
    },
  });
  dom.clip = clip;
  return dom;
}

const $$ = (d, s) => [...d.querySelectorAll(s)];
const cards = (d) => $$(d, '#cards .card');
const titles = (d) => cards(d).map(c => c.querySelector('h3').textContent);
const chip = (d, name) => $$(d, '#branch-chips .chip').find(c => c.textContent.trim().startsWith(name));
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));

(async () => {
  let dom = boot();
  let w = dom.window, d = w.document;
  await wait(700);

  // ── 1. 舊控制項已移除 ──
  ok(!d.querySelector('#explicit-date'), '「只顯示明確日期」已移除');
  ok(!d.querySelector('#field-chips'), '舊「名稱 / 成員（精準）/ 支部」欄位已移除');
  ok(d.querySelector('#keyword').placeholder.includes('名稱'), '關鍵字欄提示只搜名稱：' + d.querySelector('#keyword').placeholder);
  ok(d.querySelector('#scoutsystem-url').placeholder.includes('troop-portal.vercel.app'), 'ScoutSystem 例子網址改成 troop-portal.vercel.app');

  // ── 2. 支部標籤 ──
  const labels = $$(d, '#branch-chips .chip').map(c => c.textContent.trim());
  ok(JSON.stringify(labels) === JSON.stringify(['全部', '小童軍', '幼童軍', '童軍', '深資童軍', '樂行童軍', '領袖', '家長', '會務委員']),
     '9 個支部標籤次序正確、冇數字：' + labels.join(' '));
  ok(!d.querySelector('#branch-chips .chip-n'), '支部掣唔顯示數字');
  ok(chip(d, '全部').classList.contains('active'), '預設「全部」active');

  // 預設視窗「今天」：A B D E F 五張（C 係 20 日前）
  ok(cards(d).length === 5, `「今天」視窗 5 張（實際 ${cards(d).length}）`);

  click(w, chip(d, '童軍')); await wait(50);
  ok(chip(d, '童軍').classList.contains('active') && !chip(d, '全部').classList.contains('active'), '撳「童軍」→ 只有佢 active（單選）');
  let t = titles(d);
  ok(t.includes('童軍技能訓練班') && t.includes('樂行童軍暨領袖交流日'), '童軍：命中 audience 有「童軍」嘅 B 同「所有成員」嘅 E');
  ok(!t.includes('幼童軍繩結章訓練班'), '童軍：唔命中幼童軍（audience 精準）');
  ok(!t.includes('旅團註冊須知'), '童軍：標題冇支部詞嘅唔命中');
  ok(d.querySelector('#status-line').textContent.includes('支部：童軍'), '狀態列顯示目前支部');

  click(w, chip(d, '童軍')); await wait(50);
  ok(chip(d, '全部').classList.contains('active') && cards(d).length === 5, '再撳一次「童軍」= 取消，返回全部');

  // 冇 enrich 嘅通告：靠標題判斷（切到 30 天視窗先見到 C）
  click(w, $$(d, '#window-chips .chip').find(b => b.textContent.trim() === '30天')); await wait(50);
  ok(cards(d).length === 6, `切 30 天視窗後 6 張（實際 ${cards(d).length}）`);
  click(w, chip(d, '深資童軍')); await wait(50);
  ok(chip(d, '深資童軍').classList.contains('active'), '切視窗後支部掣狀態保留、可以繼續揀');
  t = titles(d);
  ok(t.includes('深資童軍海上旅程'), '冇 audience 嘅通告用標題判斷：深資童軍命中 C');
  click(w, chip(d, '童軍')); await wait(50);
  ok(!titles(d).includes('深資童軍海上旅程'), '標題「深資童軍」唔會被「童軍」命中（longest-match）');

  // 關鍵字 + 支部 組合
  click(w, chip(d, '全部')); await wait(30);
  const kw = d.querySelector('#keyword'); kw.value = '訓練班'; kw.dispatchEvent(new w.Event('input', { bubbles: true })); await wait(50);
  ok(cards(d).length === 2, `關鍵字「訓練班」→ 2 張（實際 ${cards(d).length}）`);
  click(w, chip(d, '幼童軍')); await wait(50);
  ok(cards(d).length === 1 && titles(d)[0] === '幼童軍繩結章訓練班', '關鍵字 + 支部 同時生效');
  kw.value = ''; kw.dispatchEvent(new w.Event('input', { bubbles: true }));
  click(w, chip(d, '全部')); await wait(50);

  // ── 3. 分享面板 ──
  ok(cards(d).every(c => c.querySelector('.share-btn')), '每張卡片都有「分享」掣');
  const cardB = cards(d).find(c => c.querySelector('h3').textContent === '童軍技能訓練班');
  click(w, cardB.querySelector('.share-btn')); await wait(50);
  let sheet = d.querySelector('.share-sheet');
  ok(!!sheet, '撳分享 → 彈出分享面板');
  ok(sheet.querySelector('#share-title').textContent === '童軍技能訓練班', '面板標題係該通告');
  const linkLabels = $$(d, '.share-sheet a[data-act="link"]').map(a => a.textContent.trim());
  ok(JSON.stringify(linkLabels) === JSON.stringify(['WhatsApp', 'Telegram', 'Facebook', 'X', 'LINE', '電郵']), '社交平台連結齊全：' + linkLabels.join(' '));
  const waHref = decodeURIComponent($$(d, '.share-sheet a.wa')[0].href);
  ok(waHref.includes(PDF_B) && waHref.includes('童軍技能訓練班') && waHref.includes('【筲箕灣區】'), 'WhatsApp 文字含區會、標題、附件直連');
  const fbHref = $$(d, '.share-sheet a.fb')[0].href;
  ok(fbHref.startsWith('https://www.facebook.com/sharer/sharer.php?u=') && decodeURIComponent(fbHref).includes(PDF_B), 'Facebook sharer 帶附件網址');
  ok($$(d, '.share-sheet a[data-act="link"]').every(a => a.target === '_blank' && a.rel.includes('noopener')), '社交連結新分頁 + noopener');

  click(w, sheet.querySelector('[data-act="copy-url"]')); await wait(30);
  ok(dom.clip.text === PDF_B, '「複製網址」複製附件直連：' + dom.clip.text);
  click(w, sheet.querySelector('[data-act="copy-text"]')); await wait(30);
  ok(dom.clip.text.includes('【筲箕灣區】童軍技能訓練班') && dom.clip.text.endsWith(PDF_B), '「複製文字」= 標題 + 摘要 + 網址');
  ok(d.querySelector('.share-toast') && d.querySelector('.share-toast').textContent.includes('已複製'), '複製後有 toast 提示');

  // 圖片產生
  click(w, sheet.querySelector('[data-act="img"]')); await wait(120);
  ok(renderCalls.length === 1 && renderCalls[0].startsWith('/api/render?') && new w.URL(renderCalls[0], 'https://example.org').searchParams.get('url') === PDF_B,
     '「產生圖片」打 /api/render?url=<附件>：' + renderCalls[0]);
  ok(!sheet.querySelector('[data-role="preview"]').hidden, '圖片預覽顯示');
  ok(sheet.querySelector('[data-role="imgstatus"]').textContent.includes('已準備好'), '狀態：已準備好');
  const pagesel = sheet.querySelector('[data-role="pagesel"]');
  ok(pagesel.options.length === 2, `兩頁 PDF → 頁數選單有 2 頁（實際 ${pagesel.options.length}）`);
  ok(!sheet.querySelector('[data-act="img-dl"]').disabled, '下載圖片掣可用');
  pagesel.value = '2'; pagesel.dispatchEvent(new w.Event('change', { bubbles: true })); await wait(120);
  ok(renderCalls.length === 2 && new w.URL(renderCalls[1], 'https://example.org').searchParams.get('page') === '2', '揀第 2 頁 → 再打 /api/render page=2');
  ok(sheet.querySelector('[data-role="pageinfo"]').textContent.includes('第 2 頁'), '頁數資訊更新：' + sheet.querySelector('[data-role="pageinfo"]').textContent);

  // Esc 關閉
  d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await wait(30);
  ok(!d.querySelector('.share-sheet'), 'Esc 關閉面板');

  // 空格 + 中文 URL：分享連結要 encode 一次，唔會 double-encode
  const cardA = cards(d).find(c => c.querySelector('h3').textContent === '幼童軍繩結章訓練班');
  click(w, cardA.querySelector('.share-btn')); await wait(50);
  click(w, d.querySelector('.share-sheet [data-act="copy-url"]')); await wait(30);
  ok(dom.clip.text === 'https://www.skwscout.org.hk/uploads/A%20%E5%B9%BC%E7%AB%A5%E8%BB%8D.pdf', '有空格／中文嘅附件網址會 percent-encode 一次：' + dom.clip.text);
  ok(cardA.querySelector('a.link').getAttribute('href') === dom.clip.text, '卡片「開啟附件」用同一條 encode 後網址');
  d.querySelector('.share-close').click(); await wait(30);

  // 非 PDF 連結 → 中文提示，唔會炸
  const cardF = cards(d).find(c => c.querySelector('h3').textContent === '灣仔區網頁通告');
  click(w, cardF.querySelector('.share-btn')); await wait(50);
  click(w, d.querySelector('.share-sheet [data-act="img"]')); await wait(120);
  const st = d.querySelector('.share-sheet [data-role="imgstatus"]');
  ok(st.classList.contains('err') && st.textContent.includes('唔係 PDF'), '網頁連結產生圖片 → 提示「唔係 PDF」：' + st.textContent.trim());
  ok(d.querySelector('.share-sheet [data-act="img-dl"]').disabled, '失敗時下載掣停用');
  d.querySelector('.share-close').click(); await wait(30);
  ok(!d.querySelector('.share-sheet'), '× 掣關閉面板');

  // 收藏夾都有分享掣 + 支部篩選
  click(w, cardB.querySelector('.star-btn')); await wait(30);
  click(w, $$(d, '.region > button').find(b => b.textContent.includes('我的收藏'))); await wait(60);
  ok(cards(d).length === 1 && cards(d)[0].querySelector('.share-btn'), '收藏夾卡片都有分享掣');
  click(w, chip(d, '幼童軍')); await wait(50);
  ok(cards(d).length === 0, '收藏夾都受支部標籤過濾（B 唔係幼童軍 → 0 張）');
  click(w, chip(d, '童軍')); await wait(50);
  ok(cards(d).length === 1, '收藏夾：童軍 → 1 張');

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.stack || e.message); process.exit(1); });
