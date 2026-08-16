// errors.html 診斷儀表板 DOM 測試
//   用法： npm i jsdom && node test_errors_dashboard.js [cache.json]
//   驗證新鮮度分欄渲染、總和一致、點擊篩選、其他面板無損。
const {JSDOM}=require('jsdom');const fs=require('fs');
const cache=JSON.parse(fs.readFileSync(process.argv[2]||'cache.json','utf8'));
const enrich=JSON.parse(fs.readFileSync('enrich.json','utf8'));
const html=fs.readFileSync('errors.html','utf8');
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://localhost/errors.html',
  beforeParse(win){ win.fetch=(u)=>Promise.resolve({ok:true,status:200,
    json:()=>Promise.resolve(String(u).includes('enrich')?enrich:cache)}); }});
const w=dom.window;
let fail=0;const ok=(c,m)=>{console.log((c?'✅ ':'❌ ')+m);if(!c)fail++;};
w.addEventListener('load',async()=>{
  await new Promise(r=>setTimeout(r,600));
  const d=w.document;
  const cols=d.querySelectorAll('.fresh-col');
  ok(cols.length===6,`6 個分欄渲染咗（實際 ${cols.length}）`);
  const labels=[...cols].map(c=>c.querySelector('.flabel').textContent);
  ok(JSON.stringify(labels)===JSON.stringify(['今天','7 天內','14 天內','1 個月內','3 個月內','超過 3 個月']),
     '欄目次序正確: '+labels.join(' | '));
  const nums=[...cols].map(c=>+c.querySelector('.fnum').textContent);
  console.log('   數字:',nums.join(' / '));
  const rowsAll=d.querySelectorAll('#stale-table tbody tr').length;
  ok(nums.reduce((a,b)=>a+b,0)===rowsAll,`分欄總和 ${nums.reduce((a,b)=>a+b,0)} = 表格列數 ${rowsAll}`);
  ok(d.querySelectorAll('.fresh-bar span').length>0,'比例橫條有渲染');
  // 點擊篩選
  const target=[...cols].find(c=>+c.querySelector('.fnum').textContent>0);
  const tn=+target.querySelector('.fnum').textContent;
  target.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await new Promise(r=>setTimeout(r,50));
  const after=d.querySelectorAll('#stale-table tbody tr').length;
  ok(after===tn,`撳「${target.querySelector('.flabel').textContent}」→ 表格剩 ${after} 列（應為 ${tn}）`);
  ok(target.classList.contains('active'),'被撳嗰欄有 active 高亮');
  console.log('   標題:',d.getElementById('fresh-table-caption').textContent);
  // 再撳一次取消
  target.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await new Promise(r=>setTimeout(r,50));
  ok(d.querySelectorAll('#stale-table tbody tr').length===rowsAll,'再撳一次還原全部');
  ok(!target.classList.contains('active'),'active 高亮已取消');
  // 90 日門檻（唔再係 14 日）
  ok(html.includes('STALE_DAYS = 90'),'門檻已由 14 日改為 90 日');
  ok(!/超過 14 日無更新/.test(html),'卡片文案已更新');
  // 其他面板無損
  ok(d.getElementById('junk-count').textContent!=='—','疑似抓錯卡有數字: '+d.getElementById('junk-count').textContent);
  ok(d.querySelectorAll('#junk-table tbody tr').length>0,'疑似抓錯表格有列');
  ok(d.getElementById('stale-count').textContent!=='—','長期未更新卡: '+d.getElementById('stale-count').textContent);
  ok(d.getElementById('enrich-coverage').textContent!=='—','enrich 覆蓋率: '+d.getElementById('enrich-coverage').textContent);
  const errs=[...d.querySelectorAll('.status.error')].map(e=>e.textContent.trim()).filter(Boolean);
  ok(errs.length===0,'頁面無錯誤訊息'+(errs.length?': '+errs.join(''):''));
  console.log(fail?`\n❌ ${fail} 項失敗`:'\n🎉 全部通過');process.exit(fail?1:0);
});
w.addEventListener('error',e=>{console.log('❌ JS 執行錯誤:',e.message);process.exit(1);});
setTimeout(()=>{console.log('❌ 逾時');process.exit(1)},15000);
