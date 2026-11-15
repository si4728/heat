// Real template and renderer; mocked responses, no model inference or DB writes.
import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const root=resolve('.'), output=join(root,'tmp/text-to-sql-charts');
mkdirSync(output,{recursive:true});
const fixture=join(output,'screen.html');
const generated=spawnSync(join(root,'.venv/Scripts/python.exe'),['-c',String.raw`
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd().parent))
from iris2.app import create_app
from iris2 import dbapi
from iris2.hx_configuration import DB_PATH
c=dbapi.connect(DB_PATH,readonly=True)
uid=c.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0];c.close()
app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
client=app.test_client()
with client.session_transaction() as s:s.update(user_id=uid,last_activity_at=time.time(),csrf_token='fixture')
r=client.get('/inspections/text-to-sql');assert r.status_code==200
print(r.get_data(as_text=True).replace('"/static/', '"'+(Path.cwd()/'static').as_uri()+'/'))
`],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(generated.status,0,generated.stderr);
writeFileSync(fixture,generated.stdout);
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try {
  const page=await browser.newPage({width:1440,height:1000});
  await page.goto(pathToFileURL(fixture).href);
  assert.equal(await page.eval(()=>document.querySelector('[data-chart="type"]').disabled),true);
  assert.match(await page.eval(()=>document.querySelector('[data-chart="hint"]').textContent),/SQL 실행 후/);
  await page.eval(()=>{
    window.chartFixture={columns:['equipment_tag','tube_no','inspection_count','wall_loss_percent'],rows:[
      {equipment_tag:'E-106',tube_no:'1-1',inspection_count:9,wall_loss_percent:20},
      {equipment_tag:'E-107',tube_no:'1-1',inspection_count:3,wall_loss_percent:null},
      {equipment_tag:'E-107',tube_no:'2-1',inspection_count:0,wall_loss_percent:0},
      {equipment_tag:'<img src=x onerror=alert(1)>',tube_no:'3-1',inspection_count:null,wall_loss_percent:null}],
      result_count:4,limit_reached:true,generated_at:new Date().toISOString()};
    window.fetch=async url=>({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>String(url).endsWith('/generate')?
      {token:'fixture',proposal:{sql:'SELECT fixture',parameters:[]},query_kind:'inspection_frequency',period:{start:'2025-01-01',end:'2025-12-31',limit:10,target:'tube'},equipment_list:[]}:{result:window.chartFixture}});
    const q=document.getElementById('sql-question');q.value='검사 횟수 많은 튜브 10개';q.dispatchEvent(new Event('input'));
    document.getElementById('sql-question-form').requestSubmit();
  });
  async function wait(){
    for(let i=0;i<60;i++){
      if(await page.eval(()=>document.getElementById('text-sql').getAttribute('aria-busy')==='false'))return;
      await new Promise(r=>setTimeout(r,50));
    }throw new Error('Request rendering timed out');
  }
  async function execute(){await page.eval(()=>document.getElementById('sql-execute').click());await wait();await new Promise(r=>setTimeout(r,100));}
  async function change(key,value){await page.eval(({key,value})=>{const node=document.querySelector(`[data-chart="${key}"]`);node.value=value;node.dispatchEvent(new Event('change'));},{key,value});}
  await wait();await execute();
  assert.equal(await page.eval(()=>document.querySelectorAll('.sql-chart-bar').length),3);
  assert.equal(await page.eval(()=>document.querySelectorAll('#sql-chart-panel img').length),0);
  assert.match(await page.eval(()=>document.querySelector('[data-chart="note"]').textContent),/4행 기준.*유효 수치 3행.*결측 1행.*제한/);
  assert.equal(await page.eval(()=>document.getElementById('sql-chart-panel').getBoundingClientRect().top>document.getElementById('sql-result-panel').getBoundingClientRect().top),true);
  checks.push('Bar from returned rows; null excluded, zero retained; counts and limit disclosed; chart below list; safe text');
  await change('type','pie');
  assert.equal(await page.eval(()=>document.querySelectorAll('.sql-chart-legend li').length),3);
  assert.match(await page.eval(()=>document.querySelector('[data-chart="hint"]').textContent),/합계 12/);
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1000});
    await page.eval(()=>document.getElementById('sql-chart-panel').scrollIntoView());
    await new Promise(r=>setTimeout(r,150));
    assert.equal(await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.screenshot({path:join(output,`pie-${width}.png`),format:'png',fullPage:false});
  }
  checks.push('Pie totals, zero share, legend; desktop/tablet/mobile without page overflow');
  await change('metric','wall_loss_percent');
  assert.equal(await page.eval(()=>document.querySelector('[data-chart="type"] [value="pie"]').disabled),true);
  assert.equal(await page.eval(()=>document.querySelector('[data-chart="type"]').value),'bar');
  checks.push('Non-additive percentage pie disabled; safe fallback after metric changes');
  await page.eval(()=>{window.chartFixture={columns:['year','minimum_mm'],rows:[{year:2025,minimum_mm:1.8},{year:2023,minimum_mm:2.1},{year:2024,minimum_mm:null}],result_count:3,generated_at:new Date().toISOString()};});
  await execute();await change('type','line');
  assert.equal(await page.eval(()=>document.querySelectorAll('.sql-chart-point').length),2);
  assert.equal(await page.eval(()=>document.querySelectorAll('.sql-chart-line').length),0);
  await page.eval(()=>{window.chartFixture.rows[2].minimum_mm=2;});
  await execute();await change('type','line');
  assert.equal(await page.eval(()=>document.querySelectorAll('.sql-chart-line').length),1);
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1000});
    await page.eval(()=>document.getElementById('sql-chart-panel').scrollIntoView());
    await new Promise(r=>setTimeout(r,150));
    assert.equal(await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.screenshot({path:join(output,`line-${width}.png`),format:'png',fullPage:false});
  }
  checks.push('Chronological line, missing-value gaps, year labels and responsive axes');
  await page.eval(()=>{window.chartFixture={columns:['tube_id'],rows:[],result_count:0,generated_at:new Date().toISOString()};});
  await execute();
  assert.equal(await page.eval(()=>document.querySelectorAll('#sql-chart-panel svg').length),0);
  assert.match(await page.eval(()=>document.querySelector('[data-chart="hint"]').textContent),/조회 결과가 없어/);
  await page.eval(()=>{window.chartFixture.rows=[{tube_id:1}];window.chartFixture.result_count=1;});await execute();
  assert.match(await page.eval(()=>document.querySelector('[data-chart="hint"]').textContent),/수치 항목이 없어/);
  await page.eval(()=>{window.fetch=async()=>({ok:false,redirected:false,headers:{get:()=> 'application/json'},json:async()=>({error:'검증용 조회 실패'})});});
  await execute();
  assert.match(await page.eval(()=>document.querySelector('[data-chart="hint"]').textContent),/조회에 실패해/);
  assert.equal(await page.eval(()=>document.querySelectorAll('#sql-chart-panel svg').length),0);
  await page.eval(()=>{const q=document.getElementById('sql-question');q.value='검사 요약';q.dispatchEvent(new Event('input'));});
  assert.equal(await page.eval(()=>document.querySelectorAll('#sql-chart-panel svg').length),0);
  checks.push('Empty, ID-only, failed-query and changed-question states clear old charts');
  assert.deepEqual(page.consoleErrors,[]);
  writeFileSync(join(output,'validation.json'),JSON.stringify({passed:true,fixture_only:true,checks},null,2));
  console.log(JSON.stringify({passed:true,checks}));
} finally {await browser.close();}
