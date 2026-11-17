// Prepare an authorized local session in tmp/text_sql_fluid_browser_cookie.json first.
import assert from 'node:assert/strict';
import {readFileSync, unlinkSync, writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const file='tmp/text_sql_fluid_browser_cookie.json';
const cookie=JSON.parse(readFileSync(file,'utf8')); unlinkSync(file);
const browser=await Browser.launch(), checks=[];
async function waitFor(page, fn) {
  const deadline=Date.now()+15000;
  while (!(await page.eval(fn))) {
    if(Date.now()>deadline) throw new Error('Timed out waiting for query');
    await new Promise(resolve=>setTimeout(resolve,100));
  }
}
try {
  const page=await browser.newPage({width:1440,height:900});
  await page.send('Network.enable');
  await page.send('Network.setCookie',{...cookie,url:'http://127.0.0.1:4824',httpOnly:true,sameSite:'Lax'});
  await page.goto('http://127.0.0.1:4824/inspections/text-to-sql');
  for(const width of [1440,768,390]) {
    await page.setViewport({width,height:900});
    await page.eval(()=>{
      const input=document.getElementById('sql-question');
      input.value='공정별 Shell 유체명이 STEAM인 교환기 수량과 목록';
      input.dispatchEvent(new Event('input',{bubbles:true}));
      document.getElementById('sql-question-form').requestSubmit();
    });
    await waitFor(page,()=>!document.getElementById('sql-execute').disabled);
    await page.eval(()=>document.getElementById('sql-execute').click());
    await waitFor(page,()=>!document.getElementById('sql-result-table').hidden);
    const result=await page.eval(()=>({
      headers:[...document.querySelectorAll('#sql-result-table th')].map(e=>e.textContent),
      rows:[...document.querySelectorAll('#sql-result-table tbody tr')].map(e=>e.textContent),
      cells:[...document.querySelectorAll('#sql-result-table tbody td')].map(e=>e.textContent),
      error:document.getElementById('sql-error').textContent,
      sql:document.getElementById('sql-code').value,
      note:document.getElementById('sql-result-note').textContent,
      viewport:innerWidth,scroll:document.documentElement.scrollWidth
    }));
    assert.equal(result.error,'');
    assert.equal(result.rows.length,1);
    assert.ok(result.cells.includes('STEAM') && result.cells.includes('10') && result.cells.includes('VCM2'));
    assert.ok(result.headers.includes('유체명') && result.headers.includes('열교환기 목록'));
    assert.ok(result.rows[0].includes('US-EV-E-105'));
    assert.ok(result.sql.includes('heat_exchanger_spec_revision'));
    assert.ok(result.note.includes('현재 사양'));
    assert.ok(result.scroll<=result.viewport+1);
    checks.push({width,...result});
    console.log(`PASS ${width}px: fluid grouping, STEAM count/list, SQL execution, no page overflow`);
  }
  writeFileSync('tmp/text_sql_fluid_browser_result.json',JSON.stringify({passed:true,checks},null,2));
} finally { await browser.close(); }
