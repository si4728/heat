import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {Browser} from '../.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
const cfg = JSON.parse(readFileSync(0, 'utf8'));
const browser = await Browser.launch();
const checks = [];
async function until(page, fn) {
  const end = Date.now() + 25000;
  while (!await page.eval(fn)) {
    if (Date.now() > end) throw new Error('Security screen timeout');
    await new Promise(r => setTimeout(r, 100));
  }
}
try {
  const page = await browser.newPage({width:390, height:844});
  await page.setViewport({width:390, height:844, mobile:true});
  await page.goto(cfg.base + '/inspections/text-to-sql');
  assert.ok(await page.eval(() => location.pathname === '/login'));
  for (const width of [390, 768, 1440]) {
    await page.setViewport({width, height:900, mobile:width === 390});
    assert.equal(await page.eval(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path:cfg.out + '/login-' + width + '.png', format:'png'});
  }
  await page.setViewport({width:390, height:844, mobile:true});
  await page.eval(({username, password}) => {
    document.querySelector('[name=username]').value = username;
    document.querySelector('[name=password]').value = password;
    document.querySelector('form').requestSubmit();
  }, {username:cfg.username, password:cfg.password});
  await until(page, () => location.pathname === '/inspections/text-to-sql' && !!document.querySelector('#sql-question'));
  assert.equal(await page.eval(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({path:cfg.out + '/mobile-text-to-sql.png', format:'png'});
  const responseHeaders = await page.eval(async () => {
    const r = await fetch(location.href);
    return {status:r.status, cache:r.headers.get('Cache-Control'), frame:r.headers.get('X-Frame-Options'),
      mime:r.headers.get('X-Content-Type-Options'), csp:r.headers.get('Content-Security-Policy')};
  });
  assert.equal(responseHeaders.status, 200);
  assert.equal(responseHeaders.cache, 'no-store');
  assert.equal(responseHeaders.frame, 'SAMEORIGIN');
  assert.equal(responseHeaders.mime, 'nosniff');
  assert.ok(responseHeaders.csp.includes("form-action 'self'"));
  checks.push('Actual password login, protected mobile navigation, three login widths and response headers');
  const csrfDenied = await page.eval(async () => (await fetch('/logout', {method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:'csrf_token=wrong'})).status);
  assert.equal(csrfDenied, 400);
  const loggedOut = await page.eval(async () => {
    const token = document.querySelector('form[action="/logout"] [name="csrf_token"]').value;
    return (await fetch('/logout', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({csrf_token:token})})).url;
  });
  assert.ok(loggedOut.includes('/login'));
  await page.goto(cfg.base + '/inspections/text-to-sql');
  assert.ok(await page.eval(() => location.pathname === '/login'));
  checks.push('CSRF rejection and logout returning browser to login');
  const failures = await page.eval(async username => {
    const responses = [];
    const token = document.querySelector('[name=csrf_token]').value;
    for (let i=0; i<6; i++) {
      const r = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({username,password:'invalid-browser-test-password',csrf_token:token})});
      responses.push({status:r.status,retry:r.headers.get('Retry-After')});
    }
    return responses;
  }, cfg.username);
  assert.deepEqual(failures.map(r => r.status), [200,200,200,200,200,429]);
  assert.ok(Number(failures[5].retry) > 0);
  checks.push('Sixth failed password attempt blocked with 429 and Retry-After');
  writeFileSync(cfg.out + '/checks.json', JSON.stringify({passed:true,checks,failures}, null, 2));
  console.log('PASS: mobile login, navigation, CSRF, logout, security headers and failed-login throttling.');
} finally {
  await browser.close();
}
