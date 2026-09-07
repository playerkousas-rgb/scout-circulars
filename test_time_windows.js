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
console.log('🎉 Hong Kong date-only 今天 midnight boundary and 7天 retention passed');
