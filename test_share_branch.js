// index.html 分享 + 支部標籤功能測試
//   用法： npm i jsdom && node test_share_branch.js
//
// 重點驗證：
//   1. 支部標籤：9 個（全部 + 8 支部），單選、再撳取消、唔顯示數字
//   2. 「童軍」唔會命中「幼童軍 / 深資童軍 / 樂行童軍」（audience 同標題都係）
//   3. 冇 audience 嘅通告退而求其次用標題（機構名唔特別處理，用戶可配合關鍵字）
//   4. 舊嘅「成員（精準）/ 支部」欄位同「只顯示明確日期」已移除
//   5. 分享面板：社交連結、複製網址（附件直連）、複製文字
//   6. IG 分享圖（2026-09-21）：client-side canvas 產生＋預覽＋下載＋複製 Caption
//      紅線：仍然唔准用 server-side /api/render（Vercel bundle 瘦身維持不變）
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
      mk('半年前舊通告', 'https://example.test/old-circ', '筲箕灣區', daysAgo(200), '港島地域'),
      mk('幼童軍繩結章訓練班', PDF_A, '筲箕灣區', iso(today), '港島地域'),           // audience: 幼童軍
      mk('童軍技能訓練班', PDF_B, '筲箕灣區', iso(today), '港島地域'),               // audience: 童軍、領袖
      mk('深資童軍海上旅程', PDF_C, '筲箕灣區', daysAgo(20), '港島地域'),           // 冇 enrich → 標題：深資童軍
      mk('旅團註冊須知', PDF_D, '筲箕灣區', iso(today), '港島地域'),                 // 冇 enrich → 標題冇任何支部詞
      mk('樂行童軍暨領袖交流日', PDF_E, '筲箕灣區', iso(today), '港島地域'),       // audience: 所有成員
      mk('灣仔區網頁通告', HTML_F, '筲箕灣區', iso(today), '港島地域'),            // 網頁，唔係 PDF
    ],
    'Scout System': [
      Object.assign(mk('舊密碼遊戲', 'https://example.test/old-game', 'Scout System', daysAgo(200), 'Scout System'), { tags: ['遊戲', '幼童軍'] }),
      Object.assign(mk('【助手】集會流程', 'https://example.test/helper', 'Scout System', daysAgo(40), 'Scout System'), {}),
    ],
  },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};
const enrich = {
  [PDF_A]: { audience: '幼童軍', deadline: '2026-09-20', fee: 'HK$50', categories: [{ id: 'training', label: '訓練班' }] },
  [PDF_B]: { audience: '童軍、領袖', deadline: '', fee: '', categories: [{ id: 'training', label: '訓練班' }] },
  [PDF_E]: { audience: '所有成員', deadline: '', fee: '', categories: [{ id: 'service', label: '服務' }] },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));

// stories 分支 index（專屬頁 hero 用）；測試中途會改寫
let storyIndex = {
  version: 1,
  items: [{ k: PDF_B, f: 'stories/2026-09-21/00_train_blue_abc123.png', t: '童軍技能訓練班' }],
};

// 轉換內文做圖測試用：假 PDF bytes 同假回應
const PDF_BYTES = new TextEncoder().encode('%PDF-1.4\n% fake notice\n%%EOF\n');
const pdfResp = (bytes) => ({
  ok: true, status: 200, body: null,
  headers: { get: (k) => ({ 'content-type': 'application/pdf', 'content-length': String(bytes.length) })[String(k).toLowerCase()] || null },
  arrayBuffer: () => Promise.resolve(bytes.slice().buffer),
});
const jsonResp = (status, payload) => ({
  ok: false, status, body: null,
  headers: { get: (k) => (String(k).toLowerCase() === 'content-type' ? 'application/json' : null) },
  json: () => Promise.resolve(payload),
});

function fakeFetch(win) {
  return (u, opts) => {
    const s = String(u);
    // win.__pdfRoute（測試自己設）：接管 PDF 直連同 /api/pdf-proxy，其餘照舊
    if (win.__pdfRoute) {
      const routed = win.__pdfRoute(s, opts);
      if (routed) return routed;
    }
    if (s.includes('enrich')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(enrich) });
    if (s.includes('/stories/stories/index.json')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(storyIndex) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cache) });
  };
}

// opts.touch === false → 扮「電腦」（jsdom 本身有 ontouchstart，所以當手機係預設）
function boot(qs = '', opts = {}) {
  const clip = { text: null, items: null };
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/' + qs,
    pretendToBeVisual: true,
    beforeParse(win) {
      win.fetch = fakeFetch(win);
      win.alert = () => {}; win.confirm = () => true;
      win.URL.createObjectURL = () => 'blob:fake'; win.URL.revokeObjectURL = () => {};
      if (opts.touch === false) {
        // 冇 touch 特徵（isTouchLikeDevice() → false），即係電腦版
        try { delete win.ontouchstart; } catch (_) {}
        Object.defineProperty(win.navigator, 'maxTouchPoints', { value: 0, configurable: true });
      }
      // 「貼去平台」開新分頁（jsdom 冇實作 window.open）
      win.__opened = [];
      win.open = (url) => {
        const tab = { location: { href: url || '' }, closed: false, close() { this.closed = true; } };
        win.__opened.push(tab);
        return tab;
      };
      if (typeof win.ClipboardItem === 'undefined') {
        win.ClipboardItem = class ClipboardItem { constructor(data) { this.data = data; } };
      }
      // 「直接分享」測試용：扮支援 Web Share files，落個 spy 落 win.__shared
      win.__shared = [];
      Object.defineProperty(win.navigator, 'canShare', { value: () => true, configurable: true });
      Object.defineProperty(win.navigator, 'share', { value: (data) => { win.__shared.push(data); return Promise.resolve(); }, configurable: true });
      // IG 分享圖測試用：jsdom 冇真 canvas，落個假 2d context（逐字 18px 當量度）
      const fakeGradient = { addColorStop() {} };
      win.HTMLCanvasElement.prototype.getContext = function () {
        return {
          measureText: (t) => ({ width: String(t).length * 18 }),
          fillRect() {}, strokeRect() {}, fillText() {}, beginPath() {}, closePath() {},
          moveTo() {}, lineTo() {}, arc() {}, arcTo() {}, save() {}, restore() {},
          translate() {}, rotate() {}, scale() {}, stroke() {}, fill() {}, rect() {}, clip() {},
          createLinearGradient: () => fakeGradient, createRadialGradient: () => fakeGradient,
        };
      };
      win.HTMLCanvasElement.prototype.toBlob = function (cb) { cb(new win.Blob(['png'], { type: 'image/png' })); };
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

  // ── 1.5 分類標籤 ──
  const catLabels = $$(d, '#category-chips .chip').map(c => c.textContent.trim());
  ok(JSON.stringify(catLabels) === JSON.stringify(['全部', '訓練', '服務', '活動', '比賽', '小工具', '未分類']),
     '分類標籤次序正確：' + catLabels.join(' '));
  ok(cards(d).length === 5, `分類標籤未影響預設「今天」5 張（實際 ${cards(d).length}）`);
  click(w, $$(d, '#category-chips .chip').find(c => c.textContent.trim() === '訓練')); await wait(50);
  ok(titles(d).length === 2 && titles(d).includes('幼童軍繩結章訓練班') && titles(d).includes('童軍技能訓練班'),
     '分類「訓練」過濾出訓練班：' + titles(d).join(' | '));
  ok(cards(d).every(c => c.querySelector('.cat-tags')), '卡片顯示分類標籤');
  click(w, $$(d, '#category-chips .chip').find(c => c.textContent.trim() === '全部')); await wait(50);
  ok(cards(d).length === 5, '分類切返「全部」恢復 5 張');

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
  ok(waHref.includes('【筲箕灣區】童軍技能訓練班童軍、領袖'), '精簡格式：對象直接黐住標題（B 只有對象）');
  ok(waHref.includes('\n詳情：' + PDF_B + '\n---經 通告圖書館 v5.11 整理 @noscout.system'), '第 2 行詳情連結、第 3 行落款（v5.11 + IG handle）');
  ok(!waHref.includes('參加資格：') && !waHref.includes('費用：') && !waHref.includes('截止報名：'), '舊嘅逐行 label 格式已移除');
  const fbHref = $$(d, '.share-sheet a.fb')[0].href;
  ok(fbHref.startsWith('https://www.facebook.com/sharer/sharer.php?u=') && decodeURIComponent(fbHref).includes(PDF_B), 'Facebook sharer 帶附件網址');
  ok($$(d, '.share-sheet a[data-act="link"]').every(a => a.target === '_blank' && a.rel.includes('noopener')), '社交連結新分頁 + noopener');

  click(w, sheet.querySelector('[data-act="copy-url"]')); await wait(30);
  ok(dom.clip.text === PDF_B, '「複製網址」複製附件直連：' + dom.clip.text);
  click(w, sheet.querySelector('[data-act="copy-text"]')); await wait(30);
  ok(dom.clip.text.includes('【筲箕灣區】童軍技能訓練班') && dom.clip.text.includes('詳情：' + PDF_B), '「複製文字」= 標題行 + 詳情網址');
  ok(dom.clip.text.endsWith('---經 通告圖書館 v5.11 整理 @noscout.system'), '「複製文字」結尾係圖書館落款（v5.11 + IG handle）');
  // Telegram：url 參數渲染附件連結，text 有落款但唔會重複詳情行
  const tgHref = decodeURIComponent($$(d, '.share-sheet a.tg')[0].href);
  ok(tgHref.includes('url=') && tgHref.includes('@noscout.system') && !(tgHref.split('text=')[1] || '').includes('詳情：'),
     'Telegram text 跟落款、唔重複詳情行');
  ok(d.querySelector('.share-toast') && d.querySelector('.share-toast').textContent.includes('已複製'), '複製後有 toast 提示');

  // IG 分享圖（2026-09-21）：client-side canvas 版。紅線不變：唔准 server-side render endpoint
  ok(!html.includes('/api/render'), '保持紅線：index.html 唔引用 /api/render（Vercel bundle 維持瘦身）');
  ok(html.includes('renderIgImage') && html.includes('canvas.toBlob'), 'IG 圖用 client-side canvas 產生（toBlob→objectURL）');
  const igBtn = sheet.querySelector('[data-act="ig"]');
  ok(!!igBtn, '分享面板有「產生 IG 分享圖」掣');
  click(w, igBtn); await wait(80);
  const igBox = sheet.querySelector('[data-role="igbox"]');
  ok(igBox && !igBox.hidden, '產生完顯示預覽區');
  ok(igBox.querySelector('img').src === 'blob:fake', '預覽圖係 objectURL（冇寫檔、冇上傳，關面板 revoke）');
  const igDl = igBox.querySelector('[data-role="igdl"]');
  ok(!!igDl && igDl.href === 'blob:fake' && /^通告圖書館-筲箕灣區-\d{8}\.png$/.test(igDl.getAttribute('download') || ''),
     '「下載圖片」有 objectURL + 中文檔名：' + (igDl && igDl.getAttribute('download')));
  click(w, igBox.querySelector('[data-act="copy-caption"]')); await wait(30);
  ok(dom.clip.text && dom.clip.text.startsWith('【筲箕灣區】童軍技能訓練班')
     && dom.clip.text.endsWith('---經 通告圖書館 v5.11 整理 @noscout.system'),
     '「複製 Caption」= 新三款分享文案（貼去 IG 用）');
  // 「直接分享」（Web Share files）：一撳彈系統分享直接揀 IG／WhatsApp
  const igShareBtn = igBox.querySelector('[data-role="igshare"]');
  ok(!!igShareBtn && !igShareBtn.hidden, '手機支援 Web Share files 時「直接分享」掣會出現');
  click(w, igShareBtn); await wait(50);
  ok(w.__shared.length === 1 && /^通告圖書館-筲箕灣區-\d{8}\.png$/.test(w.__shared[0]?.files?.[0]?.name || ''),
     '「直接分享」拎住中文檔名 PNG 彈 navigator.share(files)');

  // Story 直向版（1080×1920）：admin 出 Story；4:5 feed 版照舊係預設
  const storyBtn = igBox.querySelector('[data-role="igstory"]');
  ok(!!storyBtn, 'IG 盒有「📱 Story 版」切換掣（feed 4:5 預設不變）');
  click(w, storyBtn); await wait(60);
  ok(igBox.querySelector('[data-role="igdl"]').download.includes('-story.png')
     && storyBtn.textContent.includes('4:5'),
     '切去 Story 版：檔名加 -story、掣變「返去 4:5 版」');
  click(w, igShareBtn); await wait(50);
  ok(w.__shared.length === 2 && /-story\.png$/.test(w.__shared[1]?.files?.[0]?.name || ''),
     'Story 模式下「直接分享」拎住 -story.png');
  click(w, storyBtn); await wait(60);
  ok(!igBox.querySelector('[data-role="igdl"]').download.includes('-story')
     && storyBtn.textContent.includes('Story 版'),
     '再切返 4:5：檔名同掣面都還原');

  // ── 12 款設計（2026-09-22）：同 Actions 草稿（Pillow render_story_templates.py）
  //    同一套款、同一個揀款算法（md5(url) % pool），所以 app 出嘅圖同草稿係同一款 ──
  const DESIGN_IDS = ['train_blue', 'train_orange', 'train_green', 'competition_gold_black',
    'activity_army', 'service_wanted', 'unc_scope', 'unc_topsecret', 'unc_glitch',
    'unc_wanted_parchment', 'unc_wanted_red', 'unc_wanted_blackfin'];
  ok(w.eval('md5Hex("")') === 'd41d8cd98f00b204e9800998ecf8427e'
     && w.eval('md5Hex("abc")') === '900150983cd24fb0d6963f7d28e17f72'
     && w.eval('md5Hex("通告")') === 'ec8914bcafa641cb122a396181b0801e',
     '內建 MD5 同 hashlib 對齊（空字串／abc／中文向量；唔用 TextEncoder，舊機都有）');
  ok(w.eval('posterAutoDesignId({pdf_url:"https://x/1.pdf"},{categories:[{id:"training"}]})') === 'train_blue'
     && w.eval('posterAutoDesignId({pdf_url:"https://x/2.pdf"},{categories:[{id:"training"}]})') === 'train_orange'
     && w.eval('posterAutoDesignId({pdf_url:"https://x/1.pdf"},{categories:[{id:"competition"}]})') === 'competition_gold_black'
     && w.eval('posterAutoDesignId({pdf_url:"https://x/1.pdf"},{})') === 'unc_wanted_parchment',
     '揀款算法跟 Pillow：md5(pdf_url) % pool（訓練 3 款 / 比賽 1 款 / 其他 6 款，hash 固定唔會日日變樣）');
  ok(w.eval('posterAutoDesignId({pdf_url:"https://x/1.pdf",category:"service"},{})') === 'service_wanted',
     'queue 出嘅 flat category 都揀得中（service → WANTED 羊皮紙）');
  const designWrap = igBox.querySelector('[data-role="igdesigns"]');
  const designBtns = designWrap ? [...designWrap.querySelectorAll('button')] : [];
  ok(designBtns.map(b => b.dataset.id).join(',') === DESIGN_IDS.join(','),
     '12 款縮圖次序同 Pillow POOLS 一致：' + designBtns.map(b => b.dataset.id).join(' '));
  ok(designBtns.every(b => b.dataset.act === 'ig-design' && b.title.includes('換款')), '縮圖掣帶款名 tooltip');
  ok(designBtns.filter(b => b.classList.contains('active')).length === 1
     && designBtns.find(b => b.classList.contains('active')).dataset.id === 'train_blue',
     '第一次出圖會自動亮起跟分類嗰款（B 卡 = 訓練 → train_blue）');
  const dlName0 = igBox.querySelector('[data-role="igdl"]').download;
  click(w, designBtns.find(b => b.dataset.id === 'unc_topsecret')); await wait(80);
  ok(designBtns.find(b => b.dataset.id === 'unc_topsecret').classList.contains('active')
     && designBtns.filter(b => b.classList.contains('active')).length === 1,
     '撳「通告・絕密檔案」→ 即換款（只有佢 active）');
  ok(igBox.querySelector('[data-role="igdl"]').download === dlName0 && igBox.querySelector('img').src === 'blob:fake',
     '換款只換畫法，檔名／預覽機制不變');
  click(w, designBtns.find(b => b.dataset.id === 'unc_topsecret')); await wait(60);
  ok(designBtns.find(b => b.dataset.id === 'unc_topsecret').classList.contains('active'),
     '再撳同一款：no-op，唔會彈返自動款');

  // ── Story／4:5：冇白框、冇頒佈欄、冇絕密黑條、兩邊都有直連 QR；標語只限自動化（2026-09-24）──
  ok(!html.includes("rows.push(['頒佈'"), '資料卡唔再重複頒佈（上方日期行已經有）');
  ok(!html.includes('rgba(255,255,255,.95)'), '區徽唔再加白框');
  ok(!html.includes('兩粒「刪節」黑條') && !html.includes('L.dateY - 150'), '絕密檔案唔再畫兩粒黑色不知名框');
  ok(!html.includes('掃碼開原文附件'), 'QR 冇說明字，得白圓角方');
  const storyL = w.eval('posterLayout')(
    { title: '港島通告', date: '2026-09-24', region: '港島地域', pdf_url: 'https://x/1.pdf', source_site: '港島地域' },
    { deadline: '2026-10-01', audience: '童軍', fee: 'HK$10' },
    'story',
    { headline: null },
  );
  ok(storyL.rows.map(r => r[0]).join(',') === '截止,對象,費用', 'story 資料卡得截止／對象／費用：' + storyL.rows.map(r => r[0]).join(','));
  ok(storyL.qr && storyL.qr.size >= 180
     && storyL.qr.y + storyL.qr.size <= storyL.dateY - 40
     && storyL.qr.x + storyL.qr.size === storyL.W - storyL.MX
     && storyL.zone.y1 <= storyL.qr.y - 8
     && storyL.qr.y >= storyL.badge.y + storyL.badge.size,
     'story 靠右預留 QR，唔蓋日期行、標題、區徽');
  const feedL = w.eval('posterLayout')(
    { title: 't', date: '2026-09-24', pdf_url: 'https://x/1.pdf' },
    { deadline: '2026-10-01' },
    'feed',
    {},
  );
  ok(feedL.qr && feedL.qr.size >= 160
     && feedL.qr.y + feedL.qr.size <= feedL.dateY - 40
     && feedL.zone.y1 <= feedL.qr.y - 8
     && feedL.rows.every(r => r[0] !== '頒佈'),
     '4:5 同樣有 QR，唔蓋日期行／標題，亦冇頒佈欄');
  ok(w.eval('storySloganFor')({ slogan: '自定標語', category: 'training' }) === '自定標語', '自動化排隊時配咗標語就用返');
  const trainLines = ['解鎖新技能','Skill Up!','學多樣，識多樣','今日學，明日用','升級進行中','成為更勁嘅自己','新手都歡迎','學到就係你嘅'];
  ok(w.eval('storySloganFor')({ pdf_url: 'https://x/1.pdf', category: 'training' }) === '',
     '手動分享（冇配標語）唔加標語：用戶自己喺 IG 加字，更彈性');
  ok(w.eval('Object.keys(STORY_SLOGANS).sort().join()') === 'activity,competition,service,training',
     '標語得四類八句（同 story_queue.STORY_SLOGANS 一致），冇 app 專用「其他」類');
  {
    const assigned = w.eval('assignStorySlogans')([{ category: 'training' }, { category: 'training' }, { category: 'other' }]);
    ok(assigned[0].slogan === trainLines[0] && assigned[1].slogan === trainLines[1] && !assigned[2].slogan,
       '?batch=1 出圖台照配標語：同分類逐張輪流（同 story_queue.py），「其他」唔配');
  }
  {
    // 真係畫一次：兩個版都係一塊直連 QR，冇說明字、冇第二層白底；標語只限自動化 Story
    const paints = [];
    const stub = {
      fillStyle: '',
      beginPath() {}, moveTo() {}, arcTo() {}, closePath() {},
      fill() { paints.push(['fill', this.fillStyle]); },
      fillRect() { paints.push(['rect', this.fillStyle]); },
    };
    w.drawPosterQr(stub, PDF_B, 10, 20, 200);
    ok(paints.filter((p) => p[0] === 'fill' && p[1] === '#FFFFFF').length === 1
       && !paints.some((p) => p[0] === 'rect' && p[1] === '#FFFFFF')
       && paints.some((p) => p[0] === 'rect' && p[1] === '#111111'),
       'QR 得一塊白圓角方，模組係黑格，冇第二層白底');
    const texts = [];
    const proto = w.HTMLCanvasElement.prototype;
    const origGet = proto.getContext;
    proto.getContext = function () {
      const c = origGet.apply(this, arguments);
      c.fillText = (t) => { texts.push(String(t)); };
      return c;
    };
    w.eval(`
      window.__qrCalls = [];
      window.__origDrawPosterQr = drawPosterQr;
      drawPosterQr = function(ctx, url, x, y, size) {
        window.__qrCalls.push({ url, x, y, size });
        return window.__origDrawPosterQr(ctx, url, x, y, size);
      };
    `);
    const base = { title: '手動測試', pdf_url: PDF_B, url: PDF_B, source_site: '筲箕灣區', region: '港島地域', date: iso(today), category: 'training' };
    w.eval('renderPoster')(base, { mode: 'story', design: 'auto' });
    const manualTexts = texts.splice(0);
    const manualQr = w.__qrCalls.splice(0);
    w.eval('renderPoster')(Object.assign({}, base, { slogan: trainLines[3] }), { mode: 'story', design: 'auto' });
    const autoTexts = texts.splice(0);
    const autoQr = w.__qrCalls.splice(0);
    w.eval('renderPoster')(base, { mode: 'feed', design: 'auto' });
    const feedTexts = texts.splice(0);
    const feedQr = w.__qrCalls.splice(0);
    proto.getContext = origGet;
    w.eval('drawPosterQr = window.__origDrawPosterQr');
    const allLines = Object.values(w.eval('STORY_SLOGANS')).flat();
    const exB = w.eval('state').enrich[PDF_B] || null;
    const design0 = w.eval('POSTER_DESIGNS')[0];
    const storyLay = w.eval('posterLayout')(base, exB, 'story', design0);
    const feedLay = w.eval('posterLayout')(base, exB, 'feed', design0);
    ok(manualQr.length === 1 && manualQr[0].url === PDF_B
       && manualQr[0].x === storyLay.qr.x && manualQr[0].y === storyLay.qr.y && manualQr[0].size === storyLay.qr.size
       && !manualTexts.includes('掃碼開原文附件') && !manualTexts.some((t) => allLines.includes(t)),
       '手動 Story 版：預留位一塊直連 QR，冇說明字、冇標語');
    ok(autoQr.length === 1 && autoTexts.includes(trainLines[3]) && !autoTexts.includes('掃碼開原文附件'),
       '自動化 Story（有 item.slogan）：標語＋QR，冇說明字');
    ok(feedQr.length === 1 && feedQr[0].url === PDF_B
       && feedQr[0].x === feedLay.qr.x && feedQr[0].y === feedLay.qr.y && feedQr[0].size === feedLay.qr.size
       && !feedTexts.includes('掃碼開原文附件') && !feedTexts.some((t) => allLines.includes(t)),
       '4:5 同樣一塊直連 QR，冇說明字、冇標語');
  }
  const qr = w.eval('posterQrMatrix')('https://scout.org.hk/uploads/B.pdf');
  ok(qr && qr.length === 29 && qr[0].slice(0, 7).join('') === '1111111' && qr[14][14] === 1 && qr[28][28] === 1,
     'Story QR 同 Python qrcode（byte／EC-M／mask 0）對齊，直連通告附件');
  click(w, storyBtn); await wait(80);   // 揀咗款之後切 Story：款要跟住行
  ok(igBox.querySelector('[data-role="igdl"]').download.includes('-story.png')
     && designBtns.find(b => b.dataset.id === 'unc_topsecret').classList.contains('active'),
     '揀咗「絕密檔案」再切 Story：款保留、只換 9:16 版型');
  click(w, storyBtn); await wait(80);
  ok(!igBox.querySelector('[data-role="igdl"]').download.includes('-story')
     && designBtns.find(b => b.dataset.id === 'unc_topsecret').classList.contains('active'),
     '切返 4:5：款照樣保留');

  // PDF 內容出圖（pdf.js client-side；bytes 經 stdlib /api/pdf-proxy byte bridge 入）
  ok(html.includes('cdn.jsdelivr.net/npm/pdfjs-dist@4'), 'pdf.js 由 CDN lazy-load（唔入 repo、唔入 Vercel bundle）');
  ok(html.includes('/api/pdf-proxy?u='), 'PDF bytes 經 /api/pdf-proxy 過橋（CORS 冇開嘅區會站先要用）');
  ok(w.eval('LOCAL_PDF_MAX') === 20 * 1024 * 1024 && w.eval('PROXY_PDF_MAX') === 4 * 1024 * 1024,
     '本機畫圖上限 20MB；Vercel 單次回應仍然 4MB');
  const plan20 = w.eval('pdfBytePlan')(20 * 1024 * 1024);
  ok(plan20.ok && plan20.mode === 'slices' && plan20.chunks.every(c => c.n <= 4 * 1024 * 1024)
     && plan20.chunks.reduce((s, c) => s + c.n, 0) === 20 * 1024 * 1024,
     '20MB 分片每片 ≤4MB，拼齊先喺本機畫');
  ok(w.eval('pdfBytePlan')(20 * 1024 * 1024 + 1).ok === false, '超過 20MB 唔再畫');
  ok(w.eval('driveDirectUrl')('https://drive.google.com/file/d/ABC-1_x/view')
     === 'https://drive.google.com/uc?export=download&id=ABC-1_x',
     'Drive 分享頁轉直連，本機先試自己條網');
  ok(html.includes('loadNoticePdfBytes'), '轉換內文做圖經本機下載（直接／分片），唔再硬食 4MB 全檔');
  const p2iBtn = sheet.querySelector('[data-act="pdf2img"]');
  ok(!!p2iBtn && !!sheet.querySelector('[data-role="pdfshare"]'), '分享面板有「轉換內文做圖」掣＋其「分享圖片」掣');
  ok(!!sheet.querySelector('[data-role="pdfcopy"]') && !!sheet.querySelector('[data-role="pdfdl"]'),
     'PDF 圖有「下載圖片」＋「複製圖片」掣（電腦版唔使靠系統分享）');
  ok($$(d, '[data-role="pdfsocial"] button[data-act="img-target"]').map(b => b.dataset.target).join(',') === 'wa,tg,fb,x',
     'PDF 圖有「貼去 WhatsApp／Telegram／Facebook／X」四個掣（電腦版複製＋開平台）');
  click(w, p2iBtn); await wait(160);
  ok(d.querySelector('.share-toast') && (d.querySelector('.share-toast').textContent || '').includes('轉換唔到：載入唔到 PDF 轉換器'),
     'jsdom 載入唔到 pdf.js → toast 講明係轉換器載入唔到（唔再一律話來源站連唔到）');

  // ── 轉換內文做圖：成功路徑（2026-09-24）──
  // 之前冇測成功路徑：renderPdfPage 用咗未宣告嘅 nav，畫完圖即刻 ReferenceError，
  // 預覽被收埋再誤報「來源站連唔到」—— 所有通告都中，測試照樣全綠。
  ok(w.eval('driveDirectUrl')(HTML_F) === '', 'Drive 直連只認 Google 網域：灣仔 index.php?…&id=1 唔會被當 Drive');
  ok(w.eval('driveDirectUrl')('https://docs.google.com/uc?export=download&id=Q1') === 'https://drive.google.com/uc?export=download&id=Q1',
     'docs.google.com 嘅 ?id= 照樣認到');
  {
    const msg = (code) => w.eval('pdfFailMessage')({ code });
    ok(msg('pdf_too_large').startsWith('呢份 PDF 超過 20MB'), '20MB 提示照舊');
    ok(msg('not_a_pdf').includes('唔係 PDF'), 'not_a_pdf → 講明附件唔係 PDF：' + msg('not_a_pdf'));
    ok(msg('upstream_unreachable').includes('圖書館橋攞唔到'), 'upstream_unreachable → 講明係圖書館橋攞唔到');
    ok(msg('not_a_listed_notice').includes('重新整理'), 'not_a_listed_notice → 叫用戶重新整理');
    ok(msg('proxy_timeout').includes('逾時') && msg('pdf_password').includes('密碼') && msg('pdf_render_failed').includes('畫圖途中'),
       '逾時／密碼／畫圖失敗各有字眼');
    ok(msg('proxy_http_500').includes('proxy_http_500') && msg('constructor').includes('constructor'),
       '未知 code 照印出嚟方便報錯（唔會撞 Object.prototype）');
    ok(['not_a_pdf', 'upstream_unreachable', 'proxy_unreachable', 'pdfjs_load_failed', 'pdf_invalid', 'x']
         .every((c) => msg(c).startsWith('轉換唔到：')), '失敗提示一律「轉換唔到：」開頭');
  }
  {
    const domP = boot();
    const wP = domP.window, dP = wP.document;
    await wait(700);
    const calls = { direct: [], proxy: [], getDocument: [], destroyed: 0 };
    let proxyMode = 'ok', directMode = 'cors_block';
    wP.__pdfRoute = (u, opts) => {
      if (u.startsWith('/api/pdf-proxy?u=')) {
        calls.proxy.push(u);
        if (proxyMode === 'ok') return Promise.resolve(pdfResp(PDF_BYTES));
        if (proxyMode === 'not_a_pdf') return Promise.resolve(jsonResp(415, { ok: false, error: 'not_a_pdf' }));
        if (proxyMode === 'upstream') return Promise.resolve(jsonResp(502, { ok: false, error: 'upstream_unreachable' }));
        if (proxyMode === 'vercel504') {
          return Promise.resolve({ ok: false, status: 504, body: null, headers: { get: () => 'text/html' },
            json: () => Promise.reject(new SyntaxError('Unexpected token <')) });
        }
        if (proxyMode === 'offline') return Promise.reject(new TypeError('Failed to fetch'));
      }
      if (/^https?:\/\/[^/]*scout\.org\.hk\/uploads\//.test(u) || u.startsWith('https://drive.google.com/uc?')) {
        calls.direct.push({ u, signal: !!(opts && opts.signal) });
        if (directMode === 'cors_ok') return Promise.resolve(pdfResp(PDF_BYTES));
        return Promise.reject(new TypeError('Failed to fetch'));   // 冇 CORS：瀏覽器即刻拒絕
      }
      return null;
    };
    // 假 pdf.js：3 版，每版 600×800
    wP.__fakePdfjs = {
      GlobalWorkerOptions: {},
      getDocument: (o) => {
        calls.getDocument.push(o);
        return { promise: Promise.resolve({
          numPages: 3,
          getPage: () => Promise.resolve({
            getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }),
            render: () => ({ promise: Promise.resolve() }),
          }),
          destroy: () => { calls.destroyed++; },
        }) };
      },
    };
    wP.eval('pdfjsPromise = Promise.resolve(window.__fakePdfjs)');
    const openPdf = async (title) => {
      $$(dP, '.share-close').forEach((b) => click(wP, b));
      $$(dP, '.share-toast').forEach((t) => t.remove());
      const card = cards(dP).find((c) => c.querySelector('h3').textContent === title);
      click(wP, card.querySelector('.share-btn')); await wait(60);
      const sh = dP.querySelector('.share-sheet');
      click(wP, sh.querySelector('[data-act="pdf2img"]')); await wait(250);
      return sh;
    };
    const toastText = () => (dP.querySelector('.share-toast')?.textContent || '');

    // (a) 冇 CORS 嘅區會站 → 圖書館橋 → 畫到第 1 版，多版有換版掣
    let sh = await openPdf('童軍技能訓練班');
    let box = sh.querySelector('[data-role="pdfbox"]');
    const nav = box.querySelector('[data-role="pdfnav"]');
    ok(calls.direct.length === 1 && calls.direct[0].signal, '先試用戶自己條網（帶 AbortController，唔會吊死）');
    ok(calls.proxy.length === 1, '冇 CORS → 轉用圖書館橋');
    ok(calls.getDocument.length === 1 && w.eval('isPdfBytes')(calls.getDocument[0].data)
       && /standard_fonts\/$/.test(calls.getDocument[0].standardFontDataUrl || ''),
       'pdf.js 收到 %PDF bytes（連 cMap／標準字型設定）');
    ok(!box.hidden && box.querySelector('img').src === 'blob:fake', '成功畫圖：預覽保留，唔會畫完即刻收埋');
    ok(box.querySelector('[data-role="pdfpage"]').textContent === '第 1 / 3 版', '版數標示：第 1 / 3 版');
    ok(!nav.hidden && nav.querySelector('[data-act="pdf-prev"]').disabled && !nav.querySelector('[data-act="pdf-next"]').disabled,
       '多版 PDF 顯示換版掣（第 1 版：上一版 disabled、下一版可撳）');
    ok(!toastText().includes('轉換唔到'), '成功路徑冇「轉換唔到」誤報：' + toastText());
    ok(box.querySelector('[data-role="pdfdl"]').download.endsWith('-p1.png'), '下載檔名帶版數 -p1.png');
    click(wP, nav.querySelector('[data-act="pdf-next"]')); await wait(120);
    ok(box.querySelector('[data-role="pdfpage"]').textContent === '第 2 / 3 版'
       && !nav.querySelector('[data-act="pdf-prev"]').disabled
       && box.querySelector('[data-role="pdfdl"]').download.endsWith('-p2.png'),
       '撳「下一版」→ 第 2 / 3 版，上一版解鎖，下載檔名 -p2.png');
    ok(!toastText(), '換版冇錯誤提示');

    // (b) 來源有 CORS（例如 Contentful）→ 用戶自己條網就夠，唔使經 Vercel
    directMode = 'cors_ok'; calls.proxy.length = 0;
    sh = await openPdf('幼童軍繩結章訓練班');
    box = sh.querySelector('[data-role="pdfbox"]');
    ok(!box.hidden && calls.proxy.length === 0, 'CORS 開咗嘅來源：本機直接下載，零 Vercel');
    directMode = 'cors_block';

    // (c) 每種失敗講清楚原因（之前一律「來源站連唔到」）
    const failCase = async (mode, expect, label) => {
      proxyMode = mode;
      const sh2 = await openPdf('旅團註冊須知');
      const t = toastText();
      ok(sh2.querySelector('[data-role="pdfbox"]').hidden && t.includes(expect), label + '：' + t);
    };
    await failCase('not_a_pdf', '唔係 PDF', '圖書館橋回 415 not_a_pdf');
    await failCase('upstream', '圖書館橋攞唔到', '圖書館橋回 502 upstream_unreachable');
    await failCase('vercel504', '逾時', 'Vercel 504（HTML 錯誤頁，唔係 JSON）');
    await failCase('offline', '連唔到圖書館橋', '部機斷網（fetch reject）');
    proxyMode = 'ok';
    domP.window.close();
  }

  // ── PDF 落款：只印分享文案嗰句，黑字、半號、唔加底色條 ──
  const footer = w.eval('pdfImageFooter({source_site:"筲箕灣區",title:"童軍技能訓練班",pdf_url:"' + PDF_B + '",url:"' + PDF_B + '"},2,3)');
  ok(footer.credit === '---經 通告圖書館 v5.11 整理 @noscout.system',
     '落款只得分享文案嗰句（連開頭 ---）：' + footer.credit);
  ok(!footer.linkLine && !footer.page && !footer.title,
     '唔再印深鏈、版數、標題');
  ok(html.includes('composePdfImage(cv, item, num, pdfDoc.numPages'), 'renderPdfPage 真係用 composePdfImage 落款');
  // ── PDF 內文本機生圖：全部版數一次過出（2026-09-23）──
  ok(html.includes('data-act="pdf-all"'), '有「💾 全部版數」掣');
  ok(html.includes('async function renderAllPdfPages'), '有 renderAllPdfPages：一次過出齊所有版');
  ok(html.includes("showDirectoryPicker({ id: 'pdf-notice-images'"),
     '全部版數支援 File System Access（揀資料夾一次寫入）');
  ok(/await new Promise\(\(r\) => setTimeout\(r, 320\)\);\s*\/\/ 畀瀏覽器逐張落載/.test(html),
     '唔支援資料夾時逐張下載（320ms 間隔，唔會互相取消）');
  ok(html.includes('每張圖底部都印住圖書館落款'), '提示講明每版都有落款');
  ok(/oldCredit \/ 2/.test(html.slice(html.indexOf('function composePdfImage'), html.indexOf('function composePdfImage') + 1600)),
     '落款字級用而家廣告主字嘅一半');
  ok(!html.slice(html.indexOf('function composePdfImage'), html.indexOf('function composePdfImage') + 1600).includes('#0d1626'),
     '唔再加深藍底色條');
  ok(html.includes("ctx.fillStyle = '#000000'"), '落款用黑字印喺白底通告上');
  ok(!/pdfImageFooter\(item, pageNum, pageCount\)[\s\S]{0,400}badgeImg\.width/.test(
       html.slice(html.indexOf('function composePdfImage'), html.indexOf('function composePdfImage') + 2600)),
     '精簡落款唔再畫區徽大格（純文字，唔搶通告版面）');
  {
    // jsdom 嘅假 canvas 冇 drawImage：落款唔可以因此失去張圖（fail-safe）
    const fakePage = d.createElement('canvas');
    fakePage.width = 800; fakePage.height = 1100;
    const fakeItem = { source_site: '筲箕灣區', title: 'x', pdf_url: PDF_B, url: PDF_B };
    const out = w.eval('composePdfImage')(fakePage, fakeItem, 1, 1, null);
    ok(out === fakePage, '落款畫唔到（環境唔支援）就原圖照出，唔會冇咗張圖');
  }

  // ── 圖片分享掣規則：手機＝系統分享；電腦＝複製圖片＋「貼去平台」 ──
  const uiMobile = w.eval('imageShareUi(true,true)'), uiMobileNoShare = w.eval('imageShareUi(true,false)'), uiDesktop = w.eval('imageShareUi(false,true)');
  ok(uiMobile.system === true && uiMobile.social === false, '手機＋支援 Web Share → 出「分享圖片」，唔出「貼去…」');
  ok(uiMobileNoShare.system === false && uiMobileNoShare.social === false, '手機但唔支援 Web Share（例如 App 內置瀏覽器）→ 兩個都唔出，用「複製圖片」');
  ok(uiDesktop.system === false && uiDesktop.social === true, '電腦 → 唔出系統分享（嗰個面板分享唔到去社交平台），出「貼去…」');
  {
    ok(sheet.querySelector('[data-role="igsocial"]').hidden, '手機面板：唔出「貼去…」列（直接用系統分享）');
    // 電腦版：複製圖片 ＋「貼去 WhatsApp／Telegram…」＝複製＋開平台＋貼上
    const domD = boot('', { touch: false });
    const wD = domD.window, dD = wD.document;
    await wait(700);
    const cardD = [...dD.querySelectorAll('#cards .card')].find(c => c.querySelector('h3').textContent === '童軍技能訓練班');
    click(wD, cardD.querySelector('.share-btn')); await wait(60);
    const sheetD = dD.querySelector('.share-sheet');
    click(wD, sheetD.querySelector('[data-act="ig"]')); await wait(90);
    const boxD = sheetD.querySelector('[data-role="igbox"]');
    ok(boxD && !boxD.hidden, '電腦版：照樣出到 IG 圖預覽');
    ok(sheetD.querySelector('[data-role="igshare"]').hidden, '電腦版：「分享圖片」（系統分享）收埋唔出，唔會似壞咗');
    ok(!sheetD.querySelector('[data-role="igsocial"]').hidden && !boxD.querySelector('[data-role="igcopy"]').hidden,
       '電腦版：「貼去…」列同「複製圖片」都出齊');
    click(wD, boxD.querySelector('[data-role="igcopy"]')); await wait(40);
    ok(domD.clip.items && domD.clip.items.length === 1, '「複製圖片」真係寫咗 ClipboardItem 落剪貼板');
    ok((dD.querySelector('.share-toast')?.textContent || '').includes('已複製圖片'), '複製完有 toast 提你貼去邊');
    click(wD, sheetD.querySelector('[data-role="igsocial"] button[data-target="tg"]')); await wait(60);
    ok(wD.__opened.length === 1 && wD.__opened[0].location.href === 'https://web.telegram.org/a/',
       '撳「貼去 Telegram」→ 開 Telegram 網頁預備貼圖');
    ok(domD.clip.items.length === 1 && (dD.querySelector('.share-toast')?.textContent || '').includes('Ctrl'),
       '同時複製咗圖片，toast 教貼上（Ctrl／⌘+V）');
    click(wD, sheetD.querySelector('[data-role="pdfsocial"] button[data-target="wa"]')); await wait(40);
    ok((dD.querySelector('.share-toast')?.textContent || '').includes('請先產生圖片'),
       '未出 PDF 圖就撳「貼去 WhatsApp」→ 有提示，唔會靜靜冇反應');
  }

  // ── 今日草稿出圖台（?batch=1）：本機批次出圖 ──────────────────────
  // 揀通告邏輯要同 story_queue.py 一致（今日新入庫、join enrich、排除小工具、按日期排序）
  {
    const cache2 = {
      last_updated: '2026-09-22',
      data: {
        筲箕灣區: [
          mk('未來 A', PDF_A, '筲箕灣區', iso(today), '港島地域'),
          mk('未來 B', PDF_B, '筲箕灣區', iso(today), '港島地域'),
          mk('尋日嘅', PDF_C, '筲箕灣區', daysAgo(1), '港島地域'),
        ],
        深水埗西區: [mk('未來 C', PDF_D, '深水埗西區', iso(today), '九龍地域')],
        'Scout System': [mk('小工具公告', PDF_E, 'Scout System', iso(today), '港島地域')],
      },
    };
    const enrich2 = {
      [PDF_A]: { deadline: '2026-12-01', categories: [{ id: 'training' }] },
      [PDF_B]: { deadline: '2026-09-30', categories: [{ id: 'activity', subtype: 'competition' }] },
      [PDF_D]: { deadline: '', categories: [{ id: 'service' }] },
    };
    const todayIso = iso(today);
    const q = w.eval('batchQueueToday')(cache2, enrich2, todayIso, 20);
    ok(q.length === 3, `出圖台只揀今日新入庫（3 張，實際 ${q.length}）：尋日嗰張同小工具都唔入`);
    ok(!q.some(x => x.title === '小工具公告'), '「Scout System」小工具唔出 Story（同 story_queue.py 一致）');
    ok(q.find(x => x.title === '未來 B') && q.find(x => x.title === '未來 B').category === 'competition',
       'enrich 有 activity+subtype=competition → 當比賽（同 story_queue.py 一致）');
    ok(q.find(x => x.title === '未來 A').audience === '' || q.find(x => x.title === '未來 A').category === 'training',
       'enrich join：deadline／category 有跟入 item');
    ok(w.eval('batchQueueToday')(cache2, enrich2, todayIso, 2).length === 2, 'limit 生效（limit=2）');
    ok(w.eval('batchCategory')({ title: '某某錦標賽通告', source_site: 'x' }, null) === 'competition'
       && w.eval('batchCategory')({ title: '義工服務日', source_site: 'x' }, null) === 'service'
       && w.eval('batchCategory')({ title: '隨意標題', source_site: 'x' }, null) === 'other',
       '冇 enrich 時按標題關鍵字分類（比賽／服務／其他）');
    ok(/^02_unc_scope_柴灣區-\d{8}\.png$/.test(w.eval('batchFileName')({ source_site: '柴灣區', date: '2026-09-22' }, 2, false, 'unc_scope')),
       '檔名有次序＋款＋區會＋日期，唔會撞名：' + w.eval('batchFileName')({ source_site: '柴灣區', date: '2026-09-22' }, 2, false, 'unc_scope'));
  }
  {
    // ?batch=1 真係開到出圖台（jsdom 冇 showDirectoryPicker，會走逐張下載路線）
    const domB = boot('?batch=1');
    const dB = domB.window.document;
    await wait(900);
    const view = dB.querySelector('.batch-backdrop');
    ok(!!view, '?batch=1 → 彈出「今日草稿出圖台」');
    ok(view && /今日草稿出圖台/.test(view.textContent) && /全部儲存到資料夾/.test(view.textContent),
       '出圖台有標題同「全部儲存到資料夾」掣');
    const figs = view ? [...view.querySelectorAll('.batch-card')] : [];
    ok(figs.length === 5, `出圖台列出今日 5 張（實際 ${figs.length}）—— ?limit 可以收窄（純函數測試已蓋）`);
    ok(figs.every(f => f.querySelector('button')), '每張卡都有「⬇ 下載」掣');
    const sel = view.querySelector('[data-role="batchdesign"]');
    ok(sel && sel.options.length === 13 && sel.options[0].value === 'auto',
       '款選擇器＝自動＋12 款');
    click(domB.window, view.querySelector('[data-role="batchmode"]'));
    await wait(80);
    ok(view.querySelector('[data-role="batchmode"]').textContent.includes('4:5'),
       '撳「出 Story 版」→ 變「出 4:5 feed 版」（切換 work）');
    // 日期／範圍：可以補做之前幾日，唔會淨係得今日
    const before = view.querySelectorAll('.batch-card').length;
    const rangeSel = view.querySelector('[data-role="batchrange"]');
    rangeSel.value = '30';   // fixture 有一張 20 日前嘅通告，用 30 日範圍包返佢
    rangeSel.dispatchEvent(new domB.window.Event('change', { bubbles: true }));
    await wait(200);
    const after = view.querySelectorAll('.batch-card').length;
    ok(after > before, `範圍揀「連近 30 日」→ 卡片由 ${before} 變 ${after} 張（補做舊通告）`);
    ok(/起近 30 日/.test(view.querySelector('[data-role="batchmeta"]').textContent),
       '標題行講明而家睇緊邊段日期');
    const todayIso = iso(today);
    const mkR = (title, dt, src) => ({ title, url: 'https://x/' + encodeURIComponent(title), pdf_url: 'https://x/' + encodeURIComponent(title), date: dt, captured_date: dt, source_site: src, region: src });
    const cacheR = { data: { 筲箕灣區: [mkR('今日一', iso(today), '筲箕灣區'), mkR('尋日嘅', daysAgo(1), '筲箕灣區'), mkR('上月嘅', daysAgo(30), '筲箕灣區')] } };
    ok(w.eval('batchQueueRange')(cacheR, {}, [todayIso, daysAgo(1)], 20).length === 2,
       'batchQueueRange 食多日：今日 1 + 尋日 1 ＝ 2 張');
    ok(w.eval('batchQueueRange')(cacheR, {}, [daysAgo(1)], 20)[0].title === '尋日嘅',
       '指定日子即刻出得返嗰日嘅通告（?date= 補做）');
    ok(w.eval('batchQueueRange')(cacheR, {}, [daysAgo(29)], 20).length === 0,
       '範圍以外嘅日子唔會偷走出嚟（30 日前唔算近 30 日）');
    click(domB.window, view.querySelector('.batch-close'));
    await wait(30);
    ok(!dB.querySelector('.batch-backdrop'), '× 關得返');
    // 冇 ?batch 就唔會彈（日常使用零影響）
    const domN = boot();
    await wait(700);
    ok(!domN.window.document.querySelector('.batch-backdrop'), '冇 ?batch 時唔會出現出圖台');
  }

  // 「複製連結」＝ 通告專屬頁深鏈（IG Story link sticker 就貼呢條）
  const copyLinkBtn = sheet.querySelector('[data-act="copy-link"]');
  ok(!!copyLinkBtn, '「分享至」grid 有「複製連結」掣');
  click(w, copyLinkBtn); await wait(30);
  ok(/^https:\/\/example\.org\/\?n=[0-9a-f]{16}$/.test(dom.clip.text || ''),
     '複製出嚟嘅係 ?n=<16hex> 深鏈：' + dom.clip.text);
  const noticeDeepLink = dom.clip.text;

  // Esc 關閉
  d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await wait(30);
  ok(!d.querySelector('.share-sheet'), 'Esc 關閉面板');

  // ── 專屬頁著陸 round-trip：貼返條深鏈入瀏覽器 → 直接彈出嗰張通告 ──
  {
    const dom2 = boot('?n=' + noticeDeepLink.split('?n=')[1]);
    const w2 = dom2.window, d2 = w2.document;
    await wait(700);
    const page = d2.querySelector('.notice-page');
    ok(!!page && page.querySelector('h2').textContent.includes('童軍技能訓練班'),
       '深鏈著陸：專屬頁直接彈出嗰張通告');
    ok(d2.title.includes('童軍技能訓練班'), '專屬頁會改 document.title 俾分享預覽');
    const hero = page.querySelector('.np-hero');
    ok(!!hero && hero.querySelector('img')?.src.endsWith('stories/2026-09-21/00_train_blue_abc123.png')
       && hero.getAttribute('href').includes('stories/stories/2026-09-21/'),
       '專屬頁 hero：今日有 Story 草稿就插喺頁頂（熱連結 stories 分支）');
    click(w2, page.querySelector('[data-act="nplink"]')); await wait(30);
    ok(dom2.clip.text === noticeDeepLink, '專屬頁「複製專屬連結」複製返同一條深鏈');
    click(w2, page.querySelector('[data-act="npclose"]')); await wait(30);
    ok(!d2.querySelector('.notice-page') && !d2.title.includes('童軍技能訓練班'),
       '「入返全圖書館」收回頁面＋還原 title');
    // index 冇呢張通告（未出草稿/過咗 7 日）→ 靜靜略過，頁面照舊
    storyIndex = { version: 1, items: [{ k: 'https://example.org/no-such.pdf', f: 'stories/2026-09-21/xx.png' }] };
    const dom4 = boot('?n=' + noticeDeepLink.split('?n=')[1]);
    await wait(700);
    ok(!!dom4.window.document.querySelector('.notice-page')
       && !dom4.window.document.querySelector('.np-hero'),
       '冇草稿命中 → 專屬頁照開但冇 hero（唔會破版）');
    // 唔存在嘅 id：靜靜提示，唔會白屏
    const dom3 = boot('?n=0123456789abcdef');
    await wait(700);
    ok(!dom3.window.document.querySelector('.notice-page')
       && (dom3.window.document.querySelector('.share-toast')?.textContent || '').includes('沉底'),
       '垃圾 id → toast 提示＋唔開頁');
  }


  // 空格 + 中文 URL：分享連結要 encode 一次，唔會 double-encode
  const cardA = cards(d).find(c => c.querySelector('h3').textContent === '幼童軍繩結章訓練班');
  click(w, cardA.querySelector('.share-btn')); await wait(50);
  const waA = decodeURIComponent($$(d, '.share-sheet a.wa')[0].href);
  ok(waA.includes('【筲箕灣區】幼童軍繩結章訓練班幼童軍｜HK$50｜截止 2026-09-20'), 'A 卡三項資料齊：對象黐標題、其餘 ｜ 分隔');
  click(w, d.querySelector('.share-sheet [data-act="copy-url"]')); await wait(30);
  ok(dom.clip.text === 'https://www.skwscout.org.hk/uploads/A%20%E5%B9%BC%E7%AB%A5%E8%BB%8D.pdf', '有空格／中文嘅附件網址會 percent-encode 一次：' + dom.clip.text);
  ok(cardA.querySelector('a.link').getAttribute('href') === dom.clip.text, '卡片「開啟附件」用同一條 encode 後網址');
  d.querySelector('.share-close').click(); await wait(30);

  // 非 PDF（網頁）通告：分享面板照開，只餘連結分享
  const cardF = cards(d).find(c => c.querySelector('h3').textContent === '灣仔區網頁通告');
  click(w, cardF.querySelector('.share-btn')); await wait(50);
  ok(d.querySelector('.share-sheet [data-act="copy-url"]'), '網頁通告分享面板仍可複製網址');
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

  // ── Scout System 內設分類 + 6個月包含 6 個月以上（通告唔適用）──
  {
    const domS = boot();
    const wS = domS.window, dS = wS.document;
    await wait(800);
    const kindLabels = ['助手', '遊戲', '系統', '工具', '其他', '連結'];
    const sideKinds = $$(dS, '.source-btn span').map(s => s.textContent.trim()).filter(t => kindLabels.includes(t));
    ok(JSON.stringify(sideKinds) === JSON.stringify(kindLabels),
       'Scout System 側欄內設六類：' + sideKinds.join(' '));
    click(wS, $$(dS, '#window-chips .chip').find(b => b.textContent.trim() === '6個月'));
    await wait(80);
    ok(titles(dS).includes('舊密碼遊戲'), '6個月視窗包含 6 個月以上的 Scout System');
    ok(!titles(dS).includes('半年前舊通告'), '6個月視窗唔包含 6 個月以上的通告');
    const oldCard = cards(dS).find(c => c.querySelector('h3').textContent === '舊密碼遊戲');
    ok(!!oldCard && oldCard.textContent.includes('6個月以上') && oldCard.textContent.includes('遊戲'),
       'Scout System 卡片標「6個月以上」同內設分類');
    click(wS, $$(dS, '.source-btn').find(b => b.querySelector('span')?.textContent.trim() === '遊戲'));
    await wait(80);
    ok(titles(dS).includes('舊密碼遊戲') && !titles(dS).includes('【助手】集會流程'),
       '撳「遊戲」只見遊戲：' + titles(dS).join(' | '));
    const kindChips = $$(dS, '#category-chips .chip').map(c => c.textContent.trim());
    ok(JSON.stringify(kindChips) === JSON.stringify(kindLabels),
       '入咗 Scout System，分類掣改成內設六類：' + kindChips.join(' '));
    ok($$(dS, '#category-chips .chip').find(c => c.textContent.trim() === '遊戲').classList.contains('active'),
       '遊戲分類掣呈 active');
    domS.window.close();
  }

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.stack || e.message); process.exit(1); });
