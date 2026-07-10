// 成員搜尋精確配對測試：涵蓋 audience、標題與實際 cache/enrich 整合。
const fs = require('fs');
const path = require('path');

const KNOWN_MEMBERS = [
  '小童軍', '幼童軍', '童軍', '深資童軍', '樂行童軍',
  '領袖', '家長', '成年成員', '會務委員', '公眾', '親友', '所有成員',
];
const MEMBER_QUERY_SEPARATOR = /[\s,，、/／;；|｜]+/;

function normalizeSearchText(value) {
  return String(value ?? '').normalize('NFKC').toLowerCase().trim();
}

const NORMALIZED_MEMBERS_LONGEST_FIRST = KNOWN_MEMBERS
  .map(normalizeSearchText)
  .sort((a, b) => b.length - a.length);

function splitSearchParts(query) {
  return normalizeSearchText(query).split(MEMBER_QUERY_SEPARATOR).filter(Boolean);
}

function tokenizeMemberQuery(query) {
  const known = new Set(NORMALIZED_MEMBERS_LONGEST_FIRST);
  return [...new Set(splitSearchParts(query).filter(part => known.has(part)))];
}

function isMemberOnlyQuery(query) {
  const parts = splitSearchParts(query);
  const known = new Set(NORMALIZED_MEMBERS_LONGEST_FIRST);
  return parts.length > 0 && parts.every(part => known.has(part));
}

function extractMemberTokens(text) {
  const value = normalizeSearchText(text);
  const tokens = [];
  let index = 0;
  while (index < value.length) {
    const matched = NORMALIZED_MEMBERS_LONGEST_FIRST.find(member => value.startsWith(member, index));
    if (matched) {
      tokens.push(matched);
      index += matched.length;
    } else {
      index += 1;
    }
  }
  return [...new Set(tokens)];
}

function exactMemberTextMatches(queryTokens, text) {
  if (!text || !queryTokens.length) return false;
  const textTokens = extractMemberTokens(text);
  return queryTokens.some(token => textTokens.includes(token));
}

function audienceMatches(queryTokens, audience) {
  return exactMemberTextMatches(queryTokens, audience);
}

function matchesSearchQuery(item, enrich, query, searchFields) {
  const q = normalizeSearchText(query);
  if (!q) return true;

  const memberTokens = tokenizeMemberQuery(q);
  const memberOnly = isMemberOnlyQuery(q);

  if (memberOnly && searchFields.member) {
    return audienceMatches(memberTokens, enrich?.audience || '');
  }

  const checks = [];
  if (searchFields.name) {
    checks.push(memberOnly
      ? exactMemberTextMatches(memberTokens, item.title || '')
      : normalizeSearchText(item.title).includes(q));
  }
  if (searchFields.member && enrich?.audience && memberTokens.length) {
    checks.push(audienceMatches(memberTokens, enrich.audience));
  }
  if (searchFields.branch) {
    checks.push(normalizeSearchText(item.source_site).includes(q));
    checks.push(normalizeSearchText(item.region).includes(q));
  }
  return checks.some(Boolean);
}

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

// 1. 底層成員詞彙解析：longest-match 不得把支部名稱拆錯。
checkArray('「幼童軍」不會抽出「童軍」', extractMemberTokens('幼童軍'), ['幼童軍']);
checkArray('「深資童軍」不會抽出「童軍」', extractMemberTokens('深資童軍'), ['深資童軍']);
checkArray('混合字串仍可辨認獨立「童軍」', extractMemberTokens('幼童軍暨童軍交流日'), ['幼童軍', '童軍']);

// 2. audience 精確配對。
const audienceCases = [
  { q: '童軍', aud: '幼童軍、深資童軍、樂行童軍', expect: false },
  { q: '童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { q: '幼童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { q: '幼童軍', aud: '童軍、領袖', expect: false },
  { q: '童軍 領袖', aud: '深資童軍、樂行童軍', expect: false },
  { q: '童軍 領袖', aud: '幼童軍、童軍、家長', expect: true },
  { q: '深資童軍', aud: '深資童軍、樂行童軍', expect: true },
  { q: '所有成員', aud: '所有成員、領袖', expect: true },
];
for (const test of audienceCases) {
  const got = audienceMatches(tokenizeMemberQuery(test.q), test.aud);
  check(`「${test.q}」vs audience「${test.aud}」`, got, test.expect);
}

// 3. 完整搜尋流程：成員欄位開啟時，結構化 audience 必須優先於標題 includes。
const allFields = { name: true, member: true, branch: true };
check(
  '搜「童軍」不命中標題「幼童軍訓練班」',
  matchesSearchQuery({ title: '幼童軍訓練班' }, { audience: '幼童軍' }, '童軍', allFields),
  false,
);
check(
  '搜「童軍」不命中標題「深資童軍訓練班」',
  matchesSearchQuery({ title: '深資童軍訓練班' }, { audience: '深資童軍' }, '童軍', allFields),
  false,
);
check(
  '即使標題有「香港童軍」，仍以 audience 為準',
  matchesSearchQuery({ title: '香港童軍深資活動' }, { audience: '深資童軍' }, '童軍', allFields),
  false,
);
check(
  'audience 有獨立「童軍」時正常命中',
  matchesSearchQuery({ title: '綜合訓練班' }, { audience: '幼童軍、童軍、領袖' }, '童軍', allFields),
  true,
);
check(
  '一般名稱關鍵字仍使用包含配對',
  matchesSearchQuery({ title: '深資童軍射箭訓練班' }, { audience: '深資童軍' }, '射箭', allFields),
  true,
);

// 4. 若使用者關閉「成員」欄位，名稱搜尋仍用 longest-match，避免巢狀誤中。
const nameOnly = { name: true, member: false, branch: false };
check(
  '名稱模式：童軍不命中幼童軍',
  matchesSearchQuery({ title: '幼童軍訓練班' }, null, '童軍', nameOnly),
  false,
);
check(
  '名稱模式：童軍可命中獨立童軍',
  matchesSearchQuery({ title: '童軍技能訓練班' }, null, '童軍', nameOnly),
  true,
);

// 5. 使用 repo 真實資料作回歸測試：所有「童軍」結果都必須有精確 audience token。
const base = __dirname;
const cache = JSON.parse(fs.readFileSync(path.join(base, 'cache.json'), 'utf8'));
const enrichMap = JSON.parse(fs.readFileSync(path.join(base, 'enrich.json'), 'utf8'));
const items = Object.values(cache.data || {}).flat();
const realMatches = items.filter(item => {
  const enrich = enrichMap[item.pdf_url] || enrichMap[item.url] || null;
  return matchesSearchQuery(item, enrich, '童軍', allFields);
});
const invalidRealMatches = realMatches.filter(item => {
  const enrich = enrichMap[item.pdf_url] || enrichMap[item.url] || null;
  return !extractMemberTokens(enrich?.audience || '').includes('童軍');
});
check('真實資料中「童軍」搜尋有結果', realMatches.length > 0, true);
check('真實資料中沒有非童軍 audience 混入', invalidRealMatches.length, 0);

console.log(`\n${pass}/${pass + fail} 通過；真實資料精準命中 ${realMatches.length} 筆`);
process.exit(fail ? 1 : 0);
