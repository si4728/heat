import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8'));
const browser=await Browser.launch();
async function waitFor(page,fn,timeout=30000,arg){const end=Date.now()+timeout;while(true){try{if(await page.eval(fn,arg))return;}catch{}if(Date.now()>end)throw new Error('Browser UAT timeout');await new Promise(r=>setTimeout(r,120));}}
const checks=[];
try{
 const page=await browser.newPage({width:1440,height:1000});
 await page.send('Network.enable');
 await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
 await page.goto(cfg.base+'/inspections/text-to-sql');
 assert.equal(await page.eval(()=>!!document.querySelector('#sql-units input[value="PE"]')),true);
 await page.eval(()=>{const q=document.getElementById('sql-question');q.value='PE 잔여수명 5년 이하 열교환기';q.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('sql-question-form').requestSubmit();});
 await waitFor(page,()=>!document.getElementById('sql-execute').disabled);
 await page.eval(()=>document.getElementById('sql-execute').click());
 await waitFor(page,()=>document.querySelectorAll('#sql-result-table tbody tr').length>0);
 const rows=await page.eval(()=>[...document.querySelectorAll('#sql-result-table tbody tr')].map(r=>r.textContent));
 assert.ok(rows.every(r=>r.includes('PE')));checks.push({name:'PE Text-to-SQL rows',count:rows.length});
 await page.screenshot({path:cfg.out+'/pe-text-sql.png',format:'png',fullPage:true});
 await page.goto(cfg.base+'/?life_band=unknown');
 assert.equal(await page.eval(()=>document.querySelector('.life-band-table').textContent.includes('IRIS 미실시')),true);
 assert.equal(await page.eval(()=>document.querySelector('.life-band-table').textContent.includes('한도 미도달')),false);
 assert.equal(await page.eval(()=>document.getElementById('remaining-life-list').textContent.includes('감육 미검출')),true);
 checks.push({name:'dashboard bands and reasons',passed:true});
 await page.screenshot({path:cfg.out+'/dashboard.png',format:'png',fullPage:true});
 await page.goto(cfg.base+'/analysis?exchanger_id=100');
 await waitFor(page,()=>!!document.querySelector('#plugging-history table')||document.getElementById('plugging-history')?.textContent.includes('없습니다'));
 const before=await page.eval(()=>JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count);
 const ids=await page.eval(async()=>{const state=await (await fetch('/analysis/100/plugging')).json();return [...document.querySelectorAll('#precision-tube-map [data-tube-id]')].map(b=>Number(b.dataset.tubeId)).filter(id=>state.versions[String(id)]&&state.versions[String(id)].status!=='PLUGGED').filter((id,i,a)=>a.indexOf(id)===i).slice(0,2);});
 assert.equal(ids.length,2);
 await page.eval((values)=>{document.getElementById('plugging-select-mode').checked=true;for(const id of values.ids)document.querySelector('#precision-tube-map [data-tube-id="'+id+'"]').click();document.getElementById('plugging-date').value=values.today;document.getElementById('plugging-reason').value='격리 시험 DB의 UI 완료 등록';},{ids,today:cfg.today});
 assert.equal(await page.eval(()=>document.getElementById('plugging-selection').textContent.includes('2본')),true);
 await page.eval(()=>document.getElementById('plugging-complete').click());
 await waitFor(page,()=>document.querySelectorAll('[data-plugging-event]').length===2);
 assert.equal(await page.eval(()=>JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count),before+2);
 const plugged=await page.eval(values=>{const data=JSON.parse(document.getElementById('precision-map-data').textContent);return data.tubes.filter(t=>values.includes(Number(t.tube_id))).map(t=>t.category);},ids);
 assert.ok(plugged.every(v=>v==='PLUGGED'));checks.push({name:'multi-tube completion, Map and actual count',passed:true});
 await page.screenshot({path:cfg.out+'/plugging-completed.png',format:'png',fullPage:true});
 for(let left=2;left>0;left--){
  await page.eval(()=>{document.getElementById('plugging-reason').value='격리 시험 잘못된 등록 취소';document.querySelector('[data-plugging-event]').click();});
  await waitFor(page,expected=>document.getElementById('plugging-history')?.textContent.includes('등록 취소')&&document.querySelectorAll('[data-plugging-event]').length===expected,30000,left-1);
 }
 assert.equal(await page.eval(()=>JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count),before);
 const history=await page.eval(async()=>await (await fetch('/analysis/100/plugging')).json());
 assert.equal(history.history.length,4);assert.ok(history.history.every(e=>e.actor&&e.date&&e.registered_at));
 checks.push({name:'cancellation restores original count and keeps actor/date history',passed:true});
 for(const width of [1440,768,390]){
  await page.setViewport({width,height:1000});
  assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:cfg.out+'/analysis-'+width+'.png',format:'png',fullPage:true});
 }
 writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks,summaryModel:'TEST_STUB; all HTTP, authorization, business reads/writes and page JS are real on a disposable DB'},null,2));
 console.log('PASS: PE Text-to-SQL, dashboard bands/reasons, actual Map completion/cancellation/history; 3 viewport widths.');
}finally{await browser.close();}
