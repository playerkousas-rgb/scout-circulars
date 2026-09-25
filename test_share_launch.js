// node test_share_launch.js — app-first launcher; no installed apps required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const html = fs.readFileSync('share-launch.html', 'utf8');
const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'https://example.org/share-launch.html' });
const w = dom.window;
let count = 0;
function test(name, fn) { fn(); count++; console.log('✅ ' + name); }
function params(target, text = '【區會】中文 & # + ?\n詳情：https://example.org/a.pdf', url = 'https://example.org/a.pdf?a=1&b=2') {
  return '#' + new URLSearchParams({ target, text, url });
}
function envFor({ focus = true, hidden = false, throws = false } = {}) {
  const events = new Map(), docEvents = new Map(), timers = new Map(), calls = [];
  let next = 0;
  const listen = (map) => ({
    addEventListener(type, fn) { if (!map.has(type)) map.set(type, new Set()); map.get(type).add(fn); },
    removeEventListener(type, fn) { map.get(type)?.delete(fn); },
  });
  const env = {
    ...listen(events), focus,
    document: { ...listen(docEvents), hidden, hasFocus: () => env.focus },
    location: {
      assign(url) { calls.push(['app', url]); if (throws) throw Error('protocol blocked'); },
      replace(url) { calls.push(['web', url]); },
    },
    setTimeout(fn, ms) { assert.equal(ms, 2500); timers.set(++next, fn); return next; },
    clearTimeout(id) { timers.delete(id); },
  };
  function emit(map, name) { for (const fn of [...(map.get(name) || [])]) fn(); }
  return {
    env, calls, timers,
    fire: (name) => emit(events, name), docFire: (name) => emit(docEvents, name),
    tick() { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } },
    listeners() { return [...events.values(), ...docEvents.values()].reduce((n, set) => n + set.size, 0); },
  };
}
const text = '中文 & # + ?\n---經 通告圖書館';
const wa = w.desktopShareDestinations(params('wa', text));
const tg = w.desktopShareDestinations(params('tg', text));
test('WhatsApp app 及網頁都完整保留文案', () => {
  assert.equal(new URL(wa.app).protocol, 'whatsapp:');
  assert.equal(new URL(wa.web).origin, 'https://web.whatsapp.com');
  assert.equal(new URL(wa.app).searchParams.get('text'), text);
  assert.equal(new URL(wa.web).searchParams.get('text'), text);
});
test('Telegram Web A tgaddr 同 app deep link 一致、文案及 URL 無重複編碼', () => {
  assert.equal(new URL(tg.app).protocol, 'tg:');
  assert.equal(new URL(tg.app).searchParams.get('text'), text);
  assert.equal(new URL(tg.app).searchParams.get('url'), 'https://example.org/a.pdf?a=1&b=2');
  assert.equal(new URL(tg.web).origin, 'https://web.telegram.org');
  assert.equal(new URLSearchParams(new URL(tg.web).hash.slice(2)).get('tgaddr'), tg.app);
});
for (const invalid of ['', '#target=evil&text=x', params('wa', ''), params('tg', 'x'.repeat(20001))]) {
  test('拒絕無效／過長資料：' + invalid.slice(0, 40), () => assert.equal(w.desktopShareDestinations(invalid), null));
}
// 圖片分享（mode=image）：唔帶任何文字，只開平台本身。張圖已經有齊內文，
// 再加預填文案好奇怪（2026-09-25 用戶要求）。
const waImg = w.desktopShareDestinations('#target=wa&mode=image');
const tgImg = w.desktopShareDestinations('#target=tg&mode=image');
test('圖片模式：WhatsApp／Telegram 開返平台本身，冇任何預填文字', () => {
  assert.equal(waImg.app, 'whatsapp://');
  assert.equal(waImg.web, 'https://web.whatsapp.com/');
  assert.equal(tgImg.app, 'tg://');
  assert.equal(tgImg.web, 'https://web.telegram.org/');
  assert.ok(waImg.image && tgImg.image);
  assert.ok(!JSON.stringify([waImg, tgImg]).includes('text='));
});
for (const bad of ['#target=wa&mode=image&text=hi', '#target=tg&mode=image&url=https://x.test', '#target=fb&mode=image']) {
  test('圖片模式唔准偷加文字／唔准其他平台：' + bad.slice(0, 34), () => assert.equal(w.desktopShareDestinations(bad), null));
}
test('唔接受任意 redirect／app URL', () => {
  const dest = w.desktopShareDestinations(params('wa', '<script>alert(1)</script>') + '&web=https://evil.org&app=javascript:alert(1)');
  assert.equal(new URL(dest.web).hostname, 'web.whatsapp.com');
  assert.equal(new URL(dest.app).protocol, 'whatsapp:');
});
test('無效資料有提示、唔會自動跳轉', () => {
  assert.match(w.document.getElementById('status').textContent, /資料唔完整/);
  assert.equal(w.document.getElementById('actions').hidden, true);
});
for (const dest of [wa, tg]) {
  test(dest.label + '：先 app；無反應 2.5 秒後同一分頁退網頁，清理 listeners', () => {
    const e = envFor(); const status = {};
    w.createDesktopShareLauncher(dest, e.env, status);
    assert.deepEqual(e.calls, [['app', dest.app]]);
    e.tick(); e.tick();
    assert.deepEqual(e.calls, [['app', dest.app], ['web', dest.web]]);
    assert.equal(e.listeners(), 0);
  });
  test(dest.label + '：protocol 拋錯仍會退網頁', () => {
    const e = envFor({ throws: true });
    w.createDesktopShareLauncher(dest, e.env, {}); e.tick();
    assert.equal(e.calls[1][1], dest.web);
  });
}
for (const event of ['blur', 'visibilitychange', 'pagehide']) {
  test(event + ' 取消自動跳轉，回來唔會再彈網頁', () => {
    const e = envFor(); w.createDesktopShareLauncher(wa, e.env, {});
    if (event === 'visibilitychange') { e.env.document.hidden = true; e.docFire(event); }
    else e.fire(event);
    e.env.document.hidden = false; e.env.focus = true; e.fire('focus'); e.tick();
    assert.deepEqual(e.calls, [['app', wa.app]]);
    assert.equal(e.timers.size, 0); assert.equal(e.listeners(), 0);
  });
}
test('背景開頁唔會自動退網頁；獲焦點先試 app', () => {
  const e = envFor({ focus: false, hidden: true });
  w.createDesktopShareLauncher(tg, e.env, {}); e.tick();
  assert.equal(e.calls.length, 0);
  e.env.focus = true; e.env.document.hidden = false; e.fire('focus');
  assert.deepEqual(e.calls, [['app', tg.app]]);
  e.fire('focus'); assert.equal(e.calls.length, 1);
});
test('timer 執行時再次檢查焦點，唔搶返 app 畫面', () => {
  const e = envFor(); w.createDesktopShareLauncher(wa, e.env, {});
  e.env.focus = false; e.tick(); assert.equal(e.calls.length, 1);
});
test('手動轉網頁／重試前可以取消舊 timer', () => {
  const e = envFor(); const stop = w.createDesktopShareLauncher(wa, e.env, {});
  stop(); e.tick(); assert.equal(e.calls.length, 1);
  w.createDesktopShareLauncher(wa, e.env, {}); e.tick();
  assert.deepEqual(e.calls, [['app', wa.app], ['app', wa.app], ['web', wa.web]]);
});
test('launcher 唔會覆寫圖片剪貼板、冇 opener 依賴', () => {
  assert.ok(!html.includes('clipboard.write')); assert.ok(!html.includes('window.opener'));
});
dom.window.close();
console.log(`\n${count} tests passed`);
