import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const output=resolve('reports/dashboard-team-20261112');
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try{
  const page=await browser.newPage({width:1440,height:1000});
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1000});
    await page.goto(pathToFileURL(resolve(output,'dashboard.html')).href);
    const state=await page.eval(()=>{
      const toggle=document.querySelector('.sidebar-toggle');
      if(innerWidth<1100 && toggle?.getAttribute('aria-expanded')==='true')toggle.click();
      document.querySelector('#remaining-life-list').open=true;
      const rows=[...document.querySelectorAll('.life-band-table tbody tr')];
      const team=rows[0];
      const counts=[...team.querySelectorAll('td')].map(td=>parseInt(td.textContent));
      return {overflow:document.documentElement.scrollWidth>innerWidth,
        team:team.querySelector('th').textContent,counts,
        drilldown:[...team.querySelectorAll('a')].map(a=>a.getAttribute('href')),
        qr:!!document.querySelector('[data-qr-scan-open],#dashboard-qr-modal'),
        capped:document.querySelector('#remaining-life-list').textContent.includes('30년 이상'),
        headers:[...document.querySelectorAll('#remaining-life-list thead th')].map(th=>th.textContent),
        annualTotals:document.querySelectorAll('.team-annual-total').length};
    });
    assert.equal(state.overflow,false,`${width}: overflow`);
    assert.equal(state.team,'VCM 생산팀');
    assert.equal(state.counts.slice(0,-1).reduce((a,b)=>a+b,0),state.counts.at(-1));
    assert.ok(state.drilldown.every(link=>!link.includes('life_unit=')));
    assert.equal(state.qr,false);assert.ok(state.capped);
    assert.deepEqual(state.headers.slice(0,2),['생산팀','공정']);
    assert.ok(state.annualTotals>0);
    await page.screenshot({path:resolve(output,`dashboard-${width}.png`),format:'png'});
    await page.eval(()=>document.querySelector('.team-annual-table').scrollIntoView({block:'center'}));
    await page.screenshot({path:resolve(output,`annual-${width}.png`),format:'png'});
    checks.push({width,...state,passed:true});
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,passed:true}));
}finally{await browser.close();}
