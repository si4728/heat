import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),browser=await Browser.launch();
async function until(page,fn){const end=Date.now()+30000;while(!await page.eval(fn)){if(Date.now()>end)throw new Error('Single plugging timeout');await new Promise(r=>setTimeout(r,150));}}
try{
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  await page.goto(cfg.base+'/analysis?exchanger_id=100');
  await until(page,()=>!!document.getElementById('plugging-history')?.textContent.trim());
  const before=await page.eval(()=>JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count);
  const id=await page.eval(async()=>{const state=await(await fetch('/analysis/100/plugging')).json();return [...document.querySelectorAll('#precision-tube-map [data-tube-id]')]
    .map(n=>Number(n.dataset.tubeId)).find(id=>['ACTIVE','IN_SERVICE','UNUSED'].includes(state.versions[String(id)]?.status));});
  assert.ok(id);
  await page.eval(values=>{document.getElementById('plugging-select-mode').checked=false;
    document.querySelector('#precision-tube-map [data-tube-id="'+values.id+'"]').click();
    document.getElementById('plugging-date').value=values.today;document.getElementById('plugging-reason').value='Isolated single-tube UI audit';},{id,today:cfg.today});
  assert.ok(await page.eval(()=>document.getElementById('plugging-selection').textContent.includes('1본')));
  await page.eval(()=>document.getElementById('plugging-complete').click());
  await until(page,()=>document.querySelectorAll('[data-plugging-event]').length===1);
  const completed=await page.eval(id=>({count:JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count,
    category:JSON.parse(document.getElementById('precision-map-data').textContent).tubes.find(t=>Number(t.tube_id)===id).category}),id);
  assert.equal(completed.count,before+1);assert.equal(completed.category,'PLUGGED');
  await page.screenshot({path:cfg.out+'/single-completed.png',format:'png',fullPage:true});
  await page.eval(()=>{document.getElementById('plugging-reason').value='Cancel isolated single-tube UI audit';document.querySelector('[data-plugging-event]').click();});
  await until(page,()=>document.querySelectorAll('[data-plugging-event]').length===0&&document.getElementById('plugging-history').textContent.includes('등록 취소'));
  const after=await page.eval(()=>JSON.parse(document.getElementById('precision-life-data').textContent).actual_plugged_count);
  assert.equal(after,before);
  const history=await page.eval(async()=>await(await fetch('/analysis/100/plugging')).json());
  assert.ok(history.history.every(e=>e.actor&&e.date&&e.registered_at));
  await page.screenshot({path:cfg.out+'/single-cancelled.png',format:'png',fullPage:true});
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks:[{singleSelection:true,completed,restored:after,historyEvents:history.history.length}]},null,2));
  console.log('PASS: one tube selected/completed/cancelled through actual UI; actor/date retained.');
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
