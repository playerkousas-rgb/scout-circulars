// 驗證：手機版重新顯示區會聯絡 icon（FB／IG／YT／官網／地圖／電話／電郵）
const {JSDOM} = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const css = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));
const mobileCss = css.slice(css.indexOf('@media (max-width: 980px)'));

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };

// ── CSS 靜態檢查 ──
ok(!/\.hero > h2, \.hero > #page-subtitle, \.hero > \.contact-bar \{ display: none !important; \}/.test(mobileCss),
   '手機 media query 唔再隱藏 .contact-bar');
ok(!mobileCss.match(/\.contact-bar[^}]*display:\s*none/),
   '手機 CSS 內冇任何隱藏 contact-bar 規則');
ok(css.includes('.contact-bar:empty { display: none; }'),
   '空聯絡 bar 自動收起（唔佔位）');
ok(mobileCss.includes('.hero > .contact-bar .contact-ico { width: 36px; height: 36px; }'),
   '手機聯絡 icon 縮細至 36px 慳位');
ok(html.includes('if (c.web && /^https?:\\/\\//i.test(c.web))'),
   '官網欄位係佔位文字（如「待新網址上架」）時唔 render 死鏈');

// ── DOM 渲染檢查 ──
const HKT_OFFSET = 8 * 3600 * 1000;
const isoHKT = (ms) => new Date(ms + HKT_OFFSET).toISOString().slice(0, 10);
const today = isoHKT(Date.now());
const cache = {
  last_updated: today,
  meta: { total_notices: 1 },
  data: { '總會': [{ title: '童軍繩結訓練班', pdf_url: 'https://example.test/a.pdf',
    url: 'https://example.test/a.pdf', date: today, captured_date: today,
    source_site: '總會', region: '全港' }] },
  _meta: { expected_empty_sources: [], last_run: { error_sources: [] } },
};
const wait = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously', url: 'https://example.org/',
    beforeParse(win) {
      win.fetch = (u) => Promise.resolve({ ok: true, status: 200,
        json: () => Promise.resolve(String(u).includes('enrich') ? {} : cache) });
      win.alert = () => {}; win.confirm = () => true;
    },
  });
  const d = dom.window.document;
  await wait(700);

  const bar = d.querySelector('#contact-bar');
  ok(!!bar, 'DOM 有 #contact-bar');

  // 預設係 ALL_SOURCES（bar 應該清空），切入單一區會「總會」後先有聯絡 icon
  ok(bar.innerHTML === '', 'ALL_SOURCES 全港視角 bar 清空（配合 :empty 唔佔位）');
  const srcBtn = [...d.querySelectorAll('.source-btn')].find(b => b.textContent.includes('總會'));
  ok(!!srcBtn, 'sidebar 搵到「總會」來源掣');
  srcBtn.dispatchEvent(new dom.window.MouseEvent('click', {bubbles: true}));
  await wait(80);

  const links = [...bar.querySelectorAll('a.contact-ico')];
  const kinds = links.map(a => a.className.replace('contact-ico ', ''));
  console.log('   總會分頁顯示 icon：', kinds.join('、'));
  ok(kinds.includes('fb'), '有 Facebook icon');
  ok(kinds.includes('ig'), '有 Instagram icon');
  ok(kinds.includes('web'), '有官網 icon');
  const external = links.filter(a => !a.href.startsWith('tel:') && !a.href.startsWith('mailto:'));
  ok(external.every(a => a.target === '_blank' && a.rel === 'noopener'), '網頁外連一律 target=_blank rel=noopener（tel／mailto 除外）');
  const fb = links.find(a => a.classList.contains('fb'));
  ok(fb && fb.href === 'https://www.facebook.com/hkscout', 'FB 連結正確：' + (fb && fb.href));
  const ig = links.find(a => a.classList.contains('ig'));
  ok(ig && ig.href === 'https://www.instagram.com/hkscouting/', 'IG 連結正確：' + (ig && ig.href));
  const web = links.find(a => a.classList.contains('web'));
  ok(web && web.href === 'https://www.scout.org.hk/', '官網連結正確：' + (web && web.href));

  // 切去收藏夾（renderContactBar 應清空 bar）
  const bmChip = [...d.querySelectorAll('#window-chips .chip')].find(c => c.textContent.includes('收藏'));
  bmChip.dispatchEvent(new dom.window.MouseEvent('click', {bubbles: true}));
  await wait(80);
  ok(bar.innerHTML === '', '收藏夾／無單一區會時 bar 清空（配合 :empty 唔佔位）');

  console.log(fail ? `\n❌ ${fail} 項失敗` : '\n🎉 全部通過');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('❌ 例外:', e.message); process.exit(1); });
