// Current date-only "今天" semantics; no network, DOM or clock dependence.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('index.html', 'utf8');
function declaration(name) {
  const match = html.match(new RegExp(`    function ${name}\\([^]*?\\n    }`));
  assert(match, `${name} must exist in index.html`);
  return match[0];
}
let now = '2026-09-08T18:00:00+08:00';
let days = 1;
class TestDate extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
}
const context = vm.createContext({ Date: TestDate, currentWindow: () => ({ days }) });
vm.runInContext(declaration('parseDate') + '\n' + declaration('inWindow'), context);
assert.strictEqual(context.parseDate('2026-09-08').toISOString(), '2026-09-07T16:00:00.000Z', 'capture date starts at Hong Kong midnight');
assert(context.inWindow('2026-09-08'), 'new evening entry is visible that evening');
now = '2026-09-08T23:59:59+08:00';
assert(context.inWindow('2026-09-08'));
now = '2026-09-09T00:00:00.000+08:00';
assert(context.inWindow('2026-09-08'), 'existing <= comparison includes the exact boundary');
now = '2026-09-09T00:00:00.001+08:00';
assert(!context.inWindow('2026-09-08'), 'leaves 今天 after midnight, not 24 hours after evening capture');
now = '2026-09-09T18:00:00+08:00';
assert(!context.inWindow('2026-09-08'));
days = 7;
assert(context.inWindow('2026-09-08'), 'still available under 7天, not deleted');

// 6個月視窗：只有 Scout System 會包含 6 個月以上；通告唔會。
const archiveSrc = declaration('isScoutSystemItem') + '\n' + declaration('itemInWindow');
let archiveDays = 180;
let archiveId = '180d';
const archiveCtx = vm.createContext({
  Date: TestDate,
  TOOLS_SOURCES: new Set(['Scout System']),
  currentWindow: () => ({ days: archiveDays, id: archiveId }),
  inWindow: context.inWindow,
});
vm.runInContext(archiveSrc, archiveCtx);
const oldTool = { source_site: 'Scout System', date: '2026-01-01' };
const oldNotice = { source_site: '筲箕灣區', region: '港島地域', date: '2026-01-01' };
now = '2026-09-08T12:00:00+08:00';
assert(archiveCtx.itemInWindow(oldTool), '6個月視窗包含 6 個月以上的 Scout System');
assert(!archiveCtx.itemInWindow(oldNotice), '6個月視窗唔包含 6 個月以上的通告');
archiveId = '30d';
archiveDays = 30;
assert(!archiveCtx.itemInWindow(oldTool), '較短視窗仍然隱藏舊小工具');
archiveId = '180d';
archiveDays = 180;
assert(archiveCtx.itemInWindow({ source_site: 'Scout System' }), '冇日期嘅 Scout System 都喺 6個月視窗出現');
assert(archiveCtx.isScoutSystemItem({ region: 'Scout System', source_site: '其他' }), 'region=Scout System 都算小工具');
console.log('🎉 Hong Kong date-only 今天 midnight boundary and 7天 retention passed');
