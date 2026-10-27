// No DOM or dependencies needed: verify actual migration helper from each page.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
  const base = 'https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/';
  for (const page of ['index.html', 'errors.html', 'stats.html']) {
    const html = fs.readFileSync(page, 'utf8');
    const body = html.match(/async function fetchDataSnapshot\(url, options\) \{[\s\S]*?\n    \}/)[0];
    for (const [status, url, expected] of [
      [404, base + 'data/cache.json?t=123', [base + 'data/cache.json?t=123', base + 'main/cache.json?t=123']],
      [200, base + 'data/cache.json', [base + 'data/cache.json']],
      [500, base + 'data/cache.json', [base + 'data/cache.json']],
      [404, 'https://custom.example/data/cache.json', ['https://custom.example/data/cache.json']],
    ]) {
      const calls = [];
      const ctx = vm.createContext({fetch: async u => { calls.push(u); return {status}; }});
      vm.runInContext(body, ctx);
      await ctx.fetchDataSnapshot(url, {cache: 'no-store'});
      assert.deepEqual(calls, expected, page);
    }
    // Parse every inline script without executing DOM code.
    for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
      if (match[1].trim()) new vm.Script(match[1], {filename: page});
    }
  }
  console.log('PASS: three pages parse; 404 migration fallback preserves custom URLs and HTTP errors.');
})().catch(err => { console.error(err); process.exitCode = 1; });
