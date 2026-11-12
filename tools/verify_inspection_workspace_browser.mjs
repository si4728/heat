// Operates on saved read-only page snapshots; never submits a plan.
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {readFileSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const output=resolve('reports/inspection-workspace-20261112');
const fixture=JSON.parse(readFileSync(resolve(output,'tubes.json'),'utf8'));
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try {
  const page=await browser.newPage({width:1440,height:1000});
  for(const name of ['yearly','process','plans']) {
    for(const width of [1440,768,390]) {
      await page.setViewport({width,height:1000});
      await page.goto(pathToFileURL(resolve(output,`${name}.html`)).href);
      if(width<1100) await page.eval(()=>{
        const toggle=document.querySelector('.sidebar-toggle');
        if(toggle?.getAttribute('aria-expanded')==='true') toggle.click();
      });
      const state=await page.eval(()=>({overflow:document.documentElement.scrollWidth>innerWidth,
        filterHeight:document.querySelector('.inspection-workspace-filters').getBoundingClientRect().height,
        rows:document.querySelector('article.panel tbody')?.rows.length||0,
        title:document.querySelector('h1').textContent}));
      assert.equal(state.overflow,false,`${name} ${width}: page overflow`);
      if(width===390) assert.ok(state.filterHeight<350,`${name}: filters push data out of view`);
      assert.ok(state.rows>0);
      await page.screenshot({path:resolve(output,`${name}-${width}.png`),format:'png'});
      if(name==='plans') {
        await page.eval((data)=>{
          const original=window.fetch;
          window.fetch=async (url,options)=>String(url).includes(`/recommended/${data.heat_exchanger_id}/tubes`)?
            new Response(JSON.stringify({tubes:data.tubes}),{status:200,headers:{'content-type':'application/json'}}):original(url,options);
          document.querySelector('.recommendation-register').open=true;
        },fixture);
        for(let attempt=0;attempt<40;attempt++) {
          if(await page.eval(()=>document.querySelector('.recommendation-register select').options.length>0)) break;
          await new Promise(r=>setTimeout(r,50));
        }
        const formState=await page.eval(()=>{
          const details=document.querySelector('.recommendation-register');
          const select=details.querySelector('select');
          const before=details.querySelector('[type=submit]').disabled;
          select.options[0].selected=true;
          select.dispatchEvent(new Event('change'));
          const after=details.querySelector('[type=submit]').disabled;
          details.scrollIntoView({block:'center'});
          const wrap=details.closest('.table-wrap');wrap.scrollLeft=wrap.scrollWidth;
          return {options:select.options.length,before,after,valid:details.querySelector('form').checkValidity()};
        });
        assert.ok(formState.options>0);
        assert.equal(formState.before,true);
        assert.equal(formState.after,false);
        assert.equal(formState.valid,true);
        await page.screenshot({path:resolve(output,`register-${width}.png`),format:'png'});
      }
      checks.push({page:name,width,...state,passed:true});
    }
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,inlineRegistration:true,submitted:false,passed:true}));
}finally{await browser.close();}
