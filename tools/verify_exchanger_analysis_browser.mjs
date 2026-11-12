import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const output=resolve('reports/exchanger-analysis-20261112');
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try{
  const page=await browser.newPage({width:1440,height:1000});
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1000});
    await page.goto(pathToFileURL(resolve(output,'precision.html')).href);
    const state=await page.eval(()=>{
      const toggle=document.querySelector('.sidebar-toggle');
      if(innerWidth<1100 && toggle?.getAttribute('aria-expanded')==='true')toggle.click();
      const rows=[...document.querySelectorAll('[data-analysis-tube]')];
      const linked=rows.filter(row=>document.querySelector(`.precision-tube[data-tube-id="${row.dataset.analysisTube}"]`));
      const ids=linked.slice(0,2).map(row=>row.dataset.analysisTube);
      const results=[];
      for(const id of ids){
        document.querySelector(`.precision-tube[data-tube-id="${id}"]`).click();
        results.push({id,graph:document.querySelector('#thickness-trend').dataset.tubeId,
          table:document.querySelector('#corrosion-analysis').dataset.tubeId,
          selected:document.querySelector('[data-analysis-tube][aria-current="true"]')?.dataset.analysisTube,
          svg:!!document.querySelector('#thickness-trend svg')});
      }
      if(ids.length){rows.find(row=>row.dataset.analysisTube===ids[0]).click();}
      const life=JSON.parse(document.querySelector('#precision-life-data').textContent);
      const checks=life.analysis_tube_rows.filter(row=>['14-4','7-16'].includes(row.tube_no)).map(row=>{
        document.querySelector(`[data-analysis-tube="${row.tube_id}"]`).click();
        const slider=document.querySelector('#corrosion-rate-slider');
        slider.value='2';slider.dispatchEvent(new Event('input',{bubbles:true}));
        const result={tube:row.tube_no,label:row.corrosion_rate_selection_label,
          actualLabel:[...document.querySelectorAll('#corrosion-analysis tr')].find(tr=>tr.querySelector('th')?.textContent==='선정 근거')?.querySelector('td').textContent,
          expectedRate:(row.selected_base_corrosion_rate_mm_per_year*2).toFixed(4),
          selectedRate:document.querySelector('#applied-corrosion-rate').textContent,
          tableRate:document.querySelector(`[data-analysis-tube="${row.tube_id}"] [data-applied-rate]`).textContent,
          longRate:document.querySelector('#long-term-rate').textContent,
          expectedLong:row.long_term_corrosion_rate_mm_per_year.toFixed(4)};
        slider.value='1';slider.dispatchEvent(new Event('input',{bubbles:true}));
        return result;
      });
      if(ids.length){rows.find(row=>row.dataset.analysisTube===ids[0]).click();}
      return {overflow:document.documentElement.scrollWidth>innerWidth,rows:rows.length,results,
        rateChecks:checks,
        reverseSelected:document.querySelector('.precision-tube[aria-pressed="true"]')?.dataset.tubeId,
        forbidden:document.querySelectorAll('.analysis-workspace dialog,.analysis-workspace details,.analysis-workspace [role="tab"]').length};
    });
    assert.equal(state.overflow,false,JSON.stringify({width,state}));
    assert.equal(state.forbidden,0);
    assert.ok(state.results.length===2,JSON.stringify(state));
    for(const result of state.results){assert.equal(result.graph,result.id);assert.equal(result.table,result.id);assert.equal(result.selected,result.id);assert.ok(result.svg);}
    assert.equal(state.reverseSelected,state.results[0].id);
    assert.equal(state.rateChecks.length,2);
    for(const check of state.rateChecks){
      assert.equal(check.actualLabel,check.label);
      assert.equal(check.selectedRate,check.expectedRate);
      assert.equal(check.tableRate,check.expectedRate);
      assert.equal(check.longRate,check.expectedLong);
    }
    await page.eval(()=>document.querySelector('#precision-results-panel').scrollIntoView({block:'start'}));
    await page.screenshot({path:resolve(output,`analysis-${width}.png`),format:'png'});
    checks.push({width,...state,passed:true});
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,passed:true}));
}finally{await browser.close();}
