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
  ['東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 一個石籃的故事', 'activity'],
  ['東九50樂悠遊之與你「童」行(步行籌款活動)', 'activity'],
  ['探尋宗教足跡-參訪寶蓮禪寺(P102/2026)', 'activity'],
  // 2026-10-06 用戶規則：「香港童軍大會操」＝活動（唔係比賽）；失物認領＝公布。
  ['2026年香港童軍大會操(四)', 'activity'],
  ['香港童軍大會操荃灣區會旅遊巴士安排', 'activity'],
  ['2026年香港童軍大會操失物認領安排', 'announcement'],
  ['2026年香港童軍大會操(五) - 服務邀請', 'service'],
  ['領袖訓練工作坊', 'training'],
  ['隨意標題', 'other'],
  // 2026-10-09 用戶規則（同 subscription_tagging.py／story_queue.py 對齊）：
  // 「之行／之旅」行程＝活動；「入會／招收／招募」＝公布（更強字眼行先）；
  // 「座談會」＝訓練；「便覽」等參考文件＝公布。
  ['探索歷史典藏、清真文化與創新科技之行', 'activity'],
  ['「童」心建家園-東莞巿石龍鎮服務之旅', 'service'],           // 服務之旅仍係服務
  ['港島地域羽毛球會-入會表格', 'announcement'],
  ['港島地域羽毛球會-招收2026-2027年度下半年新會員', 'announcement'],
  ['渣打香港馬拉松2027 - 工作人員大招募(歡迎全港童軍參與)', 'service'],  // 工作人員行先
  ['香港童軍龍舟邀請賽2026 – 沙田西區龍舟隊成員招募', 'competition'],     // 賽事名行先
  ['童軍露營訓練班-學員招募', 'training'],                      // 訓練班行先
  ['港島童軍生態小組-觀鳥章(興趣組)領袖座談會', 'training'],
  ['港島地域通告便覽(2026年10月)', 'announcement'],
  // 2026-10-09 再報：「研習」裸詞涵蓋研習日／坊／班（同訂閱分類對齊）
  ['「環境保育與生態安全」— 跨支部海洋公園研習日(P105/2026)', 'training'],
  ['童軍單車研習坊 (第20/26號)', 'training'],
  ['立划板競賽研習班', 'competition'],                        // 競賽字眼行先
  // 2026-10-15 用戶點名（九龍地域＋九龍灣區）：月度摘要＝公布、出海行程＝活動。
  ['九龍地域通告【2026 年 10 月】', 'announcement'],          // 內文有「成績公佈」都搶唔走
  ['九龍地域9月份通告一覽', 'announcement'],
  ['九龍地域8月份通告一覽', 'announcement'],
  ['九灣小漁夫出海記-水上文化親子大冒險', 'activity'],
  ['維多利亞城區森林大冒險小幼童軍填色比賽', 'competition'],  // 大冒險唔會食走比賽
  ['小童軍親子堆沙工作坊及BBQ', 'training'],                  // 「親子」刻意唔收
];
for (const [title, want] of cases) {
  const got = batchCategory({ title, source_site: 'x' }, null);
  ok(got === want, `「${title}」→ ${want}（實際 ${got}）`);
}

console.log(`\n結果：${pass}/${pass + fail} 通過`);
process.exit(fail === 0 ? 0 : 1);
