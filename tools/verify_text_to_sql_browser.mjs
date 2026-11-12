import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { Browser } from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const root=resolve('.'), output=join(root,'reports/text_to_sql/browser');
mkdirSync(output,{recursive:true});
const privateSession=join(root,'tmp/text_to_sql_browser_session.json');
const cookie=JSON.parse(readFileSync(privateSession,'utf8'));
const browser=await Browser.launch();
const report={checks:[],viewports:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function check(name,passed) { report.checks.push({name,passed:!!passed}); console.log(name,!!passed); if(!passed)throw new Error(name); }
try {
  const page=await browser.newPage({width:1440,height:900});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{...cookie,url:'http://127.0.0.1:4824',httpOnly:true,sameSite:'Lax'});
  unlinkSync(privateSession);
  await page.goto('http://127.0.0.1:4824/inspections/text-to-sql');
  check('authenticated_screen',await page.eval(()=>!!document.getElementById('sql-question-form')));
  check('main_menu_link',await page.eval(()=>!!document.querySelector('nav a.active[href="/inspections/text-to-sql"]')));
  for (const width of [1440,768,390]) {
    await page.setViewport({width,height:width===1440?900:width===768?1024:844});await sleep(250);
    const measurements=await page.eval(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,title:document.querySelector('h1').innerText}));
    report.viewports.push({width,...measurements});check(`no_page_overflow_${width}`,measurements.document<=measurements.viewport+1);
    if(width===390) check('mobile_navigation_folded',await page.eval(()=>document.querySelector('.app-shell').classList.contains('sidebar-collapsed')));
    await page.screenshot({path:join(output,`initial-${width}.png`),format:'png',fullPage:true});
  }
  await page.setViewport({width:1440,height:900});
  await page.eval(()=>{const e=document.getElementById('sql-equipment');e.value='151';e.dispatchEvent(new Event('change',{bubbles:true}));});
  async function waitFor(expression,timeout=15000) {
    const start=Date.now();while(Date.now()-start<timeout){if(await page.eval(expression))return;await sleep(300);}throw new Error('Timed out: '+expression);
  }
  await waitFor("document.getElementById('sql-inspection').options.length > 1");
  await page.eval(()=>{
    const i=document.getElementById('sql-inspection');i.value='389';i.dispatchEvent(new Event('change',{bubbles:true}));
    document.querySelector('[data-question="검사 결과를 요약해 줘."]').click();
    document.getElementById('sql-question-form').requestSubmit();
  });
  await waitFor("document.getElementById('text-sql').getAttribute('aria-busy') === 'false'",140000);
  check('real_model_sql_generated',await page.eval(()=>!document.getElementById('sql-execute').disabled&&document.getElementById('sql-code').value.includes('COUNT(*)')));
  await page.eval(()=>document.getElementById('sql-execute').click());
  await waitFor("document.getElementById('text-sql').getAttribute('aria-busy') === 'false'",15000);
  report.result=await page.eval(()=>({count:document.getElementById('sql-result-count').textContent,
    cells:[...document.querySelectorAll('#sql-result-table tbody td')].map(e=>e.textContent),
    error:document.getElementById('sql-error').hidden?null:document.getElementById('sql-error').textContent,
    sql:document.getElementById('sql-code').value}));
  check('real_results_visible',report.result.count==='1행'&&report.result.cells.includes('82')&&report.result.cells.includes('0.12')&&!report.result.error);
  for (const width of [1440,768,390]) {
    await page.setViewport({width,height:width===1440?900:width===768?1024:844});await sleep(200);
    check(`results_no_page_overflow_${width}`,await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:join(output,`results-${width}.png`),format:'png',fullPage:true});
  }
  // Synthetic transport fixtures test rendering only, after real DB screenshots.
  await page.eval(()=>{
    window.realFetch=window.fetch;
    window.renderFixture={columns:['zero_value','missing_value','unsafe_text'],rows:[{zero_value:0,missing_value:null,unsafe_text:'<img src=x onerror=alert(1)>'}],result_count:1,limit_reached:false,generated_at:new Date().toISOString()};
    window.fetch=async (...args)=>String(args[0]).endsWith('/text-to-sql/execute')?new Response(JSON.stringify({result:window.renderFixture}),{status:200,headers:{'Content-Type':'application/json'}}):window.realFetch(...args);
    document.getElementById('sql-execute').click();
  });
  await waitFor("document.getElementById('text-sql').getAttribute('aria-busy') === 'false'");
  check('zero_null_and_html_are_safe',await page.eval(()=>{
    const cells=[...document.querySelectorAll('#sql-result-table tbody td')].map(e=>e.textContent);
    return cells[0]==='0'&&cells[1]==='—'&&cells[2].startsWith('<img')&&!document.querySelector('#sql-result-table img');
  }));
  await page.eval(()=>{window.renderFixture.rows=[];window.renderFixture.result_count=0;document.getElementById('sql-execute').click();});
  await waitFor("document.getElementById('text-sql').getAttribute('aria-busy') === 'false'");
  check('empty_results_keep_headers',await page.eval(()=>!document.getElementById('sql-empty').hidden&&document.querySelectorAll('#sql-result-table thead th').length===3&&document.getElementById('sql-result-count').textContent==='0행'));
  await page.eval(()=>{window.fetch=window.realFetch;delete window.realFetch;delete window.renderFixture;});
  await page.eval(()=>{const q=document.getElementById('sql-question');q.value='감육률 30% 이상인 Tube를 보여줘.';q.dispatchEvent(new Event('input',{bubbles:true}));});
  check('edited_question_invalidates_old_sql',await page.eval(()=>document.getElementById('sql-execute').disabled&&document.getElementById('sql-result-table').hidden));
  report.consoleErrors=page.consoleErrors;
  check('no_javascript_errors',!page.consoleErrors.length);
} finally {
  writeFileSync(join(output,'validation.json'),JSON.stringify(report,null,2));
  await browser.close();
}
