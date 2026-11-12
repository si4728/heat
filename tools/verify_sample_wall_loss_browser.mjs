// Inspect the authenticated, read-only HTML snapshots made by verify_sample_wall_loss_live.py --web.
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const output=resolve('reports/sample-wall-loss-20261112');
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try {
  const page=await browser.newPage({width:1440,height:1000});
  for(const name of ['precision','detail','insufficient']) {
    for(const width of [1440,768,390]) {
      await page.setViewport({width,height:1000});
      await page.goto(pathToFileURL(resolve(output,`${name}.html`)).href);
      // Detail pages intentionally open the navigation; close its overlay for inspection.
      if(width<1100) await page.eval(()=>{
        const toggle=document.querySelector('.sidebar-toggle');
        if(toggle?.getAttribute('aria-expanded')==='true') toggle.click();
      });
      await page.eval(()=>{
        document.querySelector('.sample-wall-loss').scrollIntoView({block:'start'});
      });
      const state=await page.eval(()=>{
        const panel=document.querySelector('.sample-wall-loss');
        return {pageOverflow:document.documentElement.scrollWidth>innerWidth,
          panelOverflow:panel.scrollWidth>panel.clientWidth+1,
          text:panel.textContent, rows:panel.querySelectorAll('tbody tr').length};
      });
      assert.equal(state.pageOverflow,false,`${name} ${width}: page overflow`);
      assert.equal(state.panelOverflow,false,`${name} ${width}: panel overflow`);
      assert.equal(state.rows,3);
      if(name==='insufficient') {
        assert.ok(state.text.includes('표본 부족'));
        assert.ok(state.text.includes('기존 실측 튜브별 잔여수명 계산을 유지'));
      }else{
        for(const expected of ['23.2%','31.7%','21.7%','2026년','2032년','최초 Plugging 기준 도달','Plugging 20% 도달'])
          assert.ok(state.text.includes(expected),expected);
      }
      await page.screenshot({path:resolve(output,`${name}-${width}.png`),format:'png'});
      await page.eval(()=>{
        const panel=document.querySelector('.sample-wall-loss');
        const wrap=panel.querySelector('.table-wrap');
        wrap.scrollLeft=wrap.scrollWidth;
        panel.querySelector('table').scrollIntoView({block:'center'});
      });
      await page.screenshot({path:resolve(output,`${name}-${width}-dates.png`),format:'png'});
      checks.push({page:name,width,pageOverflow:state.pageOverflow,panelOverflow:state.panelOverflow,passed:true});
    }
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,passed:true}));
}finally{await browser.close();}
