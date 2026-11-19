import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {readFileSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const output = resolve('reports/analysis-cleanup-20261119');
const runtime = process.argv.includes('--runtime');
const auth = runtime ? JSON.parse(await new Promise(resolve=>{
  let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>resolve(input));
})) : null;
const base = 'http://127.0.0.1:4824';
const browser = await Browser.launch({extraArgs:['--disable-gpu','--no-sandbox',...(runtime ? ['--no-proxy-server'] : [])]});
const results=[];
try {
  const page=await browser.newPage({width:1440,height:1000});
  if (runtime) await page.send('Network.setCookie',{...auth.cookie,url:base,httpOnly:true,sameSite:'Lax'});
  for (const width of [1440,768,390]) {
    await page.setViewport({width,height:1000});
    await page.goto(runtime ? base+auth.analysis_path : pathToFileURL(resolve(output,'precision.html')).href,{timeoutMs:60000});
    const state=await page.eval(()=>{
      const toggle=document.querySelector('.sidebar-toggle');
      if(innerWidth<1100 && toggle?.getAttribute('aria-expanded')==='true')toggle.click();
      const rows=[...document.querySelectorAll('[data-analysis-tube]')];
      const initial=rows.filter(r=>!r.hidden).length;
      const button=document.querySelector('#toggle-all-tubes');
      button.click();
      const all=rows.every(r=>!r.hidden);
      button.click();
      const target=rows.find(r=>r.hidden && document.querySelector(`.precision-tube[data-tube-id="${r.dataset.analysisTube}"]`));
      document.querySelector(`.precision-tube[data-tube-id="${target.dataset.analysisTube}"]`).click();
      const life=JSON.parse(document.querySelector('#precision-life-data').textContent);
      const expected=life.analysis_tube_rows.find(r=>r.tube_no==='18-13');
      document.querySelector(`[data-analysis-tube="${expected.tube_id}"]`).click();
      const e111Rate=Number(document.querySelector('#applied-corrosion-rate').textContent);
      const shortDashes=life.analysis_tube_rows.filter(r=>r.short_term_corrosion_rate_mm_per_year != null && r.short_term_corrosion_rate_mm_per_year<=0)
        .every(r=>document.querySelector(`[data-analysis-tube="${r.tube_id}"] td:nth-child(5)`).textContent.trim()==='−');
      const fullLabels=rows.every(r=>['추세','단기','장기','산정 불가'].includes(r.cells[7].textContent.trim()));
      const notes=[...document.querySelectorAll('.analysis-workspace .analysis-quality-note')];
      const descriptionsClosed=notes.filter(n=>n.id!=='precision-linked-selection-status').every(n=>n.closest('details') && !n.closest('details').open);
      const chart=document.querySelector('#annual-plugging-chart svg');
      const chartScale=Number(chart.querySelectorAll('text')[1].textContent);
      const limitVisible=chart.textContent.includes(`허용 한도 ${life.allowable_plugging_count}개`);
      const graphNotPinned=[...chart.querySelectorAll('rect')].some(r=>Number(r.getAttribute('height'))>=40);
      const state={width:innerWidth,initial,all,revealed:!target.hidden,
        summary:!document.querySelector('#equipment-summary').hidden,
        selected:!document.querySelector('#selected-tube-view').hidden,
        graph:!!document.querySelector('#thickness-trend svg'),
        history:document.querySelector('#precision-results-panel #thickness-history').children.length > 0,
        closed:!document.querySelector('#corrosion-help-dialog').open,
        overflow:document.documentElement.scrollWidth>innerWidth,
        legend:[...document.querySelectorAll('.wall-loss-legend-entry')].map(n=>n.textContent),
        rate:document.querySelector('#applied-corrosion-rate')?.textContent,
        e111Rate,shortDashes,fullLabels,descriptionsClosed,chartScale,limitVisible,graphNotPinned};
      return state;
    });
    assert.equal(state.initial,10); assert.ok(state.all); assert.ok(state.revealed);
    assert.ok(state.summary); assert.ok(state.selected); assert.ok(state.graph); assert.ok(state.history);
    assert.ok(state.closed); assert.equal(state.overflow,false);
    assert.ok(state.legend.some(t=>t.includes('40% 이상')));
    assert.equal(state.e111Rate,0.0083); assert.ok(state.shortDashes); assert.ok(state.fullLabels);
    assert.ok(state.descriptionsClosed); assert.ok(state.limitVisible); assert.ok(state.graphNotPinned);
    assert.ok(state.chartScale<70);
    await page.screenshot({path:resolve(output,`${runtime ? 'runtime-' : ''}analysis-${width}.png`),format:'png',fullPage:true});
    results.push(state);
  }
  await page.goto(runtime ? base+'/' : pathToFileURL(resolve(output,'dashboard.html')).href,{timeoutMs:60000});
  const dashboard=await page.eval(()=>({
    noMetrics:!document.querySelector('.metrics'),
    teams:[...document.querySelectorAll('.life-band-table tbody tr th')].map(n=>n.textContent),
  }));
  assert.ok(dashboard.noMetrics); assert.ok(dashboard.teams.includes('PE 생산팀'));
  await page.goto(runtime ? base+'/exchangers' : pathToFileURL(resolve(output,'exchangers.html')).href,{timeoutMs:60000});
  const navigation=await page.eval(()=>[...document.querySelectorAll('table tbody tr')].filter(r=>r.cells.length>=5)
    .every(r=>[...r.cells[3].querySelectorAll('a'),...r.cells[4].querySelectorAll('a')].every(a=>a.getAttribute('href').startsWith('/analysis?'))));
  assert.ok(navigation);
  results.push({liveServer:runtime,dashboard,navigation});
  if (!runtime) {
  // Exercise exact threshold boundaries through the real map renderer without DB writes.
  const markup=readFileSync(resolve(output,'precision.html'),'utf8');
  const mapMatch=markup.match(/(<script id="precision-map-data"[^>]*>)([\s\S]*?)(<\/script>)/);
  const map=JSON.parse(mapMatch[2]);
  const sample=map.tubes.filter(t=>t.tube_id != null && t.managed!==false && t.x!=null && t.y!=null).slice(0,4);
  assert.equal(sample.length,4);
  sample.forEach((t,i)=>Object.assign(t,{wall_loss_percent:[39.99,40,70,99][i],category:'NORMAL',current_status:'IN_SERVICE',operational_status:'IN_SERVICE',managed:true}));
  writeFileSync(resolve(output,'precision-color-boundaries.html'),markup.replace(mapMatch[0],mapMatch[1]+JSON.stringify(map)+mapMatch[3]));
  await page.goto(pathToFileURL(resolve(output,'precision-color-boundaries.html')).href);
  const colors=await page.eval(ids=>ids.map(id=>document.querySelector(`.precision-tube[data-tube-id="${id}"]`).style.backgroundColor),sample.map(t=>t.tube_id));
  assert.notEqual(colors[0],colors[1]);
  assert.equal(colors[1],colors[2]); assert.equal(colors[2],colors[3]);
  results.push({dashboard,navigation,colorBoundaryValues:[39.99,40,70,99],colors});
  }
  writeFileSync(resolve(output,runtime ? 'runtime-browser-validation.json' : 'browser-validation.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
} finally {await browser.close();}
