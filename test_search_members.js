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
  ;__exports = { BRANCH_TAGS, extractMemberTokens, itemBranches, matchesBranch, matchesKeyword, matchesSearchQuery, CATEGORY_TAGS, itemCategories, matchesCategory, itemScoutKind, isScoutSystemItem, SCOUT_SYSTEM_KINDS, expandBranchScopeByAge };
`, ctx);
const { BRANCH_TAGS, extractMemberTokens, itemBranches, matchesBranch, matchesKeyword, matchesSearchQuery, CATEGORY_TAGS, itemCategories, matchesCategory, itemScoutKind, isScoutSystemItem, SCOUT_SYSTEM_KINDS, expandBranchScopeByAge } = ctx.__exports;

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

// 5.5 分類：由 enrich.py 抽出嚟嘅 categories 決定，唔係靠標題字眼。
// 個人化 taxonomy 固定為訓練／服務／活動／比賽；舊 competition 資料映射到獨立比賽。
checkArray('分類標籤 = 全部 + 訓練/服務/活動/比賽/小工具/公布/未分類',
  CATEGORY_TAGS.map(t => t.label),
  ['全部', '訓練', '服務', '活動', '比賽', '小工具', '公布', '未分類']);
checkArray('Scout System 內設分類',
  SCOUT_SYSTEM_KINDS.map(k => k.label),
  ['助手', '遊戲', '系統', '工具', '其他', '連結']);
check('站方標籤「遊戲」歸遊戲', itemScoutKind({ source_site: 'Scout System', title: '密碼旗號', tags: ['幼童軍', '遊戲'] }), 'game');
check('標題【助手】歸助手', itemScoutKind({ source_site: 'Scout System', title: '【助手】集會流程' }), 'assistant');
check('冇標籤又冇關鍵詞歸其他', itemScoutKind({ source_site: 'Scout System', title: '密碼旗號' }), 'other');
check('「小工具」唔會被當成內設工具', itemScoutKind({ source_site: 'Scout System', title: '繩結小工具' }), 'other');
check('通告唔會被標成 Scout System 分類', itemScoutKind({ source_site: '筲箕灣區', title: '【遊戲】通告' }), '');
check('Scout System 先算小工具來源', isScoutSystemItem({ source_site: 'Scout System', title: 'x' }), true);
check('分類：enrich categories 有训练 → training',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'training', label: '訓練班' }] }, 'training'), true);
check('分類：enrich categories 有服务 → service',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'service', label: '服務' }] }, 'service'), true);
check('分類：歷史 direct competition categories 映射為獨立 competition',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'competition', label: '比賽' }] }, 'competition'), true);
check('分類：舊 activity:competition 也映射為獨立 competition',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'activity', subtype: 'competition', label: '活動' }] }, 'competition'), true);
check('分類：比賽不會混入活動',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'competition', label: '比賽' }] }, 'activity'), false);
check('分類：新活動 categories → activity',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'activity', subtype: 'campfire', label: '活動' }] }, 'activity'), true);
check('分類：一隻通告可以同時屬訓練 + 服務',
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'training' }, { id: 'service' }] }, 'training') &&
  matchesCategory({ title: '標題無關鍵詞' }, { categories: [{ id: 'training' }, { id: 'service' }] }, 'service'), true);
check('分類：標題有「訓練班」但 enrich 未分類 → 唔會靠標題誤判',
  matchesCategory({ title: '童軍繩結訓練班' }, null, 'training'), false);
// 2026-10-01：新增「公布」做行政類兜底，所以冇 categories 嘅通告由「未分類」改歸「公布」。
check('分類：enrich 冇 categories → announcement', matchesCategory({ title: '旅團註冊須知' }, {}, 'announcement'), true);
check('分類：enrich 冇 categories 唔再當未分類', matchesCategory({ title: '旅團註冊須知' }, {}, 'other'), false);
check('分類：ALL 永遠命中', matchesCategory({ title: '乜都冇' }, null, 'ALL'), true);

// 5b. 2026-11-04 用戶規則：歲數／「XX支部或以上」展開（前端同 Python 同步）。
function branchList(item, enrich) {
  return [...itemBranches(item, enrich)].sort().join('、');
}
check('15歲以上之童軍成員 → 童軍＋深資童軍＋樂行童軍',
  branchList({ title: '活動通告' }, { audience: '15歲以上之童軍成員' }),
  ['樂行童軍', '深資童軍', '童軍'].sort().join('、'));
check('18歲以上之童軍成員 → 深資童軍＋樂行童軍（裸「童軍」要清走）',
  branchList({ title: '活動通告' }, { audience: '18歲或以上之童軍成員' }),
  ['樂行童軍', '深資童軍'].sort().join('、'));
check('11至26歲明列支部 → 跟通告列出嘅三個支部',
  branchList({ title: '獎項公布' }, { audience: '11至26歲的童軍、深資童軍或樂行童軍支部成員' }),
  ['樂行童軍', '深資童軍', '童軍'].sort().join('、'));
check('童軍支部或以上 → 童軍＋深資童軍＋樂行童軍',
  branchList({ title: '活動通告' }, { audience: '童軍支部或以上成員' }),
  ['樂行童軍', '深資童軍', '童軍'].sort().join('、'));
check('幼童軍支部或以上 → 幼童軍以上嘅青年支部，唔包領袖',
  branchList({ title: '活動1 課程及嘉年華 報名表 幼童軍或以上' }, null),
  ['幼童軍', '樂行童軍', '深資童軍', '童軍'].sort().join('、'));
check('18歲以下家長同意書唔會變成深資／樂行推播',
  ['深資童軍', '樂行童軍'].some(b => itemBranches(
    { title: '童軍訓練班' },
    { audience: '童軍、領袖。18歲以下之參加者必須簽署家長同意書' }
  ).has(b)), false);
check('「或以上」展開後童軍篩選會命中幼童軍或以上通告',
  matchesBranch({ title: '活動1 課程及嘉年華 報名表 幼童軍或以上' }, null, '童軍'), true);

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
  const source = enrich?.audience || item.title || '';
  const tokens = extractMemberTokens(source);
  // 2026-11-04：「XX支部或以上／XX歲以上」展開出嚟嘅童軍一樣係有效命中，
  // 唔係舊版嗰種「童軍」食咗「幼童軍」嘅假陽性。
  const implied = expandBranchScopeByAge(source).implied;
  return !(tokens.includes('童軍') || tokens.includes('所有成員') || implied.has('童軍'));
});
check('真實資料中「童軍」標籤有結果', realMatches.length > 0, true);
check('真實資料中沒有非童軍 audience 混入', invalidRealMatches.length, 0);
const byTitleOnly = realMatches.filter(item => !(enrichMap[item.pdf_url] || enrichMap[item.url])?.audience);

// 2026-11-06 用戶規則：用戶點名、每年同名嘅通告，標籤永遠係公布（標題先決）。
function checkCats(label, item, ex, expected) {
  const got = [...itemCategories(item, ex)];
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  console.log(`${ok ? '✅' : '❌'} ${label} → ${JSON.stringify(got)} (expect ${JSON.stringify(expected)})`);
  if (ok) pass += 1;
  else fail += 1;
}
checkCats('「學生隊員制服資助計劃」存檔係訓練 → 照顯示公布',
  { title: '學生隊員制服資助計劃', source_site: '總會' },
  { categories: [{ id: 'training', label: '訓練', evidence: ['課程'] }] },
  ['announcement']);
checkCats('「學生隊員制服資助計劃申請表」→ 公布',
  { title: '學生隊員制服資助計劃申請表', source_site: '港島西區' },
  null,
  ['announcement']);
checkCats('「幼童軍度假營2026資助計劃」唔受影響（照 enrich 分類）',
  { title: '香港童軍115周年 幼童軍度假營2026資助計劃', source_site: '沙田南區' },
  { categories: [{ id: 'activity', label: '活動' }] },
  ['activity']);

console.log(`\n${pass}/${pass + fail} 通過；真實資料「童軍」命中 ${realMatches.length} 筆（其中 ${byTitleOnly.length} 筆靠標題）`);
process.exit(fail ? 1 : 0);
