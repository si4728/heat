import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[],browser=await Browser.launch();
try{
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  assert.equal(cfg.correction_targets.length,6);
  for(const equipment of cfg.correction_targets){
    await page.goto(cfg.base+'/analysis?exchanger_id='+equipment.heat_exchanger_id);
    const state=await page.eval(()=>{
      const life=JSON.parse(document.getElementById('precision-life-data').textContent);
      return {selection:document.querySelector('.analysis-selection-status').textContent,
        summary:document.getElementById('equipment-summary').textContent,
        total:life.total_tube_count,rows:life.analysis_tube_rows,overview:life.equipment_overview};
    });
    assert.ok(state.selection.includes(equipment.exchanger_code));
    const code=equipment.exchanger_code;
    if(['E-13','E-122A','E-341','E-222'].includes(code)){
      assert.equal(Math.max(...state.rows.map(r=>r.wall_loss_percent??-1)),0);
      assert.equal(state.overview.remaining_display,'산정 불가');
    }
    if(code==='E-341'){
      const corrected=state.rows.filter(r=>r.inspection_id===375);
      assert.equal(corrected.length,10);assert.ok(corrected.every(r=>r.minimum_wall_thickness_mm===2.77));
    }
    if(code==='E-222')assert.equal(state.total,179);
    if(code==='E-122A')assert.ok(state.rows.filter(r=>r.inspection_id===350).every(r=>r.minimum_wall_thickness_mm===null));
    if(code==='E-811')assert.ok(state.summary.includes('2020-10-24'));
    if(code==='E-331A'){assert.ok(state.summary.includes('30년 이상'));assert.ok(!state.summary.includes('2321'));}
    checks.push({code,total:state.total,summary:state.summary,remaining:state.overview.remaining_display,measurementDate:state.overview.measurement_date});
    await page.screenshot({path:cfg.out+'/'+code+'.png',format:'png',fullPage:true});
  }
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks},null,2));
  console.log('PASS: six requested equipment corrections/displays opened and checked.');
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
