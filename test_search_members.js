// 簡單測試成員搜尋精確匹配邏輯
const KNOWN_MEMBERS = [
  '小童軍', '幼童軍', '童軍', '深資童軍', '樂行童軍',
  '領袖', '家長', '成年成員', '會務委員', '公眾', '親友', '所有成員',
];

function tokenizeMemberQuery(query) {
  const parts = query.toLowerCase().trim().split(/[\s,，、/]+/).filter(Boolean);
  const tokens = [];
  for (const p of parts) {
    if (KNOWN_MEMBERS.some(m => m.toLowerCase() === p)) {
      tokens.push(p);
    }
  }
  return [...new Set(tokens)];
}

function audienceMatches(queryTokens, audience) {
  if (!audience || !queryTokens.length) return false;
  const audParts = audience.toLowerCase().split(/[\s,，、/]+/).filter(Boolean);
  const audTokens = audParts.filter(p => KNOWN_MEMBERS.some(m => m.toLowerCase() === p));
  return queryTokens.some(qt => audTokens.includes(qt));
}

const tests = [
  { q: '童軍', aud: '幼童軍、深資童軍、樂行童軍', expect: false },
  { q: '童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { q: '幼童軍', aud: '幼童軍、童軍、領袖', expect: true },
  { q: '幼童軍', aud: '童軍、領袖', expect: false },
  { q: '童軍 領袖', aud: '深資童軍、樂行童軍', expect: false },
  { q: '童軍 領袖', aud: '幼童軍、童軍、家長', expect: true },
  { q: '深資童軍', aud: '深資童軍、樂行童軍', expect: true },
  { q: '所有成員', aud: '所有成員、領袖', expect: true },
];

let pass = 0, fail = 0;
for (const t of tests) {
  const tokens = tokenizeMemberQuery(t.q);
  const got = audienceMatches(tokens, t.aud);
  const ok = got === t.expect;
  console.log(`${ok ? '✅' : '❌'} 「${t.q}」 vs 「${t.aud}」 → ${got} (expect ${t.expect})`);
  if (ok) pass++; else fail++;
}
console.log(`\n${pass}/${tests.length} 通過`);
process.exit(fail ? 1 : 0);
