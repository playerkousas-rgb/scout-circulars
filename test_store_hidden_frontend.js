// APP STORE「收埋」信號測試（2026-11-15 新規則）
//   用法： npm i jsdom && node test_store_hidden_frontend.js
//
// 新規則：曾經公開上架過嘅 app 喺 APP STORE 收埋（visible=false），
// 圖書館 *唔會刪* cache 記錄，而係靠 store-hidden.json 收埋——
//   1. 正常瀏覽／搜尋／側欄計數：全部收埋（卡片同數字都唔見）；
//   2. 「⭐ 我的收藏」：仍然見到，標示 ⚠️ 已下架，開啟掣鎖死變撳唔到；
//   3. store-hidden.json 缺檔／斷網／壞 JSON／格式唔啱：靜默當冇嘢收埋，UI 唔阻。
// 另外鎖住 Task 1：小工具卡嘅 .link rel = "noopener"（冇 noreferrer），通告卡保持 "noopener noreferrer"。
const {JSDOM} = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');

const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const now = Date.now();
const today = isoHKT(now);

const TOOL_VISIBLE = { title: '【助手】公開工具YYY', url: 'https://tool-visible.test/', pdf_url: 'https://tool-visible.test/',
  date: today, captured_date: today, source_site: 'Scout System', region: 'Scout System', tags: ['助手'] };
const TOOL_HIDDEN = { title: '【助手】秘密收埋工具ZZZ', url: 'https://tool-hidden.test/', pdf_url: 'https://tool-hidden.test/',
  date: today, captured_date: today, source_site: 'Scout System', region: 'Scout System', tags: ['助手'] };
const CIRCULAR = { title: '今日通告甲', url: 'https://circ.test/a.pdf', pdf_url: 'https://circ.test/a.pdf',
  date: today, captured_date: today, source_site: '總會', region: '總會' };

const cache = {
  last_updated: today,
  meta: { version: '5.11', total_notices: 3 },
  data: { 總會: [CIRCULAR], 'Scout System': [TOOL_VISIBLE, TOOL_HIDDEN] },
  _meta: { regions: { 總會: ['總會'], 'Scout System': ['Scout System'] },
           source_order: ['總會', 'Scout System'],
           expected_empty_sources: [], last_run: { error_sources: [] } },
};

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
const cards = (d) => [...d.querySelectorAll('#cards .card')];
const cardTitles = (d) => cards(d).map(c => c.querySelector('h3').textContent);

// hiddenDoc === undefined → 404；hiddenFails → reject（模擬斷網）；inline doc → 200。
function boot({ hiddenDoc, hiddenFails = false, storage } = {}) {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/',
    beforeParse(win) {
      win.fetch = (u) => {
        const s = String(u);
        if (s.includes('store-hidden.json')) {
          if (hiddenFails) return Promise.reject(new Error('network down'));
          if (hiddenDoc === undefined) return Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error('404')) });
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(hiddenDoc) });
        }
        if (s.includes('enrich')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        if (s.includes('subscription_catalog')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ topics: [] }) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cache) });
      };
      win.alert = () => {}; win.confirm = () => true;
      if (storage) for (const [k, v] of Object.entries(storage)) win.localStorage.setItem(k, v);
    },
  });
  return dom;
}

(async () => {
  // ── 場景一：正常瀏覽收埋（store-hidden 有值）──
  {
    const dom = boot({ hiddenDoc: { hidden: ['https://tool-hidden.test'] } });
    const w = dom.window, d = w.document;
    await wait(800);
    ok(!cardTitles(d).some(t => t.includes('秘密收埋工具ZZZ')),
       '全港瀏覽：收埋咗嘅小工具 ZZZ 唔出現');
    ok(cardTitles(d).some(t => t.includes('公開工具YYY')),
       '全港瀏覽：公開小工具 YYY 照常出現');
    ok(cardTitles(d).some(t => t.includes('今日通告甲')),
       '全港瀏覽：通告唔受影響');

    // 側欄 Scout System 計數：0/1（今日新上架 1? 不——YYY 係今日 → 1/1，ZZZ 唔計）
    const scoutRegion = [...d.querySelectorAll('#accordion .region')].find(sec =>
      sec.querySelector(':scope > button')?.textContent.includes('Scout System'));
    ok(!!scoutRegion, '側欄有 Scout System 區塊');
    ok(scoutRegion && scoutRegion.querySelector(':scope > button').textContent.includes('1/1'),
       '側欄 Scout System 徽章係 1/1（收埋嘅唔計，分子分母都剔走）：' +
       (scoutRegion?.querySelector(':scope > button').textContent.trim().replace(/\s+/g, ' ') || ''));

    // 撳入 Scout System「全部」分頁：卡片同計數對數
    click(w, scoutRegion.querySelector(':scope > button'));
    await wait(80);
    const allBtn = [...scoutRegion.querySelectorAll('.source-btn')]
      .find(b => b.textContent.includes('全部 (Scout System)'));
    click(w, allBtn);
    await wait(120);
    ok(!cardTitles(d).some(t => t.includes('ZZZ')), 'Scout System 分頁：ZZZ 唔出現');
    ok(cardTitles(d).some(t => t.includes('YYY')), 'Scout System 分頁：YYY 出現');
    ok(cards(d).length === 1, `Scout System 分頁只有 1 張卡（實際 ${cards(d).length}）`);
    ok(allBtn.textContent.includes('1 / 1'), 'Scout System「全部」計數 1 / 1 則：' + allBtn.textContent.trim().replace(/\s+/g, ' '));

    // 全港搜尋：收埋咗嘅關鍵字搜唔到，公開嘅搜得到
    const scopeGlobal = [...d.querySelectorAll('#scope-chips .scope-chip')].find(b => b.textContent.trim() === '全港搜尋');
    click(w, scopeGlobal);
    await wait(60);
    d.querySelector('#keyword').value = 'ZZZ';
    click(w, scopeGlobal); // 觸發一次重渲
    d.querySelector('#keyword').dispatchEvent(new w.InputEvent('input', {bubbles: true}));
    await wait(150);
    ok(cards(d).length === 0, '全港搜尋 ZZZ：0 張卡（收埋咗唔會出現）');
    d.querySelector('#keyword').value = 'YYY';
    d.querySelector('#keyword').dispatchEvent(new w.InputEvent('input', {bubbles: true}));
    await wait(150);
    ok(cards(d).some(c => c.textContent.includes('YYY')), '全港搜尋 YYY：搵到公開小工具');

    // ── Task 1：rel 屬性 ──
    const toolLink = cards(d).find(c => c.textContent.includes('YYY'))?.querySelector('.link');
    ok(toolLink && toolLink.getAttribute('rel') === 'noopener',
       `小工具卡 .link rel="noopener"（唔帶 noreferrer）：${toolLink?.getAttribute('rel')}`);
    d.querySelector('#keyword').value = '';
    d.querySelector('#keyword').dispatchEvent(new w.InputEvent('input', {bubbles: true}));
    const currentScope = [...d.querySelectorAll('#scope-chips .scope-chip')].find(b => b.classList.contains('active'));
    click(w, currentScope); // 切返目前分頁
    click(w, [...d.querySelectorAll('#window-chips .chip')].find(b => b.textContent.trim() === '今天'));
    await wait(150);
    // 通告係「目前分頁（ALL_SOURCES）」先會出；切返 Scout System 以外先睇到通告卡
    // 直接喺全港搜尋留低空關鍵字搵通告卡最穩陣
    click(w, scopeGlobal);
    await wait(100);
    const circCard = cards(d).find(c => c.textContent.includes('今日通告甲'));
    const circLink = circCard?.querySelector('.link');
    ok(circLink && circLink.getAttribute('rel') === 'noopener noreferrer',
       `通告卡 .link rel="noopener noreferrer"（保留）：${circLink?.getAttribute('rel')}`);
    const storeBadge = circCard?.querySelector('.badge');
    ok(storeBadge && !storeBadge.textContent.includes('SCOUT APP STORE'),
       '通告卡 badge 係來源名（冇 SCOUT APP STORE 字眼）');
    const toolCard = cards(d).find(c => c.textContent.includes('YYY'));
    ok(toolCard && toolCard.querySelector('.badge')?.textContent.includes('SCOUT APP STORE'),
       '小工具卡 badge 係 SCOUT APP STORE');

    dom.window.close();
  }

  // ── 場景二：⭐ 我的收藏 —— 收埋咗嘅 app 仍然見到，但標示已下架 + 鎖死開啟 ──
  {
    const saved = JSON.stringify({
      'https://tool-hidden.test/': {
        title: '【助手】秘密收埋工具ZZZ', pdf_url: 'https://tool-hidden.test/',
        url: 'https://tool-hidden.test/', source_site: 'Scout System',
        saved_at: new Date().toISOString(),
      },
    });
    const dom = boot({ hiddenDoc: { hidden: ['https://tool-hidden.test'] },
                       storage: { scl_bookmarks_v1: saved } });
    const w = dom.window, d = w.document;
    await wait(800);
    const bmChip = [...d.querySelectorAll('#window-chips .chip')].find(c => c.textContent.includes('收藏'));
    ok(/1/.test(bmChip.textContent), '★ 收藏掣顯示 1：' + bmChip.textContent.trim());
    click(w, bmChip);
    await wait(150);
    const bmCards = cards(d);
    ok(bmCards.length === 1, `收藏夾見到收埋咗嘅小工具（記錄保留）：${bmCards.length} 張`);
    const gone = bmCards[0];
    ok(gone.classList.contains('bm-gone'), '收藏夾卡片標示 bm-gone');
    ok(gone.textContent.includes('已下架'), '卡片上明示「已下架」：' + gone.textContent.match(/⚠️[^\n]*/)?.[0]);
    ok(!gone.textContent.includes('原站已移除'), '不會誤用通告嘅「原站已移除」字眼');
    const openLink = gone.querySelector('.link');
    ok(openLink && openLink.tagName === 'SPAN', '開啟掣唔係連結（鎖死）');
    ok(openLink && openLink.getAttribute('aria-disabled') === 'true', '開啟掣 aria-disabled="true"');
    ok(d.querySelector('#messages').textContent.includes('報唔到'), '頂部提示講明報唔到');
    ok(d.querySelector('#messages').textContent.includes('已下架'), '頂部提示講明 App Store 已下架');
    ok(!!gone.querySelector('.star-btn'), '★ 掣仲喺度（用戶可以自己取消收藏）');
    click(w, gone.querySelector('.star-btn'));
    await wait(120);
    ok(cards(d).length === 0, '撳 ★ 取消收藏 → 即刻消失');
    ok(!('https://tool-hidden.test/' in JSON.parse(w.localStorage.getItem('scl_bookmarks_v1'))),
       'localStorage 已移除該筆收藏');
    dom.window.close();
  }

  // ── 場景三：store-hidden.json 缺檔（404）──
  {
    const dom = boot({ hiddenDoc: undefined });
    const w = dom.window, d = w.document;
    await wait(800);
    ok(cardTitles(d).some(t => t.includes('ZZZ')) && cardTitles(d).some(t => t.includes('YYY')),
       '缺檔／404：兩個小工具照常出現（靜默降級）');
    dom.window.close();
  }

  // ── 場景四：store-hidden.json 斷網 ──
  {
    const dom = boot({ hiddenFails: true });
    const w = dom.window, d = w.document;
    await wait(800);
    ok(cardTitles(d).some(t => t.includes('ZZZ')) && cardTitles(d).some(t => t.includes('YYY')),
       '斷網：兩個小工具照常出現（靜默降級）');
    dom.window.close();
  }

  // ── 場景五：store-hidden.json 格式唔啱 ──
  {
    const dom = boot({ hiddenDoc: { hidden: 'not-an-array' } });
    const w = dom.window, d = w.document;
    await wait(800);
    ok(cardTitles(d).some(t => t.includes('ZZZ')) && cardTitles(d).some(t => t.includes('YYY')),
       '格式唔啱：兩個小工具照常出現（靜默降級）');
    dom.window.close();
  }

  // ── 場景六：兩個小工具都收埋 → 全館見唔到，計數 0/0，通告仍然見到 ──
  {
    const dom = boot({ hiddenDoc: { hidden: ['https://tool-hidden.test', 'https://tool-visible.test'] } });
    const w = dom.window, d = w.document;
    await wait(800);
    ok(!cardTitles(d).some(t => t.includes('ZZZ')) && !cardTitles(d).some(t => t.includes('YYY')),
       '兩個小工具都收埋 → 瀏覽唔見到');
    ok(cardTitles(d).some(t => t.includes('今日通告甲')), '通告照常出現');
    const scoutRegion = [...d.querySelectorAll('#accordion .region')].find(sec =>
      sec.querySelector(':scope > button')?.textContent.includes('Scout System'));
    ok(scoutRegion && scoutRegion.querySelector(':scope > button').textContent.includes('0/0'),
       '側欄 Scout System 徽章係 0/0：' + (scoutRegion?.querySelector(':scope > button').textContent.trim().replace(/\s+/g, ' ') || ''));
    dom.window.close();
  }


  // ── 場景七：通告卡（非小工具）唔會有已下架字眼；收藏嘅已消失通告維持原字眼 ──
  {
    const saved = JSON.stringify({
      'https://gone-circular.test/x.pdf': {
        title: '已被清走嘅舊通告', pdf_url: 'https://gone-circular.test/x.pdf',
        url: 'https://gone-circular.test/x.pdf', source_site: '總會',
        date: '2025-01-01', saved_at: new Date().toISOString(),
      },
    });
    const dom = boot({ hiddenDoc: { hidden: ['https://tool-hidden.test'] },
                       storage: { scl_bookmarks_v1: saved } });
    const w = dom.window, d = w.document;
    await wait(800);
    const bmChip = [...d.querySelectorAll('#window-chips .chip')].find(c => c.textContent.includes('收藏'));
    click(w, bmChip);
    await wait(150);
    const goneCard = cards(d).find(c => c.classList.contains('bm-gone'));
    ok(!!goneCard && goneCard.textContent.includes('原站已移除'),
       '已消失通告維持「原站已移除」字眼（測試迎合度：test_bookmarks.js 亦然）');
    dom.window.close();
  }

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e); process.exit(1); });
