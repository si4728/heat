import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[];
const browser=await Browser.launch();
async function waitFor(page,fn,timeout=45000,arg){const end=Date.now()+timeout;while(true){try{if(await page.eval(fn,arg))return;}catch{}if(Date.now()>end)throw new Error('Advanced browser timeout');await new Promise(r=>setTimeout(r,150));}}
try{
 const page=await browser.newPage({width:1440,height:1050});
 await page.send('Network.enable');await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
 await page.send('Page.addScriptToEvaluateOnNewDocument',{source:`const originalFetch=window.fetch;window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0]).endsWith('/execute')){window.checkedResult=(await response.clone().json()).result;}return response;};`});
 for(let index=0;index<cfg.questions.length;index++){
  await page.goto(cfg.base+'/inspections/text-to-sql');
  assert.ok(await page.eval(()=>document.querySelectorAll('[data-question]').length>=17));
  await page.eval(values=>{if(values.legacy)document.getElementById('sql-result-unit').value='legacy';const q=document.getElementById('sql-question');q.value=values.question;q.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('sql-question-form').requestSubmit();},{question:cfg.questions[index],legacy:index===2});
  await waitFor(page,()=>!document.getElementById('sql-execute').disabled);
  await page.eval(()=>{window.checkedResult=null;document.getElementById('sql-execute').click();});
  await waitFor(page,()=>!!window.checkedResult);
  const result=await page.eval(()=>window.checkedResult);
  assert.ok(result.rows.length>0);
  assert.ok(!result.columns.some(k=>/_id$/.test(k)));
  if(index===1){assert.ok(result.rows.every(r=>r.wall_loss_increase_percent_points>=5));assert.ok(result.columns.includes('previous_inspection_date'));}
  if(index===2){assert.ok(result.rows.every(r=>r.matching_tube_count>0&&r.maximum_corrosion_rate_mm_per_year>=.1));}
  if(index===3){assert.equal(result.result_unit,'team');assert.equal(result.rows.reduce((n,r)=>n+r.exchanger_count,0),result.matched_equipment_count);assert.ok(await page.eval(()=>!!document.querySelector('#sql-result-table a[href*="/analysis?exchanger_id="]')));}
  if(index===4)assert.ok(result.rows.every(r=>r.sample_count<10));
  if(index===5)assert.ok(result.rows.every(r=>['REQUIRED','OPTIONAL'].includes(r.iris_applicability)&&(!r.latest_inspection_date||r.latest_inspection_date<r.inspection_cutoff_date)));
  if(index===6){assert.ok(result.rows.length<=10);assert.ok(result.rows.every(r=>r.tube_material.toUpperCase().replace(/[^A-Z0-9]/g,'').startsWith('CUNI')&&r.maximum_loss!==null));}
  if(index===7){assert.equal(result.result_unit,'inspection');assert.ok(!result.columns.includes('remaining_display'));assert.ok(result.columns.includes('reported_plugging_after'));assert.ok(await page.eval(()=>!!document.querySelector('#sql-result-table a[href*="/inspections/"]')));}
  await waitFor(page,()=>!document.getElementById('sql-commentary-retry').disabled,150000);
  const model=await page.eval(()=>document.getElementById('sql-commentary-model').textContent);
  if(cfg.real_model&&(index===3||index===7)){
   assert.ok(model.includes('gemma'));
   assert.deepEqual(await page.eval(()=>[...document.querySelectorAll('#sql-commentary-text h3')].map(h=>h.textContent)),['조회 요약','우선 확인 대상','해석의 한계']);
  }
  const overflow=await page.eval(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false);
  await page.eval(()=>document.getElementById('sql-result-table').scrollIntoView({block:'start'}));
  await page.screenshot({path:cfg.out+'/question-'+(index+1)+'.png',format:'png',fullPage:true});
  checks.push({number:index+1,matched:result.matched_count,rows:result.rows.length,unit:result.result_unit||'equipment',model});
  writeFileSync(cfg.out+'/progress.json',JSON.stringify(checks,null,2));
 }
 for(const width of [768,390]){
  await page.setViewport({width,height:1050});
  assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:cfg.out+'/history-'+width+'.png',format:'png',fullPage:true});
 }
 writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks,realAggregateModel:cfg.real_model},null,2));
 console.log('PASS: eight questions, correct row units, links, three viewports, aggregate narration='+cfg.real_model);
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
