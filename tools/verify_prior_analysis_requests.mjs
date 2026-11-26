import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[];
const browser=await Browser.launch();
async function until(page,fn){const end=Date.now()+15000;while(!await page.eval(fn)){if(Date.now()>end)throw new Error('Analysis history audit timeout');await new Promise(r=>setTimeout(r,120));}}
try{
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  await page.goto(cfg.base+'/analysis?exchanger_id=106');
  const empty=await page.eval(()=>({selection:document.querySelector('.analysis-selection-status').textContent,
    hasOtherAnalysis:!!document.getElementById('precision-life-data'),url:location.search}));
  assert.ok(empty.selection.includes('E-230'));assert.equal(empty.hasOtherAnalysis,false);assert.ok(empty.url.includes('106'));
  checks.push({name:'uninspected equipment never redirects to another analysis',...empty});
  await page.screenshot({path:cfg.out+'/uninspected-analysis.png',format:'png',fullPage:true});
  await page.goto(cfg.base+'/analysis?exchanger_id=202');
  await until(page,()=>!!document.querySelector('[data-analysis-tube]'));
  const summary=await page.eval(()=>({visible:!document.getElementById('equipment-summary').hidden,
    selectedHidden:document.getElementById('selected-tube-view').hidden,text:document.getElementById('equipment-summary').textContent}));
  assert.ok(summary.visible&&summary.selectedHidden);assert.ok(summary.text.includes('30년 이상'));assert.ok(!summary.text.includes('2321'));
  await page.eval(()=>document.querySelector('[data-analysis-tube]').click());
  assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),false);
  await page.eval(()=>document.getElementById('show-equipment-summary').click());
  assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),true);
  checks.push({name:'initial Summary, tube selection and return, thirty year cap',passed:true});
  await page.goto(cfg.base+'/exchangers/202');
  const detail=await page.eval(()=>({headers:[...document.querySelectorAll('th')].map(th=>th.textContent.trim()),
    qrLinks:document.querySelectorAll('a[href*="/qr"],[data-qr-scan-open]').length}));
  assert.equal(detail.qrLinks,0);
  assert.ok(['단기 감육속도(mm/년)','장기 감육속도(mm/년)','적용 감육속도(mm/년)'].every(label=>detail.headers.includes(label)));
  checks.push({name:'detail hides QR and uses corrosion-rate names',...detail});
  await page.screenshot({path:cfg.out+'/detail-labels.png',format:'png',fullPage:true});
  for(const id of [139,143,199,142]){
    await page.goto(cfg.base+'/analysis?exchanger_id='+id);
    const state=await page.eval(()=>{
      const life=JSON.parse(document.getElementById('precision-life-data').textContent);
      return {sample:life.equipment_overview.sample_count,status:life.equipment_overview.sample_status,
        summary:document.getElementById('equipment-summary').textContent};
    });
    if(id===142){assert.equal(state.sample,20);assert.equal(state.status,'ESTIMATED');}
    else{assert.equal(state.status,'AMBIGUOUS_INSPECTION');assert.ok(state.summary.includes('번들 식별 필요'));}
    checks.push({name:'sample eligibility and explanatory reason',id,...state});
    await page.screenshot({path:cfg.out+'/sample-'+id+'.png',format:'png',fullPage:true});
  }
  assert.equal(cfg.pe_thresholds.length,6);
  for(const equipment of cfg.pe_thresholds){
    await page.goto(cfg.base+'/analysis?exchanger_id='+equipment.heat_exchanger_id+'&unit=PE');
    const state=await page.eval(()=>{
      const life=JSON.parse(document.getElementById('precision-life-data').textContent);
      return {reached:life.equipment_overview.threshold_reached_count,remaining:life.equipment_overview.remaining_display,
        measurementDate:life.equipment_overview.measurement_date,summary:document.getElementById('equipment-summary').textContent};
    });
    assert.ok(state.reached>0);assert.ok(state.measurementDate.startsWith('2020-'));
    assert.ok(state.summary.includes('실측 기준 도달 튜브'));
    if(equipment.exchanger_code==='E-131D')assert.equal(state.remaining,'산정 불가');
    checks.push({name:'PE observed threshold shown with measurement date',code:equipment.exchanger_code,...state});
    await page.screenshot({path:cfg.out+'/pe-'+equipment.exchanger_code+'.png',format:'png',fullPage:true});
  }
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks},null,2));
  console.log('PASS: prior analysis requests, sample reasons, and six PE threshold screens.');
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
