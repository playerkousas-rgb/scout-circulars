// 出圖台（?batch=1）分類測試：直接由 index.html 抽出 BATCH_RE + batchCategory，
// 唔會兩邊行開；唔需要 jsdom（同 test_search_members.js 一樣用 vm 抽源碼）。
//   用法： node test_batch_category.js
//
// 2026-10-03：新增用戶規則——標題有「公告／公布／公佈」＝公布（明確字眼以標題
// 為準）；「成績公布／結果公布」係賽果＝比賽。呢個測試釘住 index.html 同
// story_queue.py／subscription_tagging.py 嘅優先序一致。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

const start = html.indexOf('const BATCH_TOOLS_SOURCES');
const end = html.indexOf('const BATCH_NO_DATE');
if (start < 0 || end < 0 || end < start) {
  console.log('❌ 揾唔到 index.html 入面嘅出圖台分類邏輯（BATCH_TOOLS_SOURCES … batchCategory）');
  process.exit(1);
}

const ctx = {};
vm.createContext(ctx);
vm.runInContext(
  html.slice(start, end) + '\n;__exports = { BATCH_RE, batchCategory };\n',
  ctx,
);
const { batchCategory } = ctx.__exports;

let pass = 0;
let fail = 0;
function ok(cond, label) {
  if (cond) {
    pass += 1;
    console.log(`✅ ${label}`);
  } else {
    fail += 1;
    console.log(`❌ ${label}`);
  }
}

// 有 enrich categories 時以 enrich 為準（同 app 其他地方一致）
ok(batchCategory({ title: '乜字都冇', source_site: 'x' }, { categories: [{ id: 'announcement' }] }) === 'announcement',
  'enrich 已判定公布 → announcement');
ok(batchCategory({ title: '總部公告', source_site: 'Scout System' }, null) === 'tools',
  'Scout System 來源永遠係小工具');

// 標題兜底（冇 enrich）
const cases = [
  ['總部公告', 'announcement'],
  ['D-26-05 - 26年10月區會公布 【New】', 'announcement'],
  ['地域總部公佈(2026年9月)', 'announcement'],
  ['2026年新界地域領袖嘉許計劃 - 獲獎名單公布', 'announcement'],
  ['香港童軍115周年—新界地域步操及升旗比賽2026 - 成績公布', 'competition'],
  ['成績公佈', 'competition'],
  ['某某錦標賽通告', 'competition'],
  ['義工服務日', 'service'],
  ['飛鏢同樂日', 'activity'],
  ['領袖訓練工作坊', 'training'],
  ['隨意標題', 'other'],
];
for (const [title, want] of cases) {
  const got = batchCategory({ title, source_site: 'x' }, null);
  ok(got === want, `「${title}」→ ${want}（實際 ${got}）`);
}

console.log(`\n結果：${pass}/${pass + fail} 通過`);
process.exit(fail === 0 ? 0 : 1);
