import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const output=resolve('reports/menu-cleanup-20261112');
const browser=await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox']});
const checks=[];
try{
  const page=await browser.newPage({width:1440,height:1000});
  for(const name of ['dashboard','exchangers','analysis','ordinary']){
    for(const width of [1440,768,390]){
      await page.setViewport({width,height:1000});
      await page.goto(pathToFileURL(resolve(output,`${name}.html`)).href);
      const state=await page.eval(()=>{
        const toggle=document.querySelector('.sidebar-toggle');
        if(innerWidth<1100 && toggle?.getAttribute('aria-expanded')==='true')toggle.click();
        const nav=document.querySelector('#general-navigation');
        const settings=document.querySelector('#administrator-settings');
        let bounds=null,escaped=null,outsideClosed=null;
        if(settings){
          settings.querySelector('summary').click();
          const rect=settings.querySelector('nav').getBoundingClientRect();
          bounds={left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
          escaped=!settings.open;
          settings.open=true;document.querySelector('h1').click();outsideClosed=!settings.open;
          settings.open=true;
        }
        return {overflow:document.documentElement.scrollWidth>innerWidth,
          generalEntries:nav.children.length,labels:[...nav.children].map(el=>el.tagName==='DETAILS'?el.querySelector('summary').textContent:el.textContent),
          admin:!!settings,bounds,escaped,outsideClosed,
          analysisLinks:[...document.querySelectorAll('a.strong-link')].map(a=>a.getAttribute('href'))};
      });
      assert.equal(state.overflow,false,`${name} ${width}`);
      assert.equal(state.generalEntries,5);
      assert.deepEqual(state.labels,['대시보드','열교환기 목록','열교환기 분석','검사 이력','검사계획']);
      assert.equal(state.admin,name!=='ordinary');
      if(state.admin){
        assert.ok(state.bounds.left>=0 && state.bounds.right<=width+1,JSON.stringify({name,width,state}));
        assert.ok(state.bounds.top>=0 && state.bounds.bottom<=1000,JSON.stringify({name,width,state}));
        assert.ok(state.escaped && state.outsideClosed);
      }
      if(name==='exchangers'||name==='ordinary'){
        assert.ok(state.analysisLinks.some(link=>link.startsWith('/analysis?')));
        for(const link of state.analysisLinks){
          const unit=new URLSearchParams(link.split('?')[1]).get('unit');
          assert.equal(link.startsWith('/analysis?'),['VCM1','VCM2'].includes(unit));
        }
      }
      await page.screenshot({path:resolve(output,`${name}-${width}.png`),format:'png'});
      checks.push({page:name,width,...state,passed:true});
    }
  }
  writeFileSync(resolve(output,'browser-validation.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({checks:checks.length,passed:true}));
}finally{await browser.close();}
