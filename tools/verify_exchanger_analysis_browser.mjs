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
      return {overflow:document.documentElement.scrollWidth>innerWidth,rows:rows.length,results,
        reverseSelected:document.querySelector('.precision-tube[aria-pressed="true"]')?.dataset.tubeId,
        forbidden:document.querySelectorAll('.main dialog,.main details,.main [role="tab"]').length};
    });
    assert.equal(state.overflow,false,JSON.stringify({width,state}));
    assert.equal(state.forbidden,0);
    assert.ok(state.results.length===2,JSON.stringify(state));
    for(const result of state.results){assert.equal(result.graph,result.id);assert.equal(result.table,result.id);assert.equal(result.selected,result.id);assert.ok(result.svg);}
    assert.equal(state.reverseSelected,state.results[0].id);
    await page.eval(()=>document.querySelector('#precision-results-panel').scrollIntoView({block:'start'}));
    await page.screenshot({path:resolve(output,`analysis-${width}.png`),format:'png'});
    checks.push({width,...state,passed:true});
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,passed:true}));
}finally{await browser.close();}
