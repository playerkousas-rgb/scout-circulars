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

function fakeFetch(win) {
  return (u, opts) => {
    const s = String(u);
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
  const p2iBtn = sheet.querySelector('[data-act="pdf2img"]');
  ok(!!p2iBtn && !!sheet.querySelector('[data-role="pdfshare"]'), '分享面板有「轉換內文做圖」掣＋其「分享圖片」掣');
  ok(!!sheet.querySelector('[data-role="pdfcopy"]') && !!sheet.querySelector('[data-role="pdfdl"]'),
     'PDF 圖有「下載圖片」＋「複製圖片」掣（電腦版唔使靠系統分享）');
  ok($$(d, '[data-role="pdfsocial"] button[data-act="img-target"]').map(b => b.dataset.target).join(',') === 'wa,tg,fb,x',
     'PDF 圖有「貼去 WhatsApp／Telegram／Facebook／X」四個掣（電腦版複製＋開平台）');
  click(w, p2iBtn); await wait(160);
  ok(d.querySelector('.share-toast') && (d.querySelector('.share-toast').textContent || '').includes('轉換唔到'),
     'jsdom 載入唔到 pdf.js → 有 toast 回饋，唔會靜靜失敗');

  // ── PDF 落款（廣告位，2026-09-22）：同純文字分享同一句落款＋該通告深鏈 ──
  const footer = w.eval('pdfImageFooter({source_site:"筲箕灣區",title:"童軍技能訓練班",pdf_url:"' + PDF_B + '",url:"' + PDF_B + '"},2,3)');
  ok(footer.title === '【筲箕灣區】童軍技能訓練班', '落款第一行：【區會】標題：' + footer.title);
  ok(footer.credit === '經 通告圖書館 v5.11 整理 @noscout.system',
     '落款第二行同純文字分享第 3 行一樣：' + footer.credit);
  ok(/^完整通告＋最新截止日期：example\.org\/\?n=[0-9a-f]{16}$/.test(footer.linkLine),
     '落款第三行係該通告嘅專屬深鏈：' + footer.linkLine);
  ok(footer.page === '第 2 / 3 版', '多版 PDF 會標明版本：' + footer.page);
  ok(w.eval('pdfImageFooter({title:"單版通告"},{pdf_url:"x",url:"x"},1,1).page') === '',
     '單版 PDF 唔會多餘標「第 1 / 1 版」');
  ok(html.includes('composePdfImage(cv, item, num, pdfDoc.numPages'), 'renderPdfPage 真係用 composePdfImage 落款');
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

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.stack || e.message); process.exit(1); });
