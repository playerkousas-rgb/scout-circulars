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
vm.runInContext(declaration('parseDate') + '\n' + declaration('withinDays') + '\n' + declaration('inWindow'), context);
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

// ── 2026-10-01：小工具（Scout System）取消以日期分類 ──────────────
// 小工具分頁只剩「今天」同「之前發布」（＝全部）；其他分頁（全港／地域／
// 區會）小工具照跟通告視窗，唔會一撳「今天」就成版舊工具跳出嚟。
const toolsSrc = [
  declaration('isScoutSystemItem'),
  declaration('currentToolsWindow'),
  declaration('withinDays'),
  declaration('inWindow'),
  declaration('toolInToolsWindow'),
  declaration('itemInWindow'),
].join('\n');
let noticeDays = 1;
let toolsWindowId = 'tools-all';
let inToolsTab = true;
const toolsCtx = vm.createContext({
  Date: TestDate,
  TOOLS_SOURCES: new Set(['Scout System']),
  TOOLS_TIME_WINDOWS: [
    { id: 'tools-today', label: '今天', days: 1 },
    { id: 'tools-all', label: '之前發布', days: null },
  ],
  state: { get toolsWindowId() { return toolsWindowId; } },
  currentWindow: () => ({ days: noticeDays }),
  viewingScoutSystem: () => inToolsTab,
  parseDate: context.parseDate,
});
vm.runInContext(toolsSrc, toolsCtx);
const oldTool = { source_site: 'Scout System', date: '2026-01-01' };
const todayTool = { source_site: 'Scout System', date: '2026-09-08' };
const undatedTool = { source_site: 'Scout System' };
const oldNotice = { source_site: '筲箕灣區', region: '港島地域', date: '2026-01-01' };
const recentNotice = { source_site: '筲箕灣區', region: '港島地域', date: '2026-07-01' };
const todayNotice = { source_site: '筲箕灣區', region: '港島地域', date: '2026-09-08' };
now = '2026-09-08T12:00:00+08:00';

// 小工具分頁 ×「之前發布」＝全部，連 6 個月以上同冇日期嘅工具都留低。
assert(toolsCtx.itemInWindow(oldTool), '之前發布：舊小工具照出');
assert(toolsCtx.itemInWindow(todayTool), '之前發布：今日上架嘅小工具都包');
assert(toolsCtx.itemInWindow(undatedTool), '冇日期嘅小工具一樣出');
assert(toolsCtx.isScoutSystemItem({ region: 'Scout System', source_site: '其他' }), 'region=Scout System 都算小工具');
assert(toolsCtx.itemInWindow({ region: 'Scout System', source_site: '其他', date: '2026-01-01' }), 'region=Scout System 嘅舊工具都行小工具視窗');
assert(toolsCtx.itemInWindow(todayNotice), '通告仍然行通告視窗（今天）');
assert(!toolsCtx.itemInWindow(oldNotice), '通告唔會因為小工具視窗而變成全部');

// 通告視窗點改都唔影響小工具分頁 —— 兩套視窗已經脫鈎。
noticeDays = 180;
assert(toolsCtx.itemInWindow(oldTool), '通告視窗點揀都唔影響小工具分頁');
assert(toolsCtx.itemInWindow(recentNotice), '6個月視窗包含半年內嘅通告');
assert(!toolsCtx.itemInWindow(oldNotice), '6個月視窗唔包含 6 個月以上嘅通告（舊嘅小工具例外已取消）');
noticeDays = 1;

// 小工具分頁 ×「今天」＝只有今日發布嘅小工具。
toolsWindowId = 'tools-today';
assert(!toolsCtx.itemInWindow(oldTool), '今天：舊小工具唔出');
assert(toolsCtx.itemInWindow(todayTool), '今天：今日上架嘅小工具出');
assert(!toolsCtx.itemInWindow(undatedTool), '今天：冇日期嘅小工具唔當今日');

// 未知 id 兜底落「之前發布」，唔會一下清空成個小工具分頁。
toolsWindowId = 'gibberish';
assert(toolsCtx.itemInWindow(oldTool), '壞 toolsWindowId 兜底做之前發布');

// 唔喺小工具分頁（例如全港／地域）：小工具跟返通告視窗。
inToolsTab = false;
toolsWindowId = 'tools-all';
assert(!toolsCtx.itemInWindow(oldTool), '全港「今天」唔會突然出晒啲舊工具');
assert(toolsCtx.itemInWindow(todayTool), '全港「今天」仍然見到今日新上架嘅工具');
// 側欄數字唔理你喺邊個分頁，永遠報小工具視窗嘅真實件數。
assert(toolsCtx.toolInToolsWindow(oldTool), '側欄數字用小工具視窗，唔跟通告視窗');
assert(toolsCtx.toolInToolsWindow(undatedTool), '冇日期嘅工具都計入側欄數字');
toolsWindowId = 'tools-today';
assert(!toolsCtx.toolInToolsWindow(oldTool), '小工具揀咗「今天」，側欄數字跟住收窄');

console.log('🎉 Hong Kong date-only 今天 midnight boundary, 7天 retention and dateless 小工具 windows passed');
