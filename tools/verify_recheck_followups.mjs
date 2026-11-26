import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[];
const browser=await Browser.launch();
try {
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  await page.goto(cfg.base+'/');
  const groups=await page.eval(()=>[...document.querySelectorAll('.life-band-table tbody tr:not(.life-band-total)')].map(tr=>({
    team:tr.querySelector('th').textContent.split(' ')[0],
    links:[...tr.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),count:parseInt(a.textContent)}))
  })));
  assert.deepEqual(groups.map(g=>g.team).sort(),['PE','VCM']);
  for(const group of groups){
    assert.ok(group.links.every(link=>new URL(link.href,cfg.base).searchParams.get('life_team')===group.team));
    for(const index of [2,group.links.length-1]){
      const link=group.links[index];
      await page.goto(new URL(link.href,cfg.base).href);
      const state=await page.eval(()=>({open:document.querySelector('#remaining-life-list').open,
        summary:document.querySelector('#remaining-life-list summary').textContent,
        teams:[...document.querySelectorAll('#remaining-life-list tbody tr')].filter(tr=>tr.querySelector('a')).map(tr=>tr.cells[0].textContent.trim())}));
      assert.equal(state.open,true);
      assert.equal(state.teams.length,link.count);
      assert.ok(state.teams.every(team=>team===group.team+' 생산팀'));
      assert.ok(state.summary.includes(group.team+' 생산팀'));
      checks.push({team:group.team,link:link.href,count:state.teams.length});
    }
  }
  await page.goto(cfg.base+'/?life_team=PE&life_band=short#remaining-life-list');
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1050});
    await page.eval(()=>{
      const toggle=document.querySelector('.sidebar-toggle');
      if(innerWidth<1100&&toggle?.getAttribute('aria-expanded')==='true')toggle.click();
      document.querySelector('#remaining-life-dashboard').scrollIntoView({block:'start'});
    });
    assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:cfg.out+'/dashboard-'+width+'.png',format:'png'});
  }
  writeFileSync(cfg.out+'/checks.json',JSON.stringify({passed:true,checks},null,2));
  console.log(JSON.stringify({passed:true,checks}));
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
