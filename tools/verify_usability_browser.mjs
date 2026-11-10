import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const root=resolve('.'),out=join(root,'reports/ui_usability/20261110-corrections');mkdirSync(out,{recursive:true});
const generated=spawnSync(join(root,'.venv/Scripts/python.exe'),['-c',String.raw`
import sys,re
from pathlib import Path
sys.path.insert(0,str(Path.cwd().parent))
from iris2.tests.test_ui_usability import UiTemplateTests
t=UiTemplateTests();t.setUpClass()
pages={'dashboard':t.dashboard_fixture(),'precision':t.precision_fixture(),'precision-loaded':t.loaded_precision_fixture(),'login':t.render('login.html',endpoint='login',next_path='/')}
pages.update({name:t.forecast_fixture(template) for name,template in [('forecast','remaining_life_simulation.html'),('detail','exchanger_detail.html'),('qr','qr_exchanger_lookup.html'),('report','exchanger_report.html')]})
for name,html in pages.items():
    html=re.sub(r'(["\'])/static/([^"\'?]+)(?:\?[^"\']*)?\1',lambda m:m[1]+(Path.cwd()/'static'/m[2]).as_uri()+m[1],html)
    (Path('reports/ui_usability/20261110-corrections')/(name+'.html')).write_text(html,encoding='utf-8')
`],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
if(generated.status!==0)throw new Error(generated.stderr);
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try {
 const page=await browser.newPage({width:1440,height:1000});
 for(const name of ['dashboard','precision','precision-loaded','login','forecast','detail','qr','report']){
  await page.goto(pathToFileURL(join(out,name+'.html')).href);
  for(const width of [1440,768,390]){
   await page.setViewport({width,height:1000});
   await new Promise(r=>setTimeout(r,100));
   const dims=await page.eval(()=>({viewport:innerWidth,page:document.documentElement.scrollWidth}));
   assert.ok(dims.page<=dims.viewport+1,`${name} overflow at ${width}: ${JSON.stringify(dims)}`);
   if(name!=='login' && name!=='qr'){
    const collapsed=await page.eval(()=>document.querySelector('.app-shell').classList.contains('sidebar-collapsed'));
    const mode=await page.eval(()=>document.querySelector('.app-shell').dataset.sidebarMode);
    assert.equal(collapsed,mode==='collapsed' || (mode==='auto' && width<=1100),`${name} entry state at ${width}`);
   }
   if(['forecast','detail','qr','report'].includes(name)){
    const contents=await page.eval(()=>document.body.textContent);
    assert.ok(contents.includes('5/52개, 9.6%'));
    assert.ok(contents.includes('5/5개, 100.0%'));
    assert.ok(contents.includes('가용 데이터에서 한도 미도달'));
    assert.ok(!contents.includes('예측기간 내 미도달'));
    assert.ok(contents.includes('예측 가능한 등록 튜브 중 향후 추가 도달 대상 0개이며, 미등록 47개는 평가에서 제외됩니다.'));
    assert.ok(contents.includes('2020-10-24'));
    assert.ok(contents.includes('2026-11-10'));
    if(name==='detail')assert.equal(await page.eval(()=>[...document.querySelectorAll('td')].filter(td=>td.textContent==='최근 검사에서 기준 도달 확인 — 실제 도달일 미상').length),5);
   }
   if(name==='dashboard'){
    const grid=await page.eval(()=>[...document.querySelectorAll('.life-band-table tr')].map(tr=>[...tr.cells].map(cell=>({x:cell.getBoundingClientRect().x,w:cell.getBoundingClientRect().width,align:getComputedStyle(cell).textAlign}))));
    assert.equal(grid[0].length,7);
    for(const row of grid)for(let i=0;i<row.length;i++){
     assert.ok(Math.abs(row[i].x-grid[0][i].x)<1);
     assert.ok(Math.abs(row[i].w-grid[0][0].w)<1);
     assert.equal(row[i].align,'center');
    }
    assert.equal(await page.eval(()=>!!document.querySelector('[data-qr-scan-open],#missing-tube-count-panel')),false);
   }
   if(name.startsWith('precision') && width<=1100){
    assert.equal(await page.eval(()=>document.querySelector('.analysis-equipment-panel').open),false);
    assert.ok(await page.eval(()=>document.querySelector('.analysis-equipment-panel').getBoundingClientRect().height<90),'Collapsed equipment picker must not occupy an empty panel');
    await page.eval(()=>document.querySelector('.sidebar-toggle').click());
    const menu=await page.eval(()=>{const s=document.querySelector('#app-sidebar'),r=s.getBoundingClientRect();return {position:getComputedStyle(s).position,width:r.width,mainTop:document.querySelector('main').getBoundingClientRect().top};});
    assert.equal(menu.position,'fixed');assert.ok(menu.width<width);
    await page.eval(()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})));
    assert.equal(await page.eval(()=>document.querySelector('.app-shell').classList.contains('sidebar-collapsed')),true);
   }
   if(name==='precision-loaded'){
    const metrics=await page.eval(()=>Object.fromEntries([...document.querySelectorAll('#remaining-life-analysis .analysis-metric')].map(node=>[node.querySelector('span').textContent,node.querySelector('b').textContent])));
    assert.equal(metrics['실제 Plugging 완료 수량'],'0개');
    assert.equal(metrics['Plugging 기준 도달 대상 수량'],'1개');
    assert.equal(metrics['향후 Plugging 예상 수량'],'0개');
    assert.equal(metrics['열교환기 예상 잔여수명'],'가용 데이터에서 한도 미도달');
    assert.equal(metrics['선택 Tube 예상'],'최근 검사에서 기준 도달 확인 — 실제 도달일 미상');
    assert.ok(await page.eval(()=>document.querySelector('.prediction-coverage').textContent.includes('5/52개, 9.6%')));
    assert.ok(await page.eval(()=>document.getElementById('remaining-life-scope-note').textContent.includes('미등록 47개는 평가에서 제외됩니다.')));
    assert.ok(await page.eval(()=>document.querySelector('.precision-tube')));
    assert.ok(await page.eval(()=>document.querySelector('.analysis-selection-status').textContent.includes('E-131D')));
    const contrast=await page.eval(()=>{
      const node=document.querySelector('.analysis-selection-status'),s=getComputedStyle(node);
      const luminance=color=>{const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
      const a=luminance(s.color),b=luminance(s.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    });
    assert.ok(contrast>=4.5,`Selection label contrast ${contrast}`);
   }
   await page.screenshot({path:join(out,`${name}-${width}.png`),format:'png',fullPage:false});
   if(name==='detail'){
    await page.eval(()=>document.querySelector('.life-tables section:last-child').scrollIntoView());
    await page.screenshot({path:join(out,`detail-dates-${width}.png`),format:'png',fullPage:false});
    await page.eval(()=>scrollTo(0,0));
   }
   checks.push(`${name} ${width}: no overflow${name==='dashboard'?', equal life-band boundaries and centered values':''}`);
  }
 }
 writeFileSync(join(out,'validation.json'),JSON.stringify({fixture_only:true,checks,passed:true},null,2));
 console.log(JSON.stringify({passed:true,checks}));
}finally{await browser.close();}
