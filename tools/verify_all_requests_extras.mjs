import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[];
const browser=await Browser.launch();
async function until(page,fn,ms=45000){const end=Date.now()+ms;while(!await page.eval(fn)){if(Date.now()>end)throw new Error('Full browser audit timeout');await new Promise(r=>setTimeout(r,120));}}
async function init(page){
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  await page.send('Page.addScriptToEvaluateOnNewDocument',{source:`const originalFetch=window.fetch;window.fetch=async(...args)=>{const response=await originalFetch(...args);const path=String(args[0]);if(path.endsWith('/generate'))window.auditPreview=await response.clone().json();if(path.endsWith('/execute'))window.auditResult=(await response.clone().json()).result;return response;};`});
}
async function query(page,question,execute=true){
  await page.goto(cfg.base+'/inspections/text-to-sql');
  await page.eval(q=>{const input=document.getElementById('sql-question');input.value=q;input.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('sql-question-form').requestSubmit();},question);
  await until(page,()=>!!window.auditPreview);
  if(execute){await until(page,()=>!document.getElementById('sql-execute').disabled);await page.eval(()=>document.getElementById('sql-execute').click());await until(page,()=>!!window.auditResult);}
}
try{
  const page=await browser.newPage({width:1440,height:1050});await init(page);
  await query(page,'E-106 열교환기 잔여수명과 차기 검사 권고일');
  await until(page,()=>document.getElementById('sql-commentary-status').textContent.includes('대기'));
  const queued=await page.eval(()=>({message:document.getElementById('sql-commentary-status').textContent,rows:window.auditResult.rows.length}));
  assert.ok(queued.message.includes('3'));assert.equal(queued.rows,1);
  await page.screenshot({path:cfg.out+'/queue-waiting.png',format:'png',fullPage:true});
  const other=await browser.newPage({width:1440,height:1050});await init(other);
  await query(other,'E-106 열교환기 잔여수명과 차기 검사 권고일');
  await until(other,()=>document.getElementById('sql-commentary-status').textContent.includes('나중에'));
  const overflow=await other.eval(()=>({message:document.getElementById('sql-commentary-status').textContent,rows:window.auditResult.rows.length}));
  assert.equal(overflow.rows,1);assert.ok(overflow.message.includes('3'));
  for(const width of [1440,768,390]){
    await other.setViewport({width,height:1050});
    assert.equal(await other.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
    await other.screenshot({path:cfg.out+'/queue-full-'+width+'.png',format:'png',fullPage:true});
  }
  writeFileSync(cfg.gate_file,'release');
  await until(page,()=>document.getElementById('sql-commentary-status').textContent==='로컬 LLM 종합 의견');
  checks.push({name:'queue messages and overflow preserve results',queued,overflow,automaticContinuation:true,model:'TEST_STUB; real FIFO and HTTP'});
  for(const question of ['VCM1 E-111 IRIS 검사 보고서 PDF 보여줘','VCM2 E-106 IRIS 검사 보고서 PDF 보여줘','PE E-331B IRIS 검사 보고서 PDF 보여줘']){
    await query(page,question,false);
    await until(page,()=>!document.getElementById('sql-help-panel').hidden);
    const reports=await page.eval(()=>({kind:window.auditPreview.query_kind,reports:window.auditPreview.reports,
      links:[...document.querySelectorAll('#sql-help-examples a')].map(a=>({href:a.getAttribute('href'),target:a.target})),
      executeDisabled:document.getElementById('sql-execute').disabled}));
    assert.equal(reports.kind,'inspection_reports');assert.ok(reports.links.length>0);assert.ok(reports.executeDisabled);
    assert.ok(reports.links.every(a=>a.target==='_blank'&&/^\/inspections\/\d+\/pdf/.test(a.href)));
    const pdf=await page.eval(async href=>{const r=await fetch(href,{headers:{Range:'bytes=0-4'}});const bytes=await r.arrayBuffer();return {status:r.status,type:r.headers.get('content-type'),magic:new TextDecoder().decode(bytes.slice(0,5))};},reports.links[0].href);
    assert.ok([200,206].includes(pdf.status));assert.equal(pdf.type,'application/pdf');assert.equal(pdf.magic,'%PDF-');
    checks.push({question,reports:reports.links.length,pdf});
    await page.screenshot({path:cfg.out+'/pdf-'+question.split(' ')[0]+'.png',format:'png',fullPage:true});
  }
  for(const question of ['유체명이 STEAM 인 열교환기 목록','공정별 유체명별 열교환기 목록']){
    await query(page,question);
    const result=await page.eval(()=>window.auditResult);
    assert.equal(result.query_kind,'fluid_grouping');assert.ok(result.rows.length>0);
    if(question.includes('STEAM'))assert.ok(result.rows.every(r=>r.fluid_name==='STEAM'));
    checks.push({question,rows:result.rows.length,columns:result.columns});
    await page.screenshot({path:cfg.out+'/fluid-'+(question.includes('STEAM')?'steam':'grouping')+'.png',format:'png',fullPage:true});
  }
  for(const [question,expected] of [['IRIS 미실시 열교환기를 보여줘',285],['산정 불가 열교환기를 보여줘',29],['감육률 30% 이상인 튜브가 있는 열교환기를 보여줘',null],['예상 잔여수명이 5년 이하인 열교환기를 보여줘',14]]){
    await query(page,question);
    const result=await page.eval(()=>window.auditResult);
    assert.equal(result.query_kind,'equipment_analysis');
    assert.equal(new Set(result.rows.map(r=>r.heat_exchanger_id)).size,result.rows.length);
    assert.ok(!result.columns.some(c=>/_id$/.test(c)));
    assert.ok(['team_code','unit_code','exchanger_code','equipment_name','latest_inspection_date'].every(c=>result.columns.includes(c)));
    if(expected!==null)assert.equal(result.matched_count,expected);
    if(question.includes('30%'))assert.ok(result.rows.every(r=>r.matching_tube_count>0&&r.maximum_loss>=30));
    checks.push({question,matched:result.matched_count,shown:result.rows.length,oneRowPerEquipment:true});
    await page.screenshot({path:cfg.out+'/equipment-'+checks.length+'.png',format:'png',fullPage:true});
  }
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks},null,2));
  console.log('PASS: queue UI, PDF in three processes, Steam/grouping, state/threshold/remaining filters.');
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{writeFileSync(cfg.gate_file,'release');await browser.close();}
