// 問題回報 / 意見反映：對接 Scout Admin Apps Script（scout-admin.git）
//   用法： node test_report_feedback.js
//
// 抽出 index.html 嘅純函數（唔複製一份），並靜態檢查誤加嘅預覽／Cloudflare 已清走。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const base = __dirname;
const htmlPath = path.join(base, 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');

let pass = 0;
let fail = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? '✅' : '❌'} ${label} → ${JSON.stringify(actual)} (expect ${JSON.stringify(expected)})`);
  if (ok) pass += 1;
  else fail += 1;
}
function ok(cond, label) {
  console.log(`${cond ? '✅' : '❌'} ${label}`);
  if (cond) pass += 1;
  else fail += 1;
}

// ---------- 1. 上一個 agent 誤加嘅預覽／Cloudflare 唔可以再出現 ----------
ok(!fs.existsSync(path.join(base, 'preview_scout_tools.html')),
  'preview_scout_tools.html 已刪除，唔再跟 repo 一齊上線');
ok(!html.includes('preview_scout_tools.html'), 'index.html 冇獨立預覽頁連結');
ok(!html.includes('btn-open-tools-modal'), 'index.html 冇即席對比預覽掣');
ok(!html.includes('tools-preview-backdrop'), 'index.html 冇 tools 預覽彈窗');
ok(!html.includes('initToolsPreviewModal'), 'index.html 冇 initToolsPreviewModal');
ok(!html.includes('已注入 4 本紀錄冊'), 'index.html 冇開發用預覽橫額');
ok(!html.includes('__CF$cv$params'), 'index.html 冇 Cloudflare challenge 注入');
ok(!html.includes('cdn-cgi/challenge-platform'), 'index.html 冇 cdn-cgi challenge script');
ok(/<\/script>\s*<\/body>\s*<\/html>\s*$/.test(html), 'index.html 正常收尾（script → body → html）');

// ---------- 2. 表單 DOM 入口 ----------
ok(html.includes('id="report-backdrop"'), '有問題回報／意見反映彈窗');
ok(html.includes('id="report-app"'), '有 APP 欄');
ok(html.includes('id="report-problem"'), '有「什麼問題」欄');
ok(html.includes('id="report-opinion"'), '有「有什麼意見」欄');
ok(html.includes('id="report-name"'), '有選填姓名');
ok(html.includes('id="report-email"'), '有選填電郵');
ok(html.includes('id="report-phone"'), '有選填電話');
ok(html.includes('id="open-report-mobile"') && html.includes('aria-label="問題回報／意見反映"'),
  '頂欄叮噹旁有 💬 回報 icon');
ok(html.includes("reportBtn.id = 'open-report-settings'"),
  '桌面天數列叮噹旁有 💬 回報掣');
ok(html.includes('id="open-issue-report"') && html.includes('id="open-feedback-report"'),
  '頁尾有問題回報／意見反映入口');
ok(html.includes('id="open-issue-report-side"') && html.includes('id="open-feedback-report-side"'),
  '側欄診斷區有同一組入口');
ok(html.includes('novalidate'), '表單 novalidate（意見／問題分頁唔好被隱藏欄擋住）');
ok(!html.includes('id="report-backdrop"') || html.indexOf('id="report-backdrop"') > html.indexOf('id="push-settings"'),
  '回報彈窗喺通知設定外面（唔好污染 #push-settings）');

const endpoint = 'https://script.google.com/macros/s/AKfycbxj5BDDGgjs559smkK4Z5aYImWYeXbN5af8U1ObON0z9WnsN6QJW4I1XWolhs5kQ_H-UQ/exec';
ok(html.includes(endpoint), 'SCOUT_ADMIN_ENDPOINT 指向 scout-admin Apps Script');
ok(html.includes("mode: 'no-cors'"), '提交用 no-cors（Apps Script 標準做法）');

// ---------- 3. 抽出純函數 ----------
const constStart = html.indexOf('    const SCOUT_ADMIN_ENDPOINT');
const constEnd = html.indexOf('    const RAW_ENRICH_URL');
const fnStart = html.indexOf('    function formatReportContact(');
const fnEnd = html.indexOf('    function initReportSheet()');
ok(constStart >= 0 && constEnd > constStart, '揾到 SCOUT_ADMIN 常數');
ok(fnStart >= 0 && fnEnd > fnStart, '揾到回報純函數區塊');
if (constStart < 0 || fnStart < 0 || fnEnd < fnStart) {
  console.log(`fail=${fail} pass=${pass}`);
  process.exit(1);
}
const src = html.slice(constStart, constEnd) + html.slice(fnStart, fnEnd);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + `
  ;__exports = {
    SCOUT_ADMIN_ENDPOINT, SCOUT_ADMIN_DEFAULT_APP,
    formatReportContact, issueTitleFromProblem,
    buildIssuePayload, buildFeedbackPayload, validateReportForm, postScoutAdmin
  };
`, ctx);
const {
  SCOUT_ADMIN_ENDPOINT, SCOUT_ADMIN_DEFAULT_APP,
  formatReportContact, issueTitleFromProblem,
  buildIssuePayload, buildFeedbackPayload, validateReportForm,
} = ctx.__exports;

check('預設 APP', SCOUT_ADMIN_DEFAULT_APP, '通告圖書館');
check('endpoint', SCOUT_ADMIN_ENDPOINT, endpoint);

check('聯絡全空 → 空字串', formatReportContact('', '', ''), '');
check('只有姓名', formatReportContact(' 陳大文 ', '', ''), '姓名：陳大文');
check('姓名+電郵+電話', formatReportContact('陳大文', 'a@b.com', '91234567'),
  '姓名：陳大文；電郵：a@b.com；電話：91234567');
check('只有電話', formatReportContact('', '', '9123 4567'), '電話：9123 4567');

check('標題取首行', issueTitleFromProblem('打唔開 PDF\n第二行'), '打唔開 PDF');
check('空問題標題 fallback', issueTitleFromProblem('   \n  '), '問題回報');
const long = '字'.repeat(50);
ok(issueTitleFromProblem(long) === '字'.repeat(40) + '…',
  '超長問題標題截斷 40 字 + …');

const issue = buildIssuePayload({
  app: '幼童軍進度追蹤系統',
  problem: '進度儲唔到\n撳儲存冇反應',
  name: '李四',
  email: 'lee@example.com',
  phone: '5555 0000',
  pageUrl: 'https://library.example/index.html',
});
check('issue.type', issue.type, 'issue');
check('issue.sourceApp', issue.sourceApp, '幼童軍進度追蹤系統');
check('issue.title', issue.title, '進度儲唔到');
ok(issue.desc.startsWith('進度儲唔到\n撳儲存冇反應') && issue.desc.includes('頁面：https://library.example/index.html'),
  'issue.desc 含問題全文 + 頁面 URL');
check('issue.severity', issue.severity, '中');
check('issue.troopId 留空', issue.troopId, '');
check('issue.contact', issue.contact, '姓名：李四；電郵：lee@example.com；電話：5555 0000');
ok(JSON.stringify(Object.keys(issue).sort()) === JSON.stringify(
  ['contact', 'desc', 'severity', 'sourceApp', 'title', 'troopId', 'type'].sort()),
  'issue payload 欄位同 Apps Script _handleIssue 對齊');

const issueAnon = buildIssuePayload({ app: '通告圖書館', problem: '列表空白' });
check('匿名 issue.contact 空', issueAnon.contact, '');
ok(!issueAnon.desc.includes('頁面：'), '冇 pageUrl 就唔加頁面行');
check('空 app fallback 通告圖書館', buildIssuePayload({ app: '  ', problem: 'x' }).sourceApp, '通告圖書館');

const fb = buildFeedbackPayload({
  app: '通告圖書館',
  opinion: '想要旅團行事曆匯出',
  name: '',
  email: 'help@example.com',
  phone: '',
});
check('feedback.type', fb.type, 'feedback');
check('feedback.fbType 預設建議', fb.fbType, '建議');
check('feedback.sourceApp', fb.sourceApp, '通告圖書館');
check('feedback.content', fb.content, '想要旅團行事曆匯出');
check('feedback.troopId 留空', fb.troopId, '');
check('feedback.contact 只有電郵', fb.contact, '電郵：help@example.com');
ok(JSON.stringify(Object.keys(fb).sort()) === JSON.stringify(
  ['contact', 'content', 'fbType', 'sourceApp', 'troopId', 'type'].sort()),
  'feedback payload 欄位同 Apps Script _handleFeedback 對齊');

check('缺 APP', validateReportForm('issue', { app: '', problem: '壞咗' }), '請填寫 APP 名稱。');
check('缺問題', validateReportForm('issue', { app: '通告圖書館', problem: '  ' }), '請填寫什麼問題。');
check('缺意見', validateReportForm('feedback', { app: '通告圖書館', opinion: '' }), '請填寫意見。');
check('電郵格式', validateReportForm('issue', { app: '通告圖書館', problem: '壞', email: 'not-an-email' }),
  '電郵格式唔正確。');
check('選填全空 OK', validateReportForm('issue', { app: '通告圖書館', problem: '壞' }), '');
check('意見+姓名 OK', validateReportForm('feedback', {
  app: '通告圖書館', opinion: '想要幫助填金紫荊表', name: '王五', phone: '90001111',
}), '');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
