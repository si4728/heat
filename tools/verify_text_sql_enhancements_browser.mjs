import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8'));
const browser=await Browser.launch();
const wait=async(fn)=>{const until=Date.now()+20000;while(!await fn()){if(Date.now()>until)throw Error('UI timeout');await new Promise(r=>setTimeout(r,100));}};
try {
 const page=await browser.newPage({width:1440,height:1050});
 await page.send('Network.enable');
 await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
 await page.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:cfg.out});
 await page.goto(cfg.base+'/inspections/text-to-sql');
 writeFileSync(cfg.out+'/initial.html',await page.eval(()=>document.documentElement.outerHTML));
 await page.screenshot({path:cfg.out+'/initial.png',format:'png',fullPage:true});
 const questions=['VCM1에서 Tube 재질이 Cu-Ni이고 최대 감육률 30% 이상이며 잔여수명 5년 이하인 열교환기 목록','Shell 유체명이 STEAM인 열교환기 목록'];
 for(const [index,question] of questions.entries()) {
  await page.eval(q=>{const el=document.getElementById('sql-question');el.value=q;el.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('sql-question-form').requestSubmit();},question);
  await wait(()=>page.eval(()=>!document.getElementById('sql-execute').disabled));
  const interpretation=await page.eval(()=>document.getElementById('sql-interpretation').textContent);
  assert.ok(index===0 ? interpretation.includes('잔여수명 5.0년 이하')&&interpretation.includes('감육률 30.0% 이상') : interpretation.includes('설비별 1행')&&interpretation.includes('STEAM'));
  await page.eval(()=>document.getElementById('sql-execute').click());
  await wait(()=>page.eval(()=>!document.getElementById('sql-export').disabled));
  const href=await page.eval(()=>document.querySelector('#sql-result-table tbody a')?.getAttribute('href'));
  assert.match(href,/exchanger_id=1/);
  for(const width of [1440,768,390]) {
   await page.setViewport({width,height:1050});
   assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.screenshot({path:cfg.out+`/result-${index}-${width}.png`,format:'png',fullPage:true});
  }
 }
 await page.eval(()=>document.getElementById('sql-export').click());
 await wait(()=>existsSync(cfg.out+'/text-to-sql.xlsx'));
 await page.eval(()=>{const q=document.getElementById('sql-question');q.value='새 질문';q.dispatchEvent(new Event('input',{bubbles:true}));});
 assert.equal(await page.eval(()=>document.getElementById('sql-export').disabled),true);
 writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,fixtureData:true,liveDatabase:false,widths:[1440,768,390],checks:['compound interpretation','fluid equipment rows','analysis links','Excel download','stale export reset']},null,2));
 console.log('PASS: compound preview, fluid rows/links, Excel download, reset and three viewport widths (fixture data).');
} finally {await browser.close();}
