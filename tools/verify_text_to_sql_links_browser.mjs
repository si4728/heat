// Rendering fixtures only: no database access or model inference.
import {spawnSync} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const root=resolve('.'), output=join(root,'reports/text_to_sql/links-20261110');
mkdirSync(output,{recursive:true});
const fixture=join(output,'fixture.html');
const rendered=spawnSync(join(root,'.venv/Scripts/python.exe'),['-c',String.raw`
from pathlib import Path
from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader
root=Path.cwd()
base='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Text-to-SQL link verification</title><style>body{font-family:Arial,sans-serif;margin:20px} .sr-only{position:absolute;width:1px;height:1px;overflow:hidden} table{border-collapse:collapse} td,th{padding:12px;border-bottom:1px solid #ddd} .table-wrap{overflow:auto}</style>{% block extra_head %}{% endblock %}<body>{% block content %}{% endblock %}{% block scripts %}{% endblock %}</body></html>'
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':base}),FileSystemLoader(root/'templates')]),autoescape=True)
def url_for(endpoint,**kw):
    if endpoint=='static': return (root/'static'/kw['filename']).as_uri()
    return {'tube_detail':'/tubes/0','exchanger_detail':'/exchangers/0','inspection_detail':'/inspections/0','text_to_sql_inspections':'/inspections/text-to-sql/inspections','text_to_sql_generate':'/inspections/text-to-sql/generate','text_to_sql_execute':'/inspections/text-to-sql/execute'}[endpoint]
print(env.get_template('text_to_sql.html').render(url_for=url_for,csrf_token='fixture',equipment=[],catalog_error=None))
`],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
if(rendered.status!==0)throw new Error(rendered.stderr);
writeFileSync(fixture,rendered.stdout);
const browser=await Browser.launch({extraArgs:['--disable-gpu', '--no-sandbox']});
const checks=[];
try {
  const page=await browser.newPage({width:1440,height:1000});
  await page.goto(pathToFileURL(fixture).href);
  assert.equal(await page.eval(()=>!!window.TextSqlLinks),true);
  await page.eval(()=>{
    window.linkFixture={columns:['heat_exchanger_id','equipment_code','equipment_tag','equipment_name','tube_id','source_tube_id','iris_inspection_id','wall_loss_percent'],rows:[{heat_exchanger_id:151,equipment_code:'E106',equipment_tag:'E-106',equipment_name:'VCM2 exchanger',tube_id:123,source_tube_id:'A-7',iris_inspection_id:389,wall_loss_percent:42.5},{heat_exchanger_id:152,equipment_code:'<img src=x onerror=alert(1)>',equipment_tag:'E-107',equipment_name:'VCM1 exchanger',tube_id:null,source_tube_id:'B-9',iris_inspection_id:null,wall_loss_percent:0}],result_count:2,generated_at:new Date().toISOString()};
    window.fetch=async url=>({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>String(url).endsWith('/generate')?{token:'fixture',proposal:{sql:'SELECT fixture',parameters:[]},query_kind:'inspection_frequency',period:{start:'2021-11-10',end:'2026-11-10',limit:5},equipment_list:[]}:{result:window.linkFixture}});
    const q=document.getElementById('sql-question');q.value='검사를 가장 많이 한 교환기';q.dispatchEvent(new Event('input'));
    document.getElementById('sql-question-form').requestSubmit();
  });
  const wait=async()=>{
    for(let i=0;i<40;i++){if(await page.eval(()=>document.getElementById('text-sql').getAttribute('aria-busy')==='false'))return;await new Promise(r=>setTimeout(r,50));}
    throw new Error('Rendering timeout');
  };
  await wait();
  await page.eval(()=>document.getElementById('sql-execute').click());await wait();
  const actual=await page.eval(()=>[...document.querySelectorAll('#sql-result-table tbody tr')].map(tr=>[...tr.cells].map(td=>({text:td.textContent,href:td.querySelector('a')?.getAttribute('href')||null,target:td.querySelector('a')?.target,rel:td.querySelector('a')?.rel}))));
  assert.equal(actual[0][0].href,'/exchangers/151');
  assert.equal(actual[0][0].text,'E-106');
  assert.equal(actual[1][0].text,'E-107');
  assert.equal(actual[0][5].href,'/tubes/123');
  assert.equal(actual[0][6].href,'/inspections/389');
  assert.equal(actual[1][0].href,'/exchangers/152');
  assert.equal(actual[1][5].href,null);
  assert.equal(actual[0][7].href,null);
  assert.equal(actual[0][5].target,'_blank');
  assert.match(actual[0][5].rel,/noopener/);
  assert.equal(await page.eval(()=>document.querySelectorAll('#sql-result-table img').length),0);
  checks.push('Real template and result renderer: row IDs, printed tube numbers, inspection links, null IDs, aggregates, new tabs and safe text');
  await page.eval(()=>document.querySelector('#sql-result-table a').focus());
  assert.equal(await page.eval(()=>document.activeElement.className),'sql-detail-link');
  checks.push('Keyboard focus');
  for(const width of [1440,768,390]){
    await page.setViewport({width,height:1000});
    await page.eval(()=>document.getElementById('sql-result-panel').scrollIntoView());
    await page.screenshot({path:join(output,`links-${width}.png`),format:'png',fullPage:false});
  }
  // A combined summary shows its scope codes without splitting the aggregate.
  await page.eval(()=>{window.linkFixture={scopes:[{heat_exchanger_id:151,equipment:{equipment_code:'1104476',equipment_tag:'E-106'}},{heat_exchanger_id:152,equipment:{equipment_code:'1104477',equipment_tag:'E-107'}}],columns:['inspected_tubes'],rows:[{inspected_tubes:82}],result_count:1,generated_at:new Date().toISOString()};document.getElementById('sql-execute').click();});
  await wait();
  assert.deepEqual(await page.eval(()=>[...document.querySelectorAll('#sql-result-table tbody a')].map(a=>a.getAttribute('href'))),['/exchangers/151','/exchangers/152']);
  assert.equal(await page.eval(()=>document.querySelector('#sql-result-table tbody tr').cells[1].textContent),'82');
  checks.push('Combined summary keeps aggregate and displays both scope codes');
  await page.eval(()=>{window.linkFixture={heat_exchanger_id:151,equipment:{equipment_code:'1104476',equipment_tag:'E-106'},columns:['inspected_tubes'],rows:[{inspected_tubes:82}],result_count:1,generated_at:new Date().toISOString()};document.getElementById('sql-execute').click();});
  await wait();
  assert.equal(await page.eval(()=>document.querySelector('#sql-result-table tbody a').textContent),'E-106');
  checks.push('Single-equipment summary includes default code');
  writeFileSync(join(output,'validation.json'),JSON.stringify({fixture_only:true,checks,passed:true},null,2));
  console.log(JSON.stringify({passed:true,checks}));
} finally {await browser.close();}
