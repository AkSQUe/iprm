import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const p = await ctx.newPage();
try {
  await p.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await p.fill('#email', 'demo.participant@example.com');
  await p.fill('#password', 'DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),
    p.locator('form button[type="submit"], form input[type="submit"]').first().click()]);
  for (const [name, url] of [['ga', '/admin/google-analytics'], ['oauth', '/admin/google-oauth']]) {
    await p.goto(`${BASE}${url}`, { waitUntil: 'networkidle' });
    await p.waitForTimeout(250);
    await p.screenshot({ path: `${DIR}/integration-${name}.png`, fullPage: true });
    console.log(`integration-${name} <- ${p.url()}`);
  }
  console.log('DONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
