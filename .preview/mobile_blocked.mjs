import { chromium, devices } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPhone 13'] });
// Імітуємо мобільний блокувальник: ріжемо Google Fonts (стиль + файли шрифту).
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort());
const p = await ctx.newPage();
try {
  await p.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await p.fill('#email', 'demo.participant@example.com');
  await p.fill('#password', 'DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),
    p.locator('form button[type="submit"], form input[type="submit"]').first().click()]);
  await p.goto(`${BASE}/admin/courses`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(1000);
  const loaded = await p.evaluate(() =>
    document.fonts ? document.fonts.check('24px "Material Symbols Rounded"') : 'no-api');
  console.log('With Google Fonts BLOCKED -> font loaded:', loaded);
  const nav = await p.$('.admin-sidebar');
  if (nav) await nav.screenshot({ path: `${DIR}/mobile-blocked-sidebar.png` });
  console.log('DONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
