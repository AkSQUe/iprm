import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();

async function login(ctx) {
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await p.fill('#email', 'demo.participant@example.com');
  await p.fill('#password', 'DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),
    p.locator('form button[type="submit"], form input[type="submit"]').first().click()]);
  return p;
}

const sizes = [
  { name: 'tablet-834', w: 834, h: 1112 },   // iPad портрет
  { name: 'tablet-768', w: 768, h: 1024 },
  { name: 'mobile-390', w: 390, h: 844 },
  { name: 'desktop-1280', w: 1280, h: 900 },
];

try {
  for (const s of sizes) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h } });
    const p = await login(ctx);
    await p.goto(`${BASE}/admin/courses`, { waitUntil: 'networkidle' });
    await p.waitForTimeout(300);
    // індикатор горизонтального переповнення сторінки
    const overflow = await p.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await p.screenshot({ path: `${DIR}/admin-courses-${s.name}.png`, fullPage: true });
    console.log(`admin-courses-${s.name}: page-overflow-x=${overflow}px <- ${p.url()}`);
    await ctx.close();
  }
  console.log('DONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
