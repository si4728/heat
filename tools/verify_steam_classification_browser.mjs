import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[],browser=await Browser.launch();
async function until(page,fn){const end=Date.now()+20000;while(!await page.eval(fn)){if(Date.now()>end)throw new Error('Steam browser timeout');await new Promise(r=>setTimeout(r,120));}}
try{
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  await page.send('Page.addScriptToEvaluateOnNewDocument',{source:`const originalFetch=window.fetch;window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0]).endsWith('/execute'))window.steamResult=(await response.clone().json()).result;return response;};`});
  let plain;
  for(const question of ['유체명이 STEAM인 열교환기 목록','유체명이 S:STEAM인 열교환기 목록','공정별 유체명별 열교환기 목록']){
    await page.goto(cfg.base+'/inspections/text-to-sql');
    await page.eval(q=>{const input=document.getElementById('sql-question');input.value=q;input.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('sql-question-form').requestSubmit();},question);
    await until(page,()=>!document.getElementById('sql-execute').disabled);
    await page.eval(()=>document.getElementById('sql-execute').click());
    await until(page,()=>!!window.steamResult&&document.querySelectorAll('#sql-result-table tbody tr').length===window.steamResult.rows.length);
    const result=await page.eval(()=>window.steamResult);
    assert.equal(result.query_kind,'fluid_grouping');
    if(question.includes('명이 ')){
      assert.ok(result.rows.every(r=>r.fluid_name==='STEAM'));
      assert.deepEqual(Object.fromEntries(result.rows.map(r=>[r.side_code,r.exchanger_count])),{SHELL:37,TUBE:2});
      if(plain)assert.deepEqual(result.rows,plain);else plain=result.rows;
    }else{
      assert.ok(!result.rows.some(r=>r.fluid_name==='S:STEAM'));
      assert.equal(result.rows.find(r=>r.unit_code==='VCM1'&&r.side_code==='SHELL'&&r.fluid_name==='STEAM').exchanger_count,22);
    }
    assert.ok(await page.eval(()=>document.getElementById('sql-result-note').textContent.includes('S:STEAM은 STEAM으로 분류')));
    checks.push({question,rows:result.rows.length,counts:result.rows.filter(r=>r.fluid_name==='STEAM')});
    for(const width of [1440,768,390]){
      await page.setViewport({width,height:1050});
      await page.eval(()=>document.getElementById('sql-result-table').scrollIntoView({block:'start'}));
      assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:cfg.out+'/query-'+checks.length+'-'+width+'.png',format:'png'});
    }
  }
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks},null,2));
  console.log('PASS: Steam alias/filter/grouping, totals and classification note at three widths.');
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
