// 支部標籤配對測試：涵蓋 audience、標題 fallback 與實際 cache/enrich 整合。
//   用法： node test_search_members.js
//
// 呢個檔直接由 index.html 抽出配對邏輯（唔係複製一份），
// 咁樣 index.html 改咗邏輯呢度一定跟住測到，唔會兩邊行開。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const base = __dirname;
const html = fs.readFileSync(path.join(base, 'index.html'), 'utf8');

// 抽出由 BRANCH_TAGS 到 matchesSearchQuery 嗰段純函數（唔依賴 DOM / state）
const start = html.indexOf('const BRANCH_TAGS = [');
const end = html.indexOf('// === 各區聯絡資訊');
if (start < 0 || end < 0 || end < start) {
  console.log('❌ 揾唔到 index.html 入面嘅支部配對邏輯（BRANCH_TAGS … matchesSearchQuery）');
  process.exit(1);
}
const src = html.slice(start, end);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + `
  ;__exports = { BRANCH_TAGS, extractMemberTokens, itemBranches, matchesBranch, matchesKeyword, matchesSearchQuery, CATEGORY_TAGS, itemCategories, matchesCategory };
`, ctx);
const { BRANCH_TAGS, extractMemberTokens, itemBranches, matchesBranch, matchesKeyword, matchesSearchQuery, CATEGORY_TAGS, itemCategories, matchesCategory } = ctx.__exports;

let pass = 0;
let fail = 0;

function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? '✅' : '❌'} ${label} → ${actual} (expect ${expected})`);
  if (ok) pass += 1;
  else fail += 1;
}

function checkArray(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? '✅' : '❌'} ${label} → ${JSON.stringify(actual)} (expect ${JSON.stringify(expected)})`);
  if (ok) pass += 1;
  else fail += 1;
}

// 0. 標籤清單
checkArray('支部標籤 = 全部 + 8 個支部',
  BRANCH_TAGS.map(t => t.label),
  ['全部', '小童軍', '幼童軍', '童軍', '深資童軍', '樂行童軍', '領袖', '家長', '會務委員']);

// 1. 底層成員詞彙解析：longest-match 不得把支部名稱拆錯。
checkArray('「幼童軍」不會抽出「童軍」', extractMemberTokens('幼童軍'), ['幼童軍']);
checkArray('「深資童軍」不會抽出「童軍」', extractMemberTokens('深資童軍'), ['深資童軍']);
checkArray('混合字串仍可辨認獨立「童軍」', extractMemberTokens('幼童軍暨童軍交流日'), ['幼童軍', '童軍']);
checkArray('「成年成員」唔會拆成其他詞', extractMemberTokens('成年成員、領袖'), ['成年成員', '領袖']);

// 3. audience 精確配對（有 enrich 時以 audience 為準，標題唔理）。
const audienceCases = [
  { branch: '童軍', aud: '幼童軍、深資童軍、樂行童軍', expect: false },
  { branch: '童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { branch: '幼童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { branch: '幼童軍', aud: '童軍、領袖', expect: false },
  { branch: '領袖', aud: '深資童軍、樂行童軍', expect: false },
  { branch: '深資童軍', aud: '深資童軍、樂行童軍', expect: true },
  { branch: '會務委員', aud: '領袖、會務委員', expect: true },
  { branch: '家長', aud: '所有成員', expect: true },
  { branch: '小童軍', aud: '所有成員、領袖', expect: true },
];
for (const test of audienceCases) {
  const got = matchesBranch({ title: '（標題唔相干）' }, { audience: test.aud }, test.branch);
  check(`「${test.branch}」vs audience「${test.aud}」`, got, test.expect);
}
check('有 audience 時標題唔會加料：標題「幼童軍」但 audience「領袖」→ 幼童軍唔命中',
  matchesBranch({ title: '幼童軍領袖工作坊' }, { audience: '領袖' }, '幼童軍'), false);

// 4. 冇 audience → 標題 fallback（同樣 longest-match）。
check('標題模式：童軍不命中幼童軍', matchesBranch({ title: '幼童軍訓練班' }, null, '童軍'), false);
check('標題模式：童軍可命中獨立童軍', matchesBranch({ title: '童軍技能訓練班' }, null, '童軍'), true);
check('標題模式：「香港童軍115周年 幼童軍度假營」命中幼童軍', matchesBranch({ title: '香港童軍115周年–幼童軍度假營2026' }, null, '幼童軍'), true);
check('標題模式：標題冇任何支部詞 → 唔命中', matchesBranch({ title: '旅團註冊須知' }, null, '童軍'), false);
check('標題模式：空 audience 字串當冇 audience', matchesBranch({ title: '深資童軍海上旅程' }, { audience: '' }, '深資童軍'), true);
check('「全部」永遠命中', matchesBranch({ title: '乜都冇' }, null, 'ALL'), true);

// 5. 關鍵字：只搜名稱（包含配對），支部由標籤負責。
check('關鍵字包含配對', matchesKeyword({ title: '深資童軍射箭訓練班' }, '射箭'), true);
check('關鍵字唔會搜區會名', matchesKeyword({ title: '射箭訓練班', source_site: '筲箕灣區' }, '筲箕灣'), false);
check('關鍵字 NFKC：全形數字都搵到', matchesKeyword({ title: '第４１屆訓練班' }, '41'), true);
check('關鍵字 + 支部 同時生效', matchesSearchQuery({ title: '深資童軍射箭訓練班' }, { audience: '深資童軍' }, '射箭', '深資童軍'), true);
check('關鍵字中但支部唔中 → 唔顯示', matchesSearchQuery({ title: '深資童軍射箭訓練班' }, { audience: '深資童軍' }, '射箭', '幼童軍'), false);

// 5.5 分類：訓練班 / 服務 / 比賽。
checkArray('分類標籤 = 全部 + 訓練班/服務/比賽/其他',
  CATEGORY_TAGS.map(t => t.label),
  ['全部', '訓練班', '服務', '比賽', '其他']);
check('分類：標題有「訓練班」→ training', matchesCategory({ title: '童軍繩結訓練班' }, null, 'training'), true);
check('分類：標題有「服務」→ service', matchesCategory({ title: '社區服務日' }, null, 'service'), true);
check('分類：標題有「比賽」→ competition', matchesCategory({ title: '射箭邀請賽' }, null, 'competition'), true);
check('分類：可以同時屬於訓練 + 服務', matchesCategory({ title: '敬老關愛服務暨手工工作坊' }, null, 'training') && matchesCategory({ title: '敬老關愛服務暨手工工作坊' }, null, 'service'), true);
check('分類：富 enrich title 都計（cache 標題較短）',
  matchesCategory({ title: '活動' }, { title: '心靈工作坊' }, 'training'), true);
check('分類：行事曆唔會因為有「訓練」而變訓練班', matchesCategory({ title: '活動與訓練行事曆' }, null, 'training'), false);
check('分類：冇關鍵字 → other', matchesCategory({ title: '旅團註冊須知' }, null, 'other'), true);
check('分類：ALL 永遠命中', matchesCategory({ title: '乜都冇' }, null, 'ALL'), true);

// 6. 使用 repo 真實資料作回歸測試：所有「童軍」結果都必須有精確 token（audience 或標題）。
const cache = JSON.parse(fs.readFileSync(path.join(base, 'cache.json'), 'utf8'));
const enrichMap = JSON.parse(fs.readFileSync(path.join(base, 'enrich.json'), 'utf8'));
const items = Object.values(cache.data || {}).flat();
const realMatches = items.filter(item => {
  const enrich = enrichMap[item.pdf_url] || enrichMap[item.url] || null;
  return matchesBranch(item, enrich, '童軍');
});
const invalidRealMatches = realMatches.filter(item => {
  const enrich = enrichMap[item.pdf_url] || enrichMap[item.url] || null;
  const tokens = enrich?.audience
    ? extractMemberTokens(enrich.audience)
    : extractMemberTokens(item.title || '');
  return !(tokens.includes('童軍') || tokens.includes('所有成員'));
});
check('真實資料中「童軍」標籤有結果', realMatches.length > 0, true);
check('真實資料中沒有非童軍 audience 混入', invalidRealMatches.length, 0);
const byTitleOnly = realMatches.filter(item => !(enrichMap[item.pdf_url] || enrichMap[item.url])?.audience);

console.log(`\n${pass}/${pass + fail} 通過；真實資料「童軍」命中 ${realMatches.length} 筆（其中 ${byTitleOnly.length} 筆靠標題）`);
process.exit(fail ? 1 : 0);
