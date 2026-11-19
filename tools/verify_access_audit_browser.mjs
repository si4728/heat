import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const auth=JSON.parse(await new Promise(resolve=>{
  let data='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>data+=chunk);process.stdin.on('end',()=>resolve(data));
}));
const base='http://127.0.0.1:4824';
const out=resolve('reports/access-audit-20261119');mkdirSync(out,{recursive:true});
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox','--no-proxy-server']});
const result={screens:[]};
try {
  const page=await browser.newPage({width:1440,height:1000});
  await page.send('Network.setCookie',{...auth.cookie,url:base,httpOnly:true,sameSite:'Lax'});
  await page.goto(base+'/settings/access-logs');
  await page.goto(base+'/settings/access-logs?event=ACCESS&result=ALLOWED&path=%2Fsettings%2Faccess-logs');
  for(const width of [1440,768,390]) {
    await page.setViewport({width,height:1000});
    const state=await page.eval(()=>{
      const sidebar=document.querySelector('.sidebar-toggle');
      if(innerWidth<1100 && sidebar?.getAttribute('aria-expanded')==='true')sidebar.click();
      const details=document.querySelector('.access-log-results tbody details');
      if(details){details.open=true;details.open=false;}
      return {width:innerWidth,title:document.querySelector('h1')?.textContent,
        rows:document.querySelectorAll('.access-log-results tbody tr').length,
        filter:document.querySelector('[name=event]').value,
        result:document.querySelector('[name=result]').value,
        overflow:document.documentElement.scrollWidth>innerWidth,
        menu:!!document.querySelector('.administrator-settings-links a[href="/settings/access-logs"]'),
        failureWarning:!!document.querySelector('.access-log-workspace [role=alert]')};
    });
    assert.equal(state.title,'로그온·화면 접근 이력');assert.equal(state.overflow,false);
    assert.equal(state.filter,'ACCESS');assert.equal(state.result,'ALLOWED');assert.ok(state.menu);
    assert.equal(state.failureWarning,false);
    await page.screenshot({path:resolve(out,`audit-${width}.png`),format:'png',fullPage:true});
    result.screens.push(state);
  }
  const exportState=await page.eval(async()=>{
    const response=await fetch('/settings/access-logs/export.csv?event=ACCESS');
    const bytes=new Uint8Array(await response.arrayBuffer());
    return {status:response.status,recorded:response.headers.get('X-Audit-Recorded'),
      cache:response.headers.get('Cache-Control'),bom:[...bytes.slice(0,3)],
      type:response.headers.get('Content-Type'),truncated:response.headers.get('X-Export-Truncated')};
  });
  assert.equal(exportState.status,200);assert.equal(exportState.recorded,'1');
  assert.equal(exportState.cache,'no-store');assert.deepEqual(exportState.bom,[239,187,191]);
  result.csv=exportState;
  const invalid=await page.eval(async()=>{
    const r=await fetch('/settings/access-logs?start=invalid');
    return {status:r.status,recorded:r.headers.get('X-Audit-Recorded')};
  });
  assert.equal(invalid.status,400);assert.equal(invalid.recorded,'1');result.invalidFilter=invalid;
  await page.send('Network.deleteCookies',{name:auth.cookie.name,url:base});
  await page.goto(base+'/settings/access-logs');
  result.anonymousRedirect=await page.eval(()=>location.pathname==='/login');
  assert.ok(result.anonymousRedirect);
  assert.equal(page.consoleErrors.length,0);
  writeFileSync(resolve(out,'browser-validation.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
} finally {await browser.close();}
