// Real authenticated MariaDB templates, real Edge; no forms submitted or DB writes.
import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {resolve,join,extname,sep} from 'node:path';
import {createServer} from 'node:http';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const root=resolve('.'),out=join(root,'tmp/review_20261117/ui');mkdirSync(out,{recursive:true});
const generated=spawnSync(join(root,'.venv/Scripts/python.exe'),['-c',String.raw`
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd().parent))
from iris2.app import create_app
from iris2.database import get_engine
from sqlalchemy import text
app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
with get_engine().connect() as c: uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
client=app.test_client()
with client.session_transaction() as s:s.update(user_id=uid,last_activity_at=time.time())
for invalid in ['abc','0','-1']:
 assert client.get('/analysis?exchanger_id='+invalid).status_code==400
for name,url in [('summary','/analysis?exchanger_id=157'),('partial','/analysis?exchanger_id=100'),('long','/analysis?exchanger_id=202'),('empty','/analysis?exchanger_id=106'),('detail','/exchangers/202'),('dashboard','/')]:
 r=client.get(url);assert r.status_code==200,(name,r.status_code)
 html=r.get_data(as_text=True).replace('"/static/','"'+(Path.cwd()/'static').as_uri()+'/')
 Path('tmp/review_20261117/ui/'+name+'.html').write_text(html,encoding='utf-8')
 if name=='summary':Path('tmp/review_20261117/ui/summary-inspect.html').write_text(r.get_data(as_text=True),encoding='utf-8')
print('Rendered six real screens')
`],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
assert.equal(generated.status,0,generated.stderr);
const server=createServer((req,res)=>{
 try {
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const base=pathname.startsWith('/static/')?join(root,'static'):out;
  const tail=pathname.startsWith('/static/')?pathname.slice(8):pathname.startsWith('/screens/')?pathname.slice(9):'';
  const file=resolve(base,tail);
  if(!tail||!file.startsWith(base+sep)||!['.html','.css','.js','.png','.jpg','.svg','.woff2'].includes(extname(file))) {res.writeHead(404);res.end();return;}
  let data=readFileSync(file);
  if(extname(file)==='.html')data=Buffer.from(data.toString('utf8').replaceAll(pathToFileURL(join(root,'static')).href+'/', '/static/'));
  res.writeHead(200,{'content-type':({'.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript'})[extname(file)]||'application/octet-stream'});res.end(data);
 }catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const baseUrl=`http://127.0.0.1:${server.address().port}`;
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try{
 let page=await browser.newPage({width:1440,height:1000});
 const load=async(name,query='')=>{await page.goto(`${baseUrl}/screens/${name}.html${query}`);await new Promise(r=>setTimeout(r,250));};
 await load('summary');
 assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-panel').open),true);
 assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-list').getBoundingClientRect().height>0),true);
 assert.equal(await page.eval(()=>document.getElementById('equipment-summary').hidden),false);
 assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),true);
 assert.equal(await page.eval(()=>document.querySelectorAll('.precision-tube.selected').length),0);
 const tube=await page.eval(()=>Number(document.querySelector('[data-summary-tube]').dataset.summaryTube));
 for(const width of [1440,1024,768,390,360]){
  await page.setViewport({width,height:1000});
  await page.eval(()=>document.getElementById('equipment-summary').scrollIntoView({block:'center'}));
  assert.equal(await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`summary overflow @${width}`);
  assert.equal(await page.eval(()=>document.querySelector('.summary-top-tubes').scrollWidth<=document.querySelector('.summary-top-tubes').clientWidth+1),true,`summary columns clipped @${width}`);
  assert.equal(await page.eval(()=>document.querySelectorAll('.summary-top-tubes tbody tr').length),5);
  await page.screenshot({path:join(out,`summary-${width}.png`),format:'png',fullPage:false});
  await page.eval(()=>document.querySelector('[data-summary-tube]').click());
  assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),false);
  assert.equal(await page.eval(()=>document.getElementById('equipment-summary').hidden),true);
  assert.equal(await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`tube overflow @${width}`);
  await page.eval(()=>document.getElementById('selected-tube-title').scrollIntoView({block:'center'}));
  await page.screenshot({path:join(out,`tube-${width}.png`),format:'png',fullPage:false});
  await page.eval(()=>document.getElementById('show-equipment-summary').click());
 }
 checks.push('Summary and original Tube detail toggle at 1440/1024/768/390/360px without document overflow');
 assert.deepEqual(page.consoleErrors,[]);
 page=await browser.newPage({width:390,height:844,mobile:true});
 await page.send('Page.bringToFront');
 await load('summary');
 await page.eval(()=>document.querySelector('[data-summary-tube]').scrollIntoView({block:'center',behavior:'instant'}));
 await new Promise(r=>setTimeout(r,150));
 const tap=await page.eval(()=>{const r=document.querySelector('[data-summary-tube]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
 assert.equal(await page.eval(({x,y})=>!!document.elementFromPoint(x,y)?.closest('[data-summary-tube]'),tap),true);
 await page.eval(()=>{window.touchTrace=[];for(const type of ['pointerdown','pointerup','touchstart','touchend','click'])document.addEventListener(type,e=>window.touchTrace.push({type,target:e.target.tagName,tube:e.target.closest('[data-summary-tube]')?.dataset.summaryTube}),true);});
 await page.send('Input.synthesizeTapGesture',{...tap,gestureSourceType:'touch',tapCount:1});
 await new Promise(r=>setTimeout(r,700));
 assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),false,JSON.stringify({trace:await page.eval(()=>window.touchTrace),errors:page.consoleErrors,tap}));
 await page.eval(()=>document.getElementById('show-equipment-summary').focus());
 await page.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});
 await page.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
 assert.equal(await page.eval(()=>document.getElementById('equipment-summary').hidden),false);
 assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-panel').open),false);
 await page.eval(()=>document.querySelector('.analysis-equipment-panel>summary').click());
 assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-panel').open),true);
 await page.eval(()=>document.querySelector('.analysis-equipment-panel>summary').click());
 assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-panel').open),false);
 checks.push('Mobile touch selects Tube, keyboard returns to Summary, equipment chooser collapses and reopens');
 await load('summary',`?tube_id=${tube}`);
 assert.equal(await page.eval(()=>document.getElementById('selected-tube-view').hidden),false);
 await page.eval(()=>{const slider=document.getElementById('corrosion-rate-slider');slider.value='2';slider.dispatchEvent(new Event('input'));});
 assert.equal(await page.eval(()=>document.getElementById('corrosion-rate-output').textContent.includes('2')),true);
 await load('summary','?tube_id=99999999');
 assert.equal(await page.eval(()=>document.getElementById('equipment-summary').hidden),false);
 checks.push('Explicit Tube link, invalid Tube link, rate multiplier and return to summary preserve existing controls');
 await load('partial');
 await page.eval(()=>{
  const life=JSON.parse(document.getElementById('precision-life-data').textContent);
  const row=life.analysis_tube_rows.find(r=>r.tube_no==='14-4');
  document.querySelector(`[data-analysis-tube="${row.tube_id}"]`).click();
 });
 assert.match(await page.eval(()=>document.getElementById('thickness-history').textContent),/일부 구간 검사/);
 checks.push('Excluded partial measurement remains visible with exclusion explanation');
 await load('long');
 assert.match(await page.eval(()=>document.querySelector('.sample-estimate-table').textContent),/30년 이상/);
 assert.equal(await page.eval(()=>document.querySelector('.sample-estimate-table').textContent.includes('2163년')),false);
 await load('empty');
 assert.match(await page.eval(()=>document.querySelector('.analysis-no-selection').textContent),/검사 이력 없음/);
 assert.equal(await page.eval(()=>document.getElementById('precision-life-data')),null);
 await load('detail');
 assert.equal(await page.eval(()=>document.querySelector('.exchanger-actions').textContent.includes('QR 간편조회')),false);
 assert.equal(await page.eval(()=>document.body.innerText.includes('단기 CR')),false);
 await load('dashboard');
 assert.match(await page.eval(()=>document.getElementById('remaining-life-list').textContent),/통계 추정/);
 checks.push('30-year display, no-inspection identity, detail labels and dashboard statistical basis');
 for(const name of ['long','empty','detail','dashboard']){
  await load(name);
  for(const width of [1440,768,390]){
   await page.setViewport({width,height:1000});
   assert.equal(await page.eval(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`${name} overflow @${width}`);
   await page.screenshot({path:join(out,`${name}-${width}.png`),format:'png',fullPage:false});
  }
 }
 checks.push('Detail, dashboard, long forecasts and empty screens have no page overflow on desktop/tablet/mobile');
 assert.deepEqual(page.consoleErrors,[]);
 writeFileSync(join(out,'validation.json'),JSON.stringify({passed:true,checks},null,2));
 console.log(JSON.stringify({passed:true,checks}));
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
