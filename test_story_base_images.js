// index.html AI 底圖（story-bases/*.webp）接入測試
//   用法： npm i jsdom && node test_story_base_images.js
//
// 重點驗證：
//   1. BASE_IMAGE_FOR 嘅 key 同 POSTER_DESIGN_BY_ID 嘅 id 一一對應（唔會因為串錯字而靜靜失效）
//   2. renderPoster 有真底圖（o.baseImg）時，drawImage 一定係第一個落畫嘅動作
//      （底圖必須喺最底層，唔可以蓋住後加文字 —— 用戶明確要求）
//   3. renderPoster 冇底圖（o.baseImg 為 null／未解碼完）時，照舊行返向量 kind(...) 畫法，
//      唔會因為新程式碼而整壞冇底圖嗰條路
//   4. storyBaseNeedsPlate／storyBaseSoftPlate 唔會因為 ctx 冇真實圖片量度而擲錯
//   5. resolvePosterDesignId 抽出嚟之後，同原本 posterAutoDesignId/opts.design 邏輯一致
const { JSDOM } = require('jsdom');
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');

let fail = 0;
const ok = (c, m) => { console.log((c ? '✅ ' : '❌ ') + m); if (!c) fail++; };

function boot() {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.org/',
    pretendToBeVisual: true,
    beforeParse(win) {
      win.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ last_updated: new Date().toISOString(), data: {} }) });
      win.alert = () => {}; win.confirm = () => true;
      const fakeGradient = { addColorStop() {} };
      win.HTMLCanvasElement.prototype.getContext = function () {
        return {
          measureText: (t) => ({ width: String(t).length * 18 }),
          fillRect() {}, strokeRect() {}, fillText() {}, beginPath() {}, closePath() {},
          moveTo() {}, lineTo() {}, arc() {}, arcTo() {}, save() {}, restore() {},
          translate() {}, rotate() {}, scale() {}, stroke() {}, fill() {}, rect() {}, clip() {},
          drawImage() {}, getImageData: () => ({ data: new Uint8ClampedArray(4) }),
          putImageData() {}, createPattern: () => null,
          set filter(_v) {}, get filter() { return 'none'; },
          createLinearGradient: () => fakeGradient, createRadialGradient: () => fakeGradient,
        };
      };
      win.HTMLCanvasElement.prototype.toBlob = function (cb) { cb(new win.Blob(['png'], { type: 'image/png' })); };
      win.HTMLCanvasElement.prototype.toDataURL = function () { return 'data:image/png;base64,AA=='; };
    },
  });
  return dom;
}

(async () => {
  const dom = boot();
  const w = dom.window;
  await new Promise((r) => setTimeout(r, 300));

  // ── 1. BASE_IMAGE_FOR 嘅 key 一定要係真實存在嘅 design id ──
  const designIds = new Set(w.eval('POSTER_DESIGNS').map((d) => d.id));
  const baseMap = w.eval('BASE_IMAGE_FOR');
  const baseKeys = Object.keys(baseMap);
  ok(baseKeys.length > 0, 'BASE_IMAGE_FOR 有登記底圖');
  ok(baseKeys.every((k) => designIds.has(k)), 'BASE_IMAGE_FOR 全部 key 都係真實存在嘅 POSTER_DESIGNS id：' + baseKeys.filter((k) => !designIds.has(k)).join(','));
  const expectedIds = ['train_blue', 'train_orange', 'train_green', 'competition_gold_black', 'activity_army', 'service_wanted', 'unc_wanted_parchment', 'unc_scope', 'unc_topsecret', 'unc_glitch'];
  ok(expectedIds.every((id) => designIds.has(id)), '9 款底圖對應嘅 10 個 design id（含 unc_wanted_parchment 共用 service_wanted）全部喺 POSTER_DESIGNS 入面：' + expectedIds.filter((id) => !designIds.has(id)).join(','));

  // ── 2. 有真底圖時，drawImage 一定行先，fillText／fillRect 等文字相關動作喺之後 ──
  {
    const calls = [];
    const proto = w.HTMLCanvasElement.prototype;
    const origGet = proto.getContext;
    proto.getContext = function () {
      const c = origGet.apply(this, arguments);
      const wrap = (name) => { const orig = c[name].bind(c); c[name] = (...a) => { calls.push(name); return orig(...a); }; };
      ['drawImage', 'fillText', 'fillRect', 'fill'].forEach(wrap);
      return c;
    };
    const fakeImg = { width: 1080, height: 1920, complete: true };
    const base = { title: '底圖測試標題', pdf_url: 'https://x/base-test.pdf', url: 'https://x/base-test.pdf', source_site: '筲箕灣區', region: '港島地域', date: new Date().toISOString().slice(0, 10), category: 'training' };
    w.eval('renderPoster')(base, { mode: 'story', design: 'train_blue', baseImg: fakeImg });
    proto.getContext = origGet;
    const firstDrawImageIdx = calls.indexOf('drawImage');
    const firstTextIdx = calls.findIndex((n) => n === 'fillText' || n === 'fillRect' || n === 'fill');
    ok(firstDrawImageIdx === 0, '有底圖時，drawImage 係整個 renderPoster 入面第一個畫布動作（底圖最底層）：' + JSON.stringify(calls.slice(0, 5)));
    ok(firstTextIdx > firstDrawImageIdx, '底圖之後先至有文字／圖形疊上去（唔會蓋住底圖，亦都唔會俾底圖蓋住文字）');
  }

  // ── 3. 冇底圖（baseImg 為 null）時，照舊用返向量 kind(...) 畫法，唔叫 drawImage 畫底 ──
  {
    const calls = [];
    const proto = w.HTMLCanvasElement.prototype;
    const origGet = proto.getContext;
    proto.getContext = function () {
      const c = origGet.apply(this, arguments);
      const origDraw = c.drawImage.bind(c);
      c.drawImage = (...a) => { calls.push('drawImage'); return origDraw(...a); };
      return c;
    };
    const base = { title: '冇底圖測試', pdf_url: 'https://x/no-base-test.pdf', url: 'https://x/no-base-test.pdf', source_site: '筲箕灣區', region: '港島地域', date: new Date().toISOString().slice(0, 10), category: 'training' };
    w.eval('renderPoster')(base, { mode: 'story', design: 'train_blue', baseImg: null });
    proto.getContext = origGet;
    ok(calls.length === 0, '底圖未解碼完（baseImg=null）時唔會叫 drawImage，繼續行返向量 bg 畫法，唔會整壞冇底圖嗰條舊路');
  }

  // ── 4. storyBaseNeedsPlate／storyBaseSoftPlate 唔會擲錯 ──
  {
    const canvas = dom.window.document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const fakeImg = { width: 1080, height: 1920 };
    const zone = [0, 0, 100, 100]; // [x0, y0, x1, y1]
    let threw = false;
    try {
      const needsPlate = w.eval('storyBaseNeedsPlate')(ctx, fakeImg, zone, 'train_blue');
      w.eval('storyBaseSoftPlate')(ctx, zone, true);
      ok(typeof needsPlate === 'boolean', 'storyBaseNeedsPlate 回返 boolean：' + needsPlate);
    } catch (e) { threw = true; console.error(e); }
    ok(!threw, 'storyBaseNeedsPlate／storyBaseSoftPlate 喺冇真實像素資料（CORS / stub ctx）情況下唔會擲錯');

    // ── 4b. unc_wanted_parchment 共用 service_wanted 底圖 → 應該都要共享「需要底板」嘅判斷 ──
    const needsPlateService = w.eval('storyBaseNeedsPlate')(ctx, fakeImg, zone, 'service_wanted');
    const needsPlateAlias = w.eval('storyBaseNeedsPlate')(ctx, fakeImg, zone, 'unc_wanted_parchment');
    ok(needsPlateService === true && needsPlateAlias === true,
       'unc_wanted_parchment 借用 service_wanted 嘅底圖，兩個 design id 嘅「需要底板」判斷要一致：' + needsPlateService + ' / ' + needsPlateAlias);
  }

  // ── 6. 第 9 款底圖（unc_glitch）：有真底圖時唔准再畫 ghost headline ──
  // bug（2026-10-01 用戶報告）：unc_glitch 嘅 headline:'ghost' 係將「標題頭 12 個字」
  // 用青／洋紅色再畫一次做重影；疊喺 AI 底圖上面就變成「重覆 2 行標題」。
  // 正確行為（同 Python render_story_templates.py base 分支一致）：
  // 用底圖 → 完全唔畫 headline（ghost／WANTED／TOP SECRET）同 REWARD strip。
  {
    const recordTexts = (run) => {
      const texts = [];
      const proto = w.HTMLCanvasElement.prototype;
      const origGet = proto.getContext;
      proto.getContext = function () {
        const c = origGet.apply(this, arguments);
        const origFillText = c.fillText.bind(c);
        c.fillText = (t, ...a) => { texts.push({ text: String(t), style: String(c.fillStyle) }); return origFillText(t, ...a); };
        return c;
      };
      try { run(); } finally { proto.getContext = origGet; }
      return texts;
    };
    const title = '聯隊週年大會操暨檢閱禮2026';
    const ghost = title.replace(/\s+/g, ' ').slice(0, 12);
    const item = { title, pdf_url: 'https://x/glitch-test.pdf', url: 'https://x/glitch-test.pdf', source_site: '筲箕灣區', region: '港島地域', date: new Date().toISOString().slice(0, 10), category: 'other' };
    const fakeImg = { width: 1080, height: 1920, complete: true };

    // 6a. 有底圖：唔准有青／洋紅 ghost 重影（即係標題唔會出兩次）
    const withBase = recordTexts(() => w.eval('renderPoster')(item, { mode: 'feed', design: 'unc_glitch', baseImg: fakeImg }));
    const ghostDraws = withBase.filter((t) => t.text === ghost && (t.style.toUpperCase() === '#00FFFF' || t.style.toUpperCase() === '#FF00FF'));
    ok(ghostDraws.length === 0, 'unc_glitch＋真底圖：冇青／洋紅 ghost 重影（標題唔會重覆兩行）：' + JSON.stringify(ghostDraws));

    // 6b. 冇底圖（向量款）：ghost 重影照舊要有，唔好整壞原本設計
    const noBase = recordTexts(() => w.eval('renderPoster')(item, { mode: 'feed', design: 'unc_glitch', baseImg: null }));
    const vectorGhost = noBase.filter((t) => t.text === ghost && (t.style.toUpperCase() === '#00FFFF' || t.style.toUpperCase() === '#FF00FF'));
    ok(vectorGhost.length === 2, 'unc_glitch 向量款（冇底圖）：ghost 重影照舊畫兩層（青＋洋紅）：' + vectorGhost.length);

    // 6c. 其他有 headline 嘅款（service_wanted / unc_topsecret）用底圖時都唔准再畫大字
    for (const [id, word] of [['service_wanted', 'WANTED'], ['unc_topsecret', 'TOP SECRET'], ['unc_wanted_parchment', 'WANTED']]) {
      const texts = recordTexts(() => w.eval('renderPoster')(Object.assign({}, item, { category: id === 'service_wanted' ? 'service' : 'other' }), { mode: 'feed', design: id, baseImg: fakeImg }));
      const headlineDraws = texts.filter((t) => t.text === word);
      ok(headlineDraws.length === 0, id + '＋真底圖：唔會再疊 ' + word + ' 大字（底圖本身已有風格）');
    }
  }

  // ── 5. resolvePosterDesignId 抽出嚟之後，同 opts.design／posterAutoDesignId 行為一致 ──
  {
    const item = { pdf_url: 'https://x/1.pdf' };
    const exTraining = { categories: [{ id: 'training' }] };
    const viaOpts = w.eval('resolvePosterDesignId')(item, exTraining, { design: 'competition_gold_black' });
    const viaAuto = w.eval('resolvePosterDesignId')(item, exTraining, {});
    const directAuto = w.eval('posterAutoDesignId')(item, exTraining);
    ok(viaOpts === 'competition_gold_black', 'resolvePosterDesignId 尊重 opts.design：' + viaOpts);
    ok(viaAuto === directAuto, 'resolvePosterDesignId 冇指定 design 時同 posterAutoDesignId 一致：' + viaAuto + ' === ' + directAuto);
  }

  console.log(fail === 0 ? '\n🎉 全部通過' : `\n❌ ${fail} 項失敗`);
  process.exit(fail === 0 ? 0 : 1);
})();
