// Scout System 側欄「有更新」綠燈測試（2026-10-06）
//   用法： npm i jsdom && node test_scout_system_light.js
//
// 用戶要求：Scout System 唔好一直著燈 —— 今日冇新上架就唔好著燈。
// 小工具係長期資產：側欄件數跟目前「今天／之前發布」視窗；綠色高亮仍然只計今日新上架。
// 「之前發布」模式下，舊工具亦要喺來源及內設分類旁邊正確顯示數量。
const { JSDOM } = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const now = Date.now();
const daysAgo = (n) => isoHKT(now - n * 86400000);

const mk = (title, url, src, date, region, tags) => ({
  title, url, pdf_url: url, date, captured_date: date, source_site: src, region, tags,
});

// 通告側嘅對照組：區會通告喺視窗內（預設「今天」）照樣著燈
// （唔可以因為呢次改動而熄晒）
const districtNotices = [
  mk('童軍技能訓練班', 'https://scout.org.hk/uploads/B.pdf', '筲箕灣區', isoHKT(now), '港島地域'),
  mk('半年前舊通告', 'https://example.test/old-circ', '筲箕灣區', daysAgo(200), '港島地域'),
];

function buildCache(tools, notices = districtNotices) {
  return {
    last_updated: isoHKT(now),
    data: { 筲箕灣區: notices, 'Scout System': tools },
    _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
  };
}

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };
const wait = (ms) => new Promise(r => setTimeout(r, ms));

function boot(cache) {
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
  return dom;
}

const $$ = (d, s) => [...d.querySelectorAll(s)];
const regionSection = (d, name) => $$(d, '#accordion .region').find(sec => {
  const btn = sec.querySelector(':scope > button');
  return !!btn && btn.querySelector('span').textContent.includes(name);
});
const regionBadge = (d, name) => {
  const sec = regionSection(d, name);
  return sec ? sec.querySelector(':scope > button .count-badge') : null;
};
const sourceBtn = (d, label) => $$(d, '#accordion .source-btn').find(b => {
  const span = b.querySelector('span');
  return !!span && span.textContent.trim() === label;
});
const lit = (el) => !!el && el.classList.contains('has-updates');

(async () => {
  // ── 1. 今日冇新上架：側欄照數「之前發布」資產，但唔著燈 ───────
  {
    const dom = boot(buildCache([
      Object.assign(mk('舊密碼遊戲', 'https://example.test/old-game', 'Scout System', daysAgo(200), 'Scout System'), { tags: ['遊戲'] }),
      mk('【助手】集會流程', 'https://example.test/helper', 'Scout System', daysAgo(40), 'Scout System'),
    ]));
    const w = dom.window, d = w.document;
    await wait(900);

    const ssSection = regionSection(d, 'Scout System');
    ok(!!ssSection, '側欄有 Scout System 一欄');
    ok(!lit(ssSection), '今日冇新上架 → Scout System 唔著綠燈');
    const badge = regionBadge(d, 'Scout System');
    ok(!!badge && badge.textContent.trim() === '2', '「之前發布」模式下側欄數兩件舊工具：' + (badge && badge.textContent));
    ok(!!badge && !badge.classList.contains('hot'), '今日冇新上架，badge 唔發綠光（冇 hot class）');
    ok((ssSection.querySelector(':scope > button').title || '').includes('今日冇新上架'),
       'tooltip 講明今日冇新上架：' + ssSection.querySelector(':scope > button').title);

    const allBtn = sourceBtn(d, '全部 (Scout System)');
    ok(!!allBtn && !lit(allBtn), '「全部 (Scout System)」都唔著燈');
    ok(!!allBtn && allBtn.querySelector('small').textContent.trim() === '2 則', '「全部」顯示之前發布嘅 2 件工具');

    const kinds = ['助手', '遊戲', '系統', '工具', '其他', '連結'].map(k => sourceBtn(d, k)).filter(Boolean);
    ok(kinds.length === 6, '內設六類掣齊：' + kinds.length);
    ok(kinds.every(b => !lit(b)), '六類冇一個著燈（今日冇新上架）');
    ok(!!sourceBtn(d, '遊戲') && sourceBtn(d, '遊戲').querySelector('small').textContent.trim() === '1 則',
       '「遊戲」喺之前發布有 1 件，即使今日 0 件都唔顯示 0');
    ok(!!sourceBtn(d, '助手') && sourceBtn(d, '助手').querySelector('small').textContent.trim() === '1 則',
       '「助手」之前發布數量正確');

    // 對照組：地域／區會通告喺視窗內 → 照樣著燈，唔可以一併熄晒
    ok(lit(regionSection(d, '港島地域')), '地域（港島地域）有今日新通告 → 照樣著燈');
    ok(!!regionBadge(d, '港島地域') && regionBadge(d, '港島地域').classList.contains('hot'), '地域 badge 照樣 hot');
    ok(lit(sourceBtn(d, '筲箕灣區')), '區會（筲箕灣區）掣照樣著燈');
    ok(lit(sourceBtn(d, '全部 (港島地域)')), '地域「全部」掣照樣著燈');
    ok(lit(regionSection(d, '全港 (所有層級)')), '全港列照樣著燈（區會通告帶住）');

    dom.window.close();
  }

  // ── 2. 今日有新上架：只嗰類著燈 ────────────────────────────────
  {
    const dom = boot(buildCache([
      Object.assign(mk('舊密碼遊戲', 'https://example.test/old-game', 'Scout System', daysAgo(200), 'Scout System'), { tags: ['遊戲'] }),
      Object.assign(mk('【遊戲】今日新計時器', 'https://example.test/new-game', 'Scout System', isoHKT(now), 'Scout System'), { tags: ['遊戲'] }),
      mk('【助手】集會流程', 'https://example.test/helper', 'Scout System', daysAgo(40), 'Scout System'),
    ]));
    const w = dom.window, d = w.document;
    await wait(900);

    ok(lit(regionSection(d, 'Scout System')), '今日有新上架 → Scout System 著綠燈');
    const badge = regionBadge(d, 'Scout System');
    ok(!!badge && badge.classList.contains('hot') && badge.textContent.trim() === '3', 'badge 數 3 件已發布工具，並因今日有更新發綠光：' + (badge && badge.textContent));
    ok(lit(sourceBtn(d, '遊戲')), '「遊戲」類有新工具 → 著燈');
    ok(sourceBtn(d, '遊戲').querySelector('small').textContent.trim() === '2 則', '遊戲類一新一舊，共顯示 2 件');
    ok(sourceBtn(d, '全部 (Scout System)').querySelector('small').textContent.trim() === '3 則', 'Scout System 全部顯示 3 件');
    ok(!lit(sourceBtn(d, '助手')), '「助手」類今日冇新 → 唔著燈');
    ok(!!sourceBtn(d, '助手') && sourceBtn(d, '助手').querySelector('small').textContent.trim() === '1 則', '「助手」目前「之前發布」顯示 1 件');
    ok(lit(sourceBtn(d, '全部 (Scout System)')), '「全部 (Scout System)」著燈');

    const allScoutSource = sourceBtn(d, '全部 (Scout System)');
    if (allScoutSource) allScoutSource.click();
    const todayWindow = $$(d, '#window-chips button').find(b => b.textContent.trim() === '今天更新/發布');
    ok(!!todayWindow, 'Scout System 有「今天」切換掣');
    if (todayWindow) todayWindow.click();
    ok(!!regionBadge(d, 'Scout System') && regionBadge(d, 'Scout System').textContent.trim() === '1',
       '切到「今天」後，Scout System 側欄件數同步變 1');
    ok(sourceBtn(d, '遊戲').querySelector('small').textContent.trim() === '1 則',
       '切到「今天」後，遊戲分類件數同步變 1');
    ok(sourceBtn(d, '助手').querySelector('small').textContent.trim() === '0 則',
       '切到「今天」後，舊助手分類件數同步變 0');
    const allToolsWindow = $$(d, '#window-chips button').find(b => b.textContent.trim() === '之前發布');
    if (allToolsWindow) allToolsWindow.click();
    ok(!!regionBadge(d, 'Scout System') && regionBadge(d, 'Scout System').textContent.trim() === '3',
       '切返「之前發布」後，側欄恢復顯示全部 3 件');

    dom.window.close();
  }

  // ── 3. 昨日上架（過咗午夜）就要熄燈 ────────────────────────────
  {
    const dom = boot(buildCache([
      Object.assign(mk('【遊戲】尋日新計時器', 'https://example.test/y-game', 'Scout System', daysAgo(1), 'Scout System'), { tags: ['遊戲'] }),
    ]));
    const w = dom.window, d = w.document;
    await wait(900);
    ok(!lit(regionSection(d, 'Scout System')), '尋日上架（唔係今日）→ 唔著燈');
    const badge = regionBadge(d, 'Scout System');
    ok(!!badge && !badge.classList.contains('hot') && badge.textContent.trim() === '1', 'badge 顯示 1 件舊工具但唔發光');
    ok(!lit(sourceBtn(d, '遊戲')), '尋日新嘅「遊戲」都唔著燈');
    dom.window.close();
  }

  // ── 4. 區會通告跌出「今天」視窗 → 區會都熄燈（證明燈號真係跟視窗，唔係寫死）──
  {
    const dom = boot(buildCache(
      [mk('【助手】集會流程', 'https://example.test/helper', 'Scout System', daysAgo(40), 'Scout System')],
      [mk('半年前舊通告', 'https://example.test/old-circ', '筲箕灣區', daysAgo(200), '港島地域')],
    ));
    const w = dom.window, d = w.document;
    await wait(900);
    ok(!lit(regionSection(d, '港島地域')), '區會通告全部跌出「今天」視窗 → 地域熄燈');
    ok(!lit(sourceBtn(d, '筲箕灣區')), '區會掣都熄燈');
    ok(!lit(regionSection(d, 'Scout System')), '同一版面 Scout System 都熄燈');
    ok(!lit(regionSection(d, '全港 (所有層級)')), '全港列冇嘢新 → 熄燈');
    dom.window.close();
  }

  // ── 5. 通告分類「小工具」直入 Scout System，並重設成「之前發布」──
  {
    const dom = boot(buildCache(
      [mk('【助手】舊集會流程', 'https://example.test/helper-old', 'Scout System', daysAgo(40), 'Scout System')],
      [mk('今日區會通告', 'https://example.test/today-circ', '筲箕灣區', isoHKT(now), '港島地域')],
    ));
    const d = dom.window.document;
    await wait(900);

    const scoutButton = sourceBtn(d, '全部 (Scout System)');
    ok(!!scoutButton, '側欄可進入 Scout System');
    if (scoutButton) scoutButton.click();
    const todayToolWindow = $$(d, '#window-chips button').find(b => b.textContent.trim() === '今天更新/發布');
    ok(!!todayToolWindow, 'Scout System 顯示專用「今天更新/發布」視窗');
    if (todayToolWindow) todayToolWindow.click();

    const districtButton = sourceBtn(d, '筲箕灣區');
    ok(!!districtButton, '可返回區會通告視圖');
    if (districtButton) districtButton.click();
    const genericToolsChip = d.querySelector('#category-chips [data-cat="tools"]');
    ok(!!genericToolsChip && genericToolsChip.textContent.trim() === '小工具', '通告分類有「小工具」選項');
    if (genericToolsChip) genericToolsChip.click();

    const toolWindows = $$(d, '#window-chips button');
    const beforePublished = toolWindows.find(b => b.textContent.trim() === '之前發布');
    const activeKindChips = $$(d, '#category-chips [data-cat]');
    ok(d.querySelector('#page-title')?.textContent.trim() === 'Scout System',
       '選「小工具」後主視圖切到 Scout System');
    ok(d.querySelector('#category-chips')?.previousElementSibling?.textContent.includes('小工具'),
       '分類列切換成 Scout System 內設小工具分類');
    ok(activeKindChips.length === 6 && activeKindChips.some(b => b.textContent.trim() === '助手'),
       'Scout System 六個內設分類已顯示');
    ok(!!beforePublished && beforePublished.classList.contains('active'),
       '由通告進入時重設為「之前發布」，唔沿用先前嘅「今天」');
    ok(!!regionBadge(d, 'Scout System') && regionBadge(d, 'Scout System').textContent.trim() === '1',
       '直入後舊小工具已計入側欄件數');

    const noticeModeChip = d.querySelector('#category-chips [data-mode="notices"]');
    ok(!!noticeModeChip && noticeModeChip.textContent.trim() === '通告',
       '小工具專屬標籤前面有「通告」返回標籤');
    if (noticeModeChip) noticeModeChip.click();
    ok(d.querySelector('#page-title')?.textContent.trim() === '筲箕灣區',
       '撳「通告」後返回進入小工具前嘅區會');
    ok(d.querySelector('#category-chips')?.previousElementSibling?.textContent.includes('分類'),
       '返回後分類標籤列恢復一般「分類」模式');
    ok(!!d.querySelector('#category-chips [data-cat="tools"]')
       && d.querySelector('#category-chips [data-cat="tools"]').textContent.trim() === '小工具',
       '通告模式嘅一般分類標籤已恢復（包括「小工具」）');
    ok(!d.querySelector('#category-chips [data-mode="notices"]'),
       '返回通告模式後收起 Scout System 專屬返回標籤');
    ok($$(d, '#window-chips button').some(b => b.textContent.trim() === '7天'),
       '返回後恢復通告日期範圍掣');
    dom.window.close();
  }

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.stack || e.message); process.exit(1); });
