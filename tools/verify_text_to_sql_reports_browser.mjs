// Prepare an authorized local session in tmp/text_sql_pdf_browser_cookie.json first.
import assert from 'node:assert/strict';
import {readFileSync, unlinkSync, writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const sessionFile = 'tmp/text_sql_pdf_browser_cookie.json';
const cookie = JSON.parse(readFileSync(sessionFile, 'utf8'));
unlinkSync(sessionFile);
const browser = await Browser.launch();
const checks = [];
try {
  const page = await browser.newPage({width:1440,height:900});
  await page.send('Network.enable');
  await page.send('Network.setCookie', {...cookie, url:'http://127.0.0.1:4824', httpOnly:true, sameSite:'Lax'});
  await page.goto('http://127.0.0.1:4824/inspections/text-to-sql');
  for (const width of [1440, 768, 390]) {
    await page.setViewport({width,height:900});
    await page.eval(() => {
      const input = document.getElementById('sql-question');
      input.value = 'E-111의 2025년 IRIS 검사 보고서 PDF 보여줘';
      input.dispatchEvent(new Event('input', {bubbles:true}));
      document.getElementById('sql-question-form').requestSubmit();
    });
    const deadline = Date.now()+15000;
    while (await page.eval(() => document.getElementById('sql-help-panel').hidden)) {
      if (Date.now()>deadline) throw new Error('Report list did not appear');
      await new Promise(resolve => setTimeout(resolve,100));
    }
    const result = await page.eval(() => ({
      title:document.getElementById('sql-help-title').textContent,
      links:[...document.querySelectorAll('#sql-help-examples a')].map(a=>({href:a.getAttribute('href'),text:a.textContent,target:a.target})),
      error:document.getElementById('sql-error').textContent,
      executeDisabled:document.getElementById('sql-execute').disabled,
      width:innerWidth, scroll:document.documentElement.scrollWidth
    }));
    assert.equal(result.title,'IRIS 검사 보고서 PDF');
    assert.ok(result.links.length>0);
    assert.ok(result.links.every(a=>/^\/inspections\/\d+\/pdf#page=\d+$/.test(a.href) && a.target==='_blank' && a.text.includes('E-111')));
    assert.equal(result.error,'');
    assert.equal(result.executeDisabled,true);
    assert.ok(result.scroll<=result.width+1);
    checks.push({width, ...result});
    console.log(`PASS ${width}px: report links, mapped pages, disabled SQL execution, no overflow`);
  }
  writeFileSync('tmp/text_sql_pdf_browser_result.json', JSON.stringify({passed:true,checks},null,2));
} finally {
  await browser.close();
}
