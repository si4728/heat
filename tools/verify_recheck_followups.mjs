import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg=JSON.parse(readFileSync(0,'utf8')),checks=[];
const browser=await Browser.launch();
try {
  const page=await browser.newPage({width:1440,height:1050});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{name:'iris2_session',value:cfg.cookie,url:cfg.base,httpOnly:true,sameSite:'Lax'});
  if(['all','dashboard'].includes(cfg.section)){
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
  }
  if(['all','analysis'].includes(cfg.section)){
    await page.setViewport({width:1440,height:1050});
    await page.goto(cfg.base+'/analysis?exchanger_id=100&search=E-111');
    const state=await page.eval(()=>{
      const life=JSON.parse(document.getElementById('precision-life-data').textContent);
      return {sidebar:document.querySelector('.analysis-equipment-item.active em').textContent.trim(),
        maximum:Math.max(...life.analysis_tube_rows.filter(r=>r.wall_loss_percent!==null).map(r=>r.wall_loss_percent)),
        hasPartial:life.analysis_tube_rows.some(r=>r.inspection_id===87)};
    });
    assert.equal(state.sidebar,'27.44%');assert.equal(state.maximum,27.44);assert.equal(state.hasPartial,false);
    checks.push({issue:'R5',...state});
    for(const width of [1440,768,390]){
      await page.setViewport({width,height:1050});
      await page.eval(()=>{
        const toggle=document.querySelector('.sidebar-toggle');
        if(innerWidth<1100&&toggle?.getAttribute('aria-expanded')==='true')toggle.click();
        document.querySelector('.analysis-equipment-panel').open=true;
        document.querySelector('.analysis-equipment-panel').scrollIntoView({block:'start'});
      });
      assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:cfg.out+'/analysis-'+width+'.png',format:'png'});
    }
  }
  if(['all','thickness'].includes(cfg.section)){
    assert.ok(cfg.thickness_id);
    await page.setViewport({width:1440,height:1050});
    await page.goto(cfg.base+'/analysis?exchanger_id='+cfg.thickness_id+'&search=E-122A');
    const end=Date.now()+15000;
    while(!await page.eval(()=>!!document.querySelector('[data-analysis-tube]'))){
      if(Date.now()>end)throw new Error('Thickness measurement rows did not render');
      await new Promise(r=>setTimeout(r,150));
    }
    const state=await page.eval(()=>{
      const life=JSON.parse(document.getElementById('precision-life-data').textContent);
      const target=life.analysis_tube_rows.find(r=>r.minimum_wall_thickness_mm===null);
      if(!target)throw new Error('Missing-thickness fixture not found');
      document.querySelector('[data-analysis-tube="'+target.tube_id+'"]').click();
      const fields=Object.fromEntries([...document.querySelectorAll('#corrosion-analysis table tr')]
        .map(tr=>[tr.querySelector('th').textContent,tr.querySelector('b').textContent]));
      return {fields,note:document.getElementById('selected-thickness-basis').textContent,
        hasCurrentMeasuredPoint:window.TubeThicknessTrend.series(life.tube_histories[String(target.tube_id)] || [])
          .some(point=>point.date===target.measurement_date),
        rawThickness:target.minimum_wall_thickness_mm};
    });
    assert.equal(state.rawThickness,null);
    assert.equal(state.fields['실측 최소두께 (mm)'],'미등록');
    assert.equal(state.fields['공칭두께 (참고, mm)'],'2.770');
    assert.ok(state.note.includes('NDD')&&state.note.includes('이전 검사값으로 대체하지 않습니다'));
    assert.equal(state.hasCurrentMeasuredPoint,false);
    checks.push({issue:'missing-thickness',...state});
    for(const width of [1440,768,390]){
      await page.setViewport({width,height:1050});
      await page.eval(()=>{
        const toggle=document.querySelector('.sidebar-toggle');
        if(innerWidth<1100&&toggle?.getAttribute('aria-expanded')==='true')toggle.click();
        document.querySelector('#corrosion-analysis').scrollIntoView({block:'start'});
      });
      assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:cfg.out+'/thickness-'+width+'.png',format:'png'});
    }
  }
  writeFileSync(cfg.out+'/checks-'+cfg.section+'.json',JSON.stringify({passed:true,checks},null,2));
  console.log(JSON.stringify({passed:true,checks}));
}catch(error){writeFileSync(cfg.out+'/failure.txt',String(error.stack||error));throw error;}
finally{await browser.close();}
